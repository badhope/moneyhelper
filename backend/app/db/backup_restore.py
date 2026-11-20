"""备份导入的各域还原组件：总账、报销、支付、采购、银行流水与对账。

从 db/backup.py 拆出，供 _import_backup_locked 按域调用；写入语义与顺序不变
（仍是同一个事务内逐域落库）。
"""

from __future__ import annotations

from typing import Any

import aiosqlite

from .tenant import current_user_id


async def _restore_gl(
    conn: aiosqlite.Connection, data: dict[str, Any], tenant_id: int
) -> dict[str, int]:
    """恢复总账并重映射内部 ID（科目/期间/凭证/分录行）。

    备份里的 id/外键只在原库有意义；跨库恢复必须重新分配，否则会与
    其他租户的全局自增 id 冲突，或把分录挂到错误的凭证上。
    """

    def rows(name: str) -> list[dict[str, Any]]:
        raw = data.get(name) or []
        if not isinstance(raw, list) or any(not isinstance(x, dict) for x in raw):
            raise ValueError(f"{name} 备份格式不正确")
        return raw

    accounts = rows("gl_accounts")
    periods = rows("gl_periods")
    entries = rows("gl_entries")
    lines = rows("gl_entry_lines")

    for table in ("gl_entry_lines", "gl_entries", "gl_periods", "gl_accounts"):
        await conn.execute(
            f"DELETE FROM {table} WHERE tenant_id=?", (int(tenant_id),)
        )

    account_map: dict[int, int] = {}
    for a in accounts:
        cur = await conn.execute(
            "INSERT INTO gl_accounts(tenant_id,code,name,type,parent_id,is_active,created_at)"
            " VALUES(?,?,?,?,NULL,?,?)",
            (
                int(tenant_id),
                str(a.get("code") or "")[:20],
                str(a.get("name") or "")[:80],
                str(a.get("type") or ""),
                int(a.get("is_active", 1) or 0),
                str(a.get("created_at") or ""),
            ),
        )
        account_map[int(a["id"])] = int(cur.lastrowid)
    for a in accounts:
        parent = a.get("parent_id")
        if parent is None:
            continue
        parent_id = account_map.get(int(parent))
        if parent_id is None:
            raise ValueError("总账科目上级引用缺失")
        await conn.execute(
            "UPDATE gl_accounts SET parent_id=? WHERE tenant_id=? AND id=?",
            (parent_id, int(tenant_id), account_map[int(a["id"])]),
        )

    period_map: dict[int, int] = {}
    for p in periods:
        cur = await conn.execute(
            "INSERT INTO gl_periods(tenant_id,year,month,start_date,end_date,status,"
            "created_at,closed_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                int(p.get("year") or 0),
                int(p.get("month") or 0),
                str(p.get("start_date") or ""),
                str(p.get("end_date") or ""),
                str(p.get("status") or "open"),
                str(p.get("created_at") or ""),
                str(p.get("closed_at") or ""),
            ),
        )
        period_map[int(p["id"])] = int(cur.lastrowid)

    entry_map: dict[int, int] = {}
    for e in entries:
        period_id = period_map.get(int(e.get("period_id") or 0))
        if period_id is None:
            raise ValueError("总账凭证的期间引用缺失")
        cur = await conn.execute(
            "INSERT INTO gl_entries(tenant_id,entry_no,entry_date,period_id,description,"
            "status,source,reversal_of,created_by,created_at,posted_at)"
            " VALUES(?,?,?,?,?,?,?,NULL,?,?,?)",
            (
                int(tenant_id),
                str(e.get("entry_no") or ""),
                str(e.get("entry_date") or ""),
                period_id,
                str(e.get("description") or ""),
                str(e.get("status") or "draft"),
                str(e.get("source") or "manual"),
                e.get("created_by"),
                str(e.get("created_at") or ""),
                str(e.get("posted_at") or ""),
            ),
        )
        entry_map[int(e["id"])] = int(cur.lastrowid)
    for e in entries:
        rev = e.get("reversal_of")
        if rev is None:
            continue
        rev_id = entry_map.get(int(rev))
        if rev_id is None:
            raise ValueError("总账反冲引用缺失")
        await conn.execute(
            "UPDATE gl_entries SET reversal_of=? WHERE tenant_id=? AND id=?",
            (rev_id, int(tenant_id), entry_map[int(e["id"])]),
        )

    for line in lines:
        entry_id = entry_map.get(int(line.get("entry_id") or 0))
        account_id = account_map.get(int(line.get("account_id") or 0))
        if entry_id is None or account_id is None:
            raise ValueError("总账分录行引用缺失")
        await conn.execute(
            "INSERT INTO gl_entry_lines(tenant_id,entry_id,line_no,account_id,"
            "debit_cents,credit_cents,memo) VALUES(?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                entry_id,
                int(line.get("line_no") or 0),
                account_id,
                int(line.get("debit_cents") or 0),
                int(line.get("credit_cents") or 0),
                str(line.get("memo") or "")[:200],
            ),
        )

    return {
        "gl_accounts": len(accounts),
        "gl_periods": len(periods),
        "gl_entries": len(entries),
        "gl_entry_lines": len(lines),
    }, {
        "accounts": account_map,
        "periods": period_map,
        "entries": entry_map,
    }


async def _restore_expenses(
    conn: aiosqlite.Connection,
    data: dict[str, Any],
    tenant_id: int,
    entry_map: dict[int, int],
) -> tuple[dict[str, int], dict[int, int]]:
    """恢复报销单；gl_entry_id 必须映射到新总账凭证 id。"""
    raw = data.get("expense_claims") or []
    if not isinstance(raw, list) or any(not isinstance(x, dict) for x in raw):
        raise ValueError("expense_claims 备份格式不正确")
    await conn.execute(
        "DELETE FROM expense_claims WHERE tenant_id=?", (int(tenant_id),)
    )
    claim_map: dict[int, int] = {}
    for c in raw:
        old_entry = c.get("gl_entry_id")
        new_entry = None
        if old_entry is not None:
            new_entry = entry_map.get(int(old_entry))
            if new_entry is None:
                raise ValueError("报销单关联的总账凭证引用缺失")
        cur = await conn.execute(
            "INSERT INTO expense_claims(tenant_id,claim_no,title,applicant_user_id,"
            "department_id,amount_cents,category,expense_account_id,credit_account_id,"
            "invoice_ref,attachment_name,status,approved_by,approved_at,"
            "rejected_reason,gl_entry_id,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                str(c.get("claim_no") or ""),
                str(c.get("title") or ""),
                int(c.get("applicant_user_id") or 0),
                c.get("department_id"),
                int(c.get("amount_cents") or 0),
                str(c.get("category") or ""),
                int(c.get("expense_account_id") or 0),
                int(c.get("credit_account_id") or 0),
                str(c.get("invoice_ref") or ""),
                str(c.get("attachment_name") or ""),
                str(c.get("status") or "draft"),
                c.get("approved_by"),
                str(c.get("approved_at") or ""),
                str(c.get("rejected_reason") or ""),
                new_entry,
                str(c.get("created_at") or ""),
                str(c.get("updated_at") or ""),
            ),
        )
        claim_map[int(c["id"])] = int(cur.lastrowid)
    return {"expense_claims": len(raw)}, claim_map


async def _restore_payments(
    conn: aiosqlite.Connection,
    data: dict[str, Any],
    tenant_id: int,
    claim_map: dict[int, int],
    payable_map: dict[int, int],
    entry_map: dict[int, int],
    account_map: dict[int, int],
) -> tuple[dict[str, int], dict[int, int]]:
    raw = data.get("payments") or []
    if not isinstance(raw, list) or any(not isinstance(x, dict) for x in raw):
        raise ValueError("payments 备份格式不正确")
    await conn.execute("DELETE FROM payments WHERE tenant_id=?", (int(tenant_id),))
    payment_map: dict[int, int] = {}
    for p in raw:
        old_claim = int(p.get("claim_id") or 0)
        claim_id = claim_map.get(old_claim) if old_claim else 0
        if old_claim and claim_id is None:
            raise ValueError("付款关联的报销单引用缺失")
        old_payable = p.get("payable_id")
        payable_id = None
        if old_payable is not None:
            payable_id = payable_map.get(int(old_payable))
            if payable_id is None:
                raise ValueError("付款关联的应付单引用缺失")
        account_id = account_map.get(int(p.get("bank_account_id") or 0))
        if account_id is None:
            raise ValueError("付款关联的银行科目引用缺失")
        old_entry = p.get("gl_entry_id")
        entry_id = None
        if old_entry is not None:
            entry_id = entry_map.get(int(old_entry))
            if entry_id is None:
                raise ValueError("付款关联的总账凭证引用缺失")
        cur = await conn.execute(
            "INSERT INTO payments(tenant_id,payment_no,claim_id,payable_id,amount_cents,"
            "payee,bank_account_id,method,status,paid_at,gl_entry_id,created_by,note,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                str(p.get("payment_no") or ""),
                int(claim_id or 0),
                payable_id,
                int(p.get("amount_cents") or 0),
                str(p.get("payee") or ""),
                account_id,
                str(p.get("method") or "bank"),
                str(p.get("status") or "paid"),
                str(p.get("paid_at") or ""),
                entry_id,
                p.get("created_by"),
                str(p.get("note") or ""),
                str(p.get("created_at") or ""),
                str(p.get("updated_at") or ""),
            ),
        )
        payment_map[int(p["id"])] = int(cur.lastrowid)
    return {"payments": len(raw)}, payment_map


async def _restore_procurement(
    conn: aiosqlite.Connection,
    data: dict[str, Any],
    tenant_id: int,
    account_map: dict[int, int],
    entry_map: dict[int, int],
) -> tuple[dict[str, int], dict[int, int], list[tuple[int, int]]]:
    """恢复供应商 / 采购单 / 应付单。

    付款与应付单互相引用（应付单记 payment_id，付款记 payable_id），
    这里先不写 payment_id，返回待回填清单，等 payments 落库后由调用方补上。
    """
    vendors = data.get("vendors") or []
    orders = data.get("purchase_orders") or []
    payables = data.get("payables") or []
    for name, rows in (
        ("vendors", vendors),
        ("purchase_orders", orders),
        ("payables", payables),
    ):
        if not isinstance(rows, list) or any(not isinstance(x, dict) for x in rows):
            raise ValueError(f"{name} 备份格式不正确")

    await conn.execute("DELETE FROM payables WHERE tenant_id=?", (int(tenant_id),))
    await conn.execute(
        "DELETE FROM purchase_orders WHERE tenant_id=?", (int(tenant_id),)
    )
    await conn.execute("DELETE FROM vendors WHERE tenant_id=?", (int(tenant_id),))

    vendor_map: dict[int, int] = {}
    for v in vendors:
        cur = await conn.execute(
            "INSERT INTO vendors(tenant_id,code,name,tax_no,contact,phone,status,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                str(v.get("code") or ""),
                str(v.get("name") or ""),
                str(v.get("tax_no") or ""),
                str(v.get("contact") or ""),
                str(v.get("phone") or ""),
                str(v.get("status") or "active"),
                str(v.get("created_at") or ""),
            ),
        )
        vendor_map[int(v["id"])] = int(cur.lastrowid)

    po_map: dict[int, int] = {}
    for po in orders:
        new_vendor = vendor_map.get(int(po.get("vendor_id") or 0))
        if new_vendor is None:
            raise ValueError("采购单关联的供应商引用缺失")
        cur = await conn.execute(
            "INSERT INTO purchase_orders(tenant_id,po_no,vendor_id,order_date,"
            "expected_date,amount_cents,description,status,approved_by,approved_at,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                str(po.get("po_no") or ""),
                new_vendor,
                str(po.get("order_date") or ""),
                str(po.get("expected_date") or ""),
                int(po.get("amount_cents") or 0),
                str(po.get("description") or ""),
                str(po.get("status") or "draft"),
                po.get("approved_by"),
                str(po.get("approved_at") or ""),
                str(po.get("created_at") or ""),
                str(po.get("updated_at") or ""),
            ),
        )
        po_map[int(po["id"])] = int(cur.lastrowid)

    payable_map: dict[int, int] = {}
    pending_payments: list[tuple[int, int]] = []
    for ap in payables:
        new_vendor = vendor_map.get(int(ap.get("vendor_id") or 0))
        if new_vendor is None:
            raise ValueError("应付单关联的供应商引用缺失")
        old_po = ap.get("po_id")
        new_po = None
        if old_po is not None:
            new_po = po_map.get(int(old_po))
            if new_po is None:
                raise ValueError("应付单关联的采购单引用缺失")
        new_expense = account_map.get(int(ap.get("expense_account_id") or 0))
        new_payable_account = account_map.get(int(ap.get("payable_account_id") or 0))
        if new_expense is None or new_payable_account is None:
            raise ValueError("应付单关联的会计科目引用缺失")
        old_entry = ap.get("gl_entry_id")
        new_entry = None
        if old_entry is not None:
            new_entry = entry_map.get(int(old_entry))
            if new_entry is None:
                raise ValueError("应付单关联的总账凭证引用缺失")
        cur = await conn.execute(
            "INSERT INTO payables(tenant_id,payable_no,vendor_id,po_id,invoice_no,"
            "invoice_date,due_date,amount_cents,tax_cents,expense_account_id,"
            "payable_account_id,status,gl_entry_id,payment_id,approved_by,approved_at,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,?,?,?)",
            (
                int(tenant_id),
                str(ap.get("payable_no") or ""),
                new_vendor,
                new_po,
                str(ap.get("invoice_no") or ""),
                str(ap.get("invoice_date") or ""),
                str(ap.get("due_date") or ""),
                int(ap.get("amount_cents") or 0),
                int(ap.get("tax_cents") or 0),
                new_expense,
                new_payable_account,
                str(ap.get("status") or "draft"),
                new_entry,
                ap.get("approved_by"),
                str(ap.get("approved_at") or ""),
                str(ap.get("created_at") or ""),
                str(ap.get("updated_at") or ""),
            ),
        )
        new_payable_id = int(cur.lastrowid)
        payable_map[int(ap["id"])] = new_payable_id
        if ap.get("payment_id") is not None:
            pending_payments.append((new_payable_id, int(ap["payment_id"])))
    return (
        {
            "vendors": len(vendors),
            "purchase_orders": len(orders),
            "payables": len(payables),
        },
        payable_map,
        pending_payments,
    )


async def _restore_bank_transactions(
    conn: aiosqlite.Connection,
    data: dict[str, Any],
    tenant_id: int,
    payment_map: dict[int, int],
    account_map: dict[int, int],
) -> dict[str, int]:
    raw = data.get("bank_transactions") or []
    if not isinstance(raw, list) or any(not isinstance(x, dict) for x in raw):
        raise ValueError("bank_transactions 备份格式不正确")
    await conn.execute(
        "DELETE FROM bank_transactions WHERE tenant_id=?", (int(tenant_id),)
    )
    for b in raw:
        account_id = account_map.get(int(b.get("bank_account_id") or 0))
        if account_id is None:
            raise ValueError("银行流水关联的银行科目引用缺失")
        old_payment = b.get("payment_id")
        new_payment = None
        if old_payment is not None:
            new_payment = payment_map.get(int(old_payment))
            if new_payment is None:
                raise ValueError("银行流水关联的付款引用缺失")
        await conn.execute(
            "INSERT INTO bank_transactions(tenant_id,bank_account_id,txn_date,direction,"
            "amount_cents,counterparty,memo,bank_ref,status,payment_id,matched_by,"
            "matched_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                account_id,
                str(b.get("txn_date") or ""),
                str(b.get("direction") or ""),
                int(b.get("amount_cents") or 0),
                str(b.get("counterparty") or ""),
                str(b.get("memo") or ""),
                str(b.get("bank_ref") or ""),
                str(b.get("status") or "unmatched"),
                new_payment,
                b.get("matched_by"),
                str(b.get("matched_at") or ""),
                str(b.get("created_at") or ""),
                str(b.get("updated_at") or ""),
            ),
        )
    return {"bank_transactions": len(raw)}


async def _restore_bank_reconciliations(
    conn: aiosqlite.Connection,
    data: dict[str, Any],
    tenant_id: int,
    account_map: dict[int, int],
    period_map: dict[int, int],
) -> dict[str, int]:
    raw = data.get("bank_reconciliations") or []
    if not isinstance(raw, list) or any(not isinstance(x, dict) for x in raw):
        raise ValueError("bank_reconciliations 备份格式不正确")
    await conn.execute(
        "DELETE FROM bank_reconciliations WHERE tenant_id=?", (int(tenant_id),)
    )
    for r in raw:
        account_id = account_map.get(int(r.get("bank_account_id") or 0))
        period_id = period_map.get(int(r.get("period_id") or 0))
        if account_id is None or period_id is None:
            raise ValueError("对账记录的账户或期间引用缺失")
        await conn.execute(
            "INSERT INTO bank_reconciliations(tenant_id,bank_account_id,period_id,"
            "statement_balance_cents,book_balance_cents,difference_cents,status,note,"
            "created_by,created_at,closed_by,closed_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                account_id,
                period_id,
                int(r.get("statement_balance_cents") or 0),
                int(r.get("book_balance_cents") or 0),
                int(r.get("difference_cents") or 0),
                str(r.get("status") or "open"),
                str(r.get("note") or ""),
                r.get("created_by"),
                str(r.get("created_at") or ""),
                r.get("closed_by"),
                str(r.get("closed_at") or ""),
            ),
        )
    return {"bank_reconciliations": len(raw)}


async def _restore_table(
    conn: aiosqlite.Connection,
    name: str,
    rows: Any,
    sql: str,
) -> int:
    """把备份列表写回指定表。

    统一注入当前租户：备份包本身不带 user_id（也不该带），恢复时一律落到
    当前登录用户名下。

    错误策略（专家评审 P0-7）：**不再静默跳过坏行**。旧实现 `except: continue`
    会让外键失败/字段不匹配的行悄悄消失，接口却返回 ok，用户以为恢复成功。
    现在收集失败行并在最后抛错，由调用方整体回滚。
    """
    if not isinstance(rows, list):
        return 0
    uid = current_user_id()
    n = 0
    failed: list[str] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            failed.append(f"#{idx}: 非对象")
            continue
        try:
            await conn.execute(sql, {**row, "user_id": uid})
            n += 1
        except Exception as exc:  # noqa: BLE001
            failed.append(f"#{idx}: {type(exc).__name__}: {exc}")
    if failed:
        raise ValueError(
            f"恢复 {name} 时有 {len(failed)} 行失败（已回滚）：" + "; ".join(failed[:3])
        )
    return n

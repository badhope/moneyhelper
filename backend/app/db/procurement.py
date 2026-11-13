"""采购/应付数据层（切片 8）：供应商 → 采购单 → 应付单 → 付款。

- 采购单审核只代表采购获批，不生成总账；
- 应付单审核生成「借费用/资产、贷应付」凭证草稿；
- 付款生成「借应付、贷银行」凭证草稿，并登记 payments（claim_id=0）；
- 过账仍由会计在总账页确认，不自动改账。
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Any

from ..calculations.gl import to_cents
from ._core import _conn, fetch_all, fetch_one, get_write_lock
from .gl import gl_create_entry, gl_delete_draft_entry, gl_get_account


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _row(value: Any) -> dict[str, Any] | None:
    return dict(value) if value is not None else None


def _amount(data: dict[str, Any]) -> dict[str, Any]:
    result = dict(data)
    for key in ("amount_cents", "tax_cents"):
        if key in result:
            result[key.replace("_cents", "")] = round(
                int(result.get(key) or 0) / 100, 2
            )
    return result


def _parse_date(value: Any, field: str = "日期") -> str:
    try:
        return date.fromisoformat(str(value or "").strip()).isoformat()
    except ValueError:
        raise ValueError(f"{field}需为 YYYY-MM-DD") from None


# ---------------------------------------------------------------------------
# 供应商
# ---------------------------------------------------------------------------


async def vendor_list(tenant_id: int) -> list[dict[str, Any]]:
    return await fetch_all(
        "SELECT id,tenant_id,code,name,tax_no,contact,phone,status,created_at"
        " FROM vendors WHERE tenant_id=? ORDER BY code,id",
        (int(tenant_id),),
    )


async def vendor_create(
    tenant_id: int,
    code: str,
    name: str,
    tax_no: str = "",
    contact: str = "",
    phone: str = "",
) -> dict[str, Any]:
    clean_code = str(code or "").strip()[:30]
    clean_name = str(name or "").strip()[:120]
    if not clean_code or not clean_name:
        raise ValueError("供应商编码和名称不能为空")
    conn = await _conn()
    try:
        cur = await conn.execute(
            "INSERT INTO vendors(tenant_id,code,name,tax_no,contact,phone,status,created_at)"
            " VALUES(?,?,?,?,?,?,'active',?)",
            (
                int(tenant_id),
                clean_code,
                clean_name,
                str(tax_no or "")[:40],
                str(contact or "")[:60],
                str(phone or "")[:40],
                _now(),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("供应商编码已存在") from exc
    await conn.commit()
    row = await fetch_one(
        "SELECT id,tenant_id,code,name,tax_no,contact,phone,status,created_at"
        " FROM vendors WHERE tenant_id=? AND id=?",
        (int(tenant_id), int(cur.lastrowid)),
    )
    assert row is not None
    return dict(row)


async def _assert_vendor(tenant_id: int, vendor_id: int) -> dict[str, Any]:
    row = await fetch_one(
        "SELECT id,tenant_id,code,name,status FROM vendors WHERE tenant_id=? AND id=?",
        (int(tenant_id), int(vendor_id)),
    )
    if row is None or str(row["status"]) != "active":
        raise ValueError("供应商不存在或已停用")
    return dict(row)


# ---------------------------------------------------------------------------
# 采购单
# ---------------------------------------------------------------------------

_PO_SELECT = (
    "SELECT po.id,po.tenant_id,po.po_no,po.vendor_id,po.order_date,po.expected_date,"
    "po.amount_cents,po.description,po.status,po.approved_by,po.approved_at,"
    "po.created_at,po.updated_at,v.code AS vendor_code,v.name AS vendor_name"
    " FROM purchase_orders po"
    " LEFT JOIN vendors v ON v.id=po.vendor_id AND v.tenant_id=po.tenant_id"
)


async def po_get(tenant_id: int, po_id: int) -> dict[str, Any] | None:
    row = await fetch_one(
        _PO_SELECT + " WHERE po.tenant_id=? AND po.id=?",
        (int(tenant_id), int(po_id)),
    )
    return _amount(row) if row is not None else None


async def po_list(tenant_id: int) -> list[dict[str, Any]]:
    return [
        _amount(r)
        for r in await fetch_all(
            _PO_SELECT + " WHERE po.tenant_id=? ORDER BY po.id DESC LIMIT 300",
            (int(tenant_id),),
        )
    ]


async def po_create(
    tenant_id: int,
    vendor_id: int,
    order_date: str,
    expected_date: str,
    amount: Any,
    description: str = "",
) -> dict[str, Any]:
    await _assert_vendor(tenant_id, vendor_id)
    order_day = _parse_date(order_date, "采购日期")
    expected = _parse_date(expected_date, "预计到货日期") if expected_date else ""
    amount_cents = to_cents(amount)
    if amount_cents <= 0:
        raise ValueError("采购金额必须大于 0")
    month = datetime.now().strftime("%Y%m")
    conn = await _conn()
    async with get_write_lock():
        await conn.execute("BEGIN IMMEDIATE")
        try:
            row = await (
                await conn.execute(
                    "SELECT COUNT(*) AS n FROM purchase_orders"
                    " WHERE tenant_id=? AND po_no LIKE ?",
                    (int(tenant_id), f"PO-{month}-%"),
                )
            ).fetchone()
            seq = int(row["n"]) + 1 if row else 1
            po_no = f"PO-{month}-{seq:04d}"
            cur = await conn.execute(
                "INSERT INTO purchase_orders(tenant_id,po_no,vendor_id,order_date,"
                "expected_date,amount_cents,description,status,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,'draft',?,?)",
                (
                    int(tenant_id),
                    po_no,
                    int(vendor_id),
                    order_day,
                    expected,
                    amount_cents,
                    str(description or "")[:300],
                    _now(),
                    _now(),
                ),
            )
            await conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            await conn.execute("ROLLBACK")
            raise ValueError("采购单号冲突，请重试") from exc
        except BaseException:
            await conn.execute("ROLLBACK")
            raise
    created = await po_get(tenant_id, int(cur.lastrowid))
    assert created is not None
    return created


async def po_submit(tenant_id: int, po_id: int) -> dict[str, Any]:
    conn = await _conn()
    cur = await conn.execute(
        "UPDATE purchase_orders SET status='submitted',updated_at=?"
        " WHERE tenant_id=? AND id=? AND status='draft'",
        (_now(), int(tenant_id), int(po_id)),
    )
    await conn.commit()
    if not cur.rowcount:
        raise ValueError("只有草稿采购单可以提交")
    po = await po_get(tenant_id, po_id)
    assert po is not None
    return po


async def po_approve(tenant_id: int, po_id: int, approved_by: int) -> dict[str, Any]:
    conn = await _conn()
    cur = await conn.execute(
        "UPDATE purchase_orders SET status='approved',approved_by=?,approved_at=?,"
        "updated_at=? WHERE tenant_id=? AND id=? AND status='submitted'",
        (_now(), int(approved_by), _now(), int(tenant_id), int(po_id)),
    )
    await conn.commit()
    if not cur.rowcount:
        raise ValueError("只有已提交采购单可以审核")
    po = await po_get(tenant_id, po_id)
    assert po is not None
    return po


# ---------------------------------------------------------------------------
# 应付单
# ---------------------------------------------------------------------------

_PAYABLE_SELECT = (
    "SELECT p.id,p.tenant_id,p.payable_no,p.vendor_id,p.po_id,p.invoice_no,"
    "p.invoice_date,p.due_date,p.amount_cents,p.tax_cents,p.expense_account_id,"
    "p.payable_account_id,p.status,p.gl_entry_id,p.payment_id,p.approved_by,"
    "p.approved_at,p.created_at,p.updated_at,v.code AS vendor_code,v.name AS vendor_name,"
    "po.po_no,ge.entry_no AS gl_entry_no,ge.status AS gl_status,pay.payment_no"
    " FROM payables p"
    " LEFT JOIN vendors v ON v.id=p.vendor_id AND v.tenant_id=p.tenant_id"
    " LEFT JOIN purchase_orders po ON po.id=p.po_id AND po.tenant_id=p.tenant_id"
    " LEFT JOIN gl_entries ge ON ge.id=p.gl_entry_id AND ge.tenant_id=p.tenant_id"
    " LEFT JOIN payments pay ON pay.id=p.payment_id AND pay.tenant_id=p.tenant_id"
)


async def payable_get(tenant_id: int, payable_id: int) -> dict[str, Any] | None:
    row = await fetch_one(
        _PAYABLE_SELECT + " WHERE p.tenant_id=? AND p.id=?",
        (int(tenant_id), int(payable_id)),
    )
    return _amount(row) if row is not None else None


async def payable_list(tenant_id: int) -> list[dict[str, Any]]:
    return [
        _amount(r)
        for r in await fetch_all(
            _PAYABLE_SELECT + " WHERE p.tenant_id=? ORDER BY p.id DESC LIMIT 300",
            (int(tenant_id),),
        )
    ]


async def _assert_payable_accounts(
    tenant_id: int, expense_account_id: int, payable_account_id: int
) -> None:
    expense = await gl_get_account(tenant_id, expense_account_id)
    if expense is None or not expense["is_active"] or expense["type"] not in (
        "asset",
        "expense",
    ):
        raise ValueError("借方科目必须是启用的资产或费用类科目")
    payable = await gl_get_account(tenant_id, payable_account_id)
    if payable is None or not payable["is_active"] or payable["type"] != "liability":
        raise ValueError("贷方科目必须是启用的负债类科目")


async def payable_create(
    tenant_id: int,
    vendor_id: int,
    po_id: int | None,
    invoice_no: str,
    invoice_date: str,
    due_date: str,
    amount: Any,
    tax: Any,
    expense_account_id: int,
    payable_account_id: int,
) -> dict[str, Any]:
    await _assert_vendor(tenant_id, vendor_id)
    invoice_day = _parse_date(invoice_date, "发票日期")
    due = _parse_date(due_date, "到期日") if due_date else ""
    amount_cents = to_cents(amount)
    tax_cents = to_cents(tax or 0)
    if amount_cents <= 0:
        raise ValueError("应付金额必须大于 0")
    if tax_cents > amount_cents:
        raise ValueError("税额不能大于价税合计")
    if po_id not in (None, ""):
        po = await po_get(tenant_id, int(po_id))
        if po is None:
            raise ValueError("采购单不存在")
        if po["status"] != "approved":
            raise ValueError("只有已审核采购单可以生成应付")
        if int(po["vendor_id"]) != int(vendor_id):
            raise ValueError("采购单供应商与应付单不一致")
        po_id = int(po_id)
    else:
        po_id = None
    await _assert_payable_accounts(tenant_id, expense_account_id, payable_account_id)
    month = datetime.now().strftime("%Y%m")
    conn = await _conn()
    async with get_write_lock():
        await conn.execute("BEGIN IMMEDIATE")
        try:
            row = await (
                await conn.execute(
                    "SELECT COUNT(*) AS n FROM payables WHERE tenant_id=? AND payable_no LIKE ?",
                    (int(tenant_id), f"AP-{month}-%"),
                )
            ).fetchone()
            seq = int(row["n"]) + 1 if row else 1
            payable_no = f"AP-{month}-{seq:04d}"
            cur = await conn.execute(
                "INSERT INTO payables(tenant_id,payable_no,vendor_id,po_id,invoice_no,"
                "invoice_date,due_date,amount_cents,tax_cents,expense_account_id,"
                "payable_account_id,status,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,'draft',?,?)",
                (
                    int(tenant_id),
                    payable_no,
                    int(vendor_id),
                    po_id,
                    str(invoice_no or "")[:80],
                    invoice_day,
                    due,
                    amount_cents,
                    tax_cents,
                    int(expense_account_id),
                    int(payable_account_id),
                    _now(),
                    _now(),
                ),
            )
            await conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            await conn.execute("ROLLBACK")
            raise ValueError("应付单号冲突，请重试") from exc
        except BaseException:
            await conn.execute("ROLLBACK")
            raise
    created = await payable_get(tenant_id, int(cur.lastrowid))
    assert created is not None
    return created


async def payable_submit(tenant_id: int, payable_id: int) -> dict[str, Any]:
    conn = await _conn()
    cur = await conn.execute(
        "UPDATE payables SET status='submitted',updated_at=?"
        " WHERE tenant_id=? AND id=? AND status='draft'",
        (_now(), int(tenant_id), int(payable_id)),
    )
    await conn.commit()
    if not cur.rowcount:
        raise ValueError("只有草稿应付单可以提交")
    payable = await payable_get(tenant_id, payable_id)
    assert payable is not None
    return payable


async def payable_approve(
    tenant_id: int, payable_id: int, approved_by: int
) -> dict[str, Any]:
    payable = await payable_get(tenant_id, payable_id)
    if payable is None:
        raise ValueError("应付单不存在")
    if payable["status"] != "submitted":
        raise ValueError("只有已提交应付单可以审核")
    await _assert_payable_accounts(
        tenant_id,
        int(payable["expense_account_id"]),
        int(payable["payable_account_id"]),
    )
    # 抢占式状态：避免两个审批人同时通过、重复生成凭证。
    conn = await _conn()
    cur = await conn.execute(
        "UPDATE payables SET status='approving',updated_at=?"
        " WHERE tenant_id=? AND id=? AND status='submitted'",
        (_now(), int(tenant_id), int(payable_id)),
    )
    await conn.commit()
    if not cur.rowcount:
        raise ValueError("应付单已被处理")

    amount = f"{int(payable['amount_cents']) // 100}.{int(payable['amount_cents']) % 100:02d}"
    try:
        entry = await gl_create_entry(
            tenant_id,
            str(payable["invoice_date"]),
            f"应付 {payable['payable_no']} {payable['vendor_name'] or ''}".strip(),
            [
                {
                    "account_id": int(payable["expense_account_id"]),
                    "debit": amount,
                    "credit": 0,
                    "memo": payable["invoice_no"] or "采购应付",
                },
                {
                    "account_id": int(payable["payable_account_id"]),
                    "debit": 0,
                    "credit": amount,
                    "memo": payable["vendor_name"] or "",
                },
            ],
            approved_by,
        )
    except Exception:
        await conn.execute(
            "UPDATE payables SET status='submitted',updated_at=?"
            " WHERE tenant_id=? AND id=?",
            (_now(), int(tenant_id), int(payable_id)),
        )
        await conn.commit()
        raise

    try:
        await conn.execute(
            "UPDATE payables SET status='approved',approved_by=?,approved_at=?,"
            "gl_entry_id=?,updated_at=? WHERE tenant_id=? AND id=?",
            (
                int(approved_by),
                _now(),
                int(entry["id"]),
                _now(),
                int(tenant_id),
                int(payable_id),
            ),
        )
        await conn.commit()
    except BaseException:
        await conn.execute(
            "UPDATE payables SET status='submitted',updated_at=?"
            " WHERE tenant_id=? AND id=?",
            (_now(), int(tenant_id), int(payable_id)),
        )
        await conn.commit()
        try:
            await gl_delete_draft_entry(tenant_id, int(entry["id"]))
        except Exception:  # noqa: BLE001
            pass
        raise
    approved = await payable_get(tenant_id, payable_id)
    assert approved is not None
    return approved


async def payable_pay(
    tenant_id: int,
    payable_id: int,
    bank_account_id: int,
    created_by: int,
    note: str = "",
) -> dict[str, Any]:
    payable = await payable_get(tenant_id, payable_id)
    if payable is None:
        raise ValueError("应付单不存在")
    if payable["status"] != "approved":
        raise ValueError("只有已审核应付单可以付款")
    if payable["payment_id"]:
        raise ValueError("该应付单已经付款")
    bank = await gl_get_account(tenant_id, bank_account_id)
    if bank is None or not bank["is_active"] or bank["type"] != "asset":
        raise ValueError("付款账户必须是启用的资产类科目")
    amount = f"{int(payable['amount_cents']) // 100}.{int(payable['amount_cents']) % 100:02d}"
    entry = await gl_create_entry(
        tenant_id,
        datetime.now().date().isoformat(),
        f"付款 {payable['payable_no']} {payable['vendor_name'] or ''}".strip(),
        [
            {
                "account_id": int(payable["payable_account_id"]),
                "debit": amount,
                "credit": 0,
                "memo": "应付付款",
            },
            {
                "account_id": int(bank_account_id),
                "debit": 0,
                "credit": amount,
                "memo": "",
            },
        ],
        created_by,
    )
    month = datetime.now().strftime("%Y%m")
    conn = await _conn()
    async with get_write_lock():
        await conn.execute("BEGIN IMMEDIATE")
        try:
            row = await (
                await conn.execute(
                    "SELECT COUNT(*) AS n FROM payments WHERE tenant_id=? AND payment_no LIKE ?",
                    (int(tenant_id), f"PAY-{month}-%"),
                )
            ).fetchone()
            seq = int(row["n"]) + 1 if row else 1
            payment_no = f"PAY-{month}-{seq:04d}"
            cur = await conn.execute(
                "INSERT INTO payments(tenant_id,payment_no,claim_id,payable_id,amount_cents,"
                "payee,bank_account_id,method,status,paid_at,gl_entry_id,created_by,note,"
                "created_at,updated_at) VALUES(?,?,0,?,?,?,?, 'bank','paid',?,?,?,?,?,?)",
                (
                    int(tenant_id),
                    payment_no,
                    int(payable_id),
                    int(payable["amount_cents"]),
                    str(payable["vendor_name"] or payable["payable_no"])[:120],
                    int(bank_account_id),
                    _now(),
                    int(entry["id"]),
                    int(created_by),
                    str(note or "")[:300],
                    _now(),
                    _now(),
                ),
            )
            payment_id = int(cur.lastrowid)
            await conn.execute(
                "UPDATE payables SET status='paid',payment_id=?,updated_at=?"
                " WHERE tenant_id=? AND id=?",
                (payment_id, _now(), int(tenant_id), int(payable_id)),
            )
            await conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            await conn.execute("ROLLBACK")
            try:
                await gl_delete_draft_entry(tenant_id, int(entry["id"]))
            except Exception:  # noqa: BLE001
                pass
            raise ValueError("该应付单已经付款") from exc
        except BaseException:
            await conn.execute("ROLLBACK")
            try:
                await gl_delete_draft_entry(tenant_id, int(entry["id"]))
            except Exception:  # noqa: BLE001
                pass
            raise
    paid = await payable_get(tenant_id, payable_id)
    assert paid is not None
    return paid

"""银行流水：导入、匹配、取消匹配。

从 banking.py 拆出；对账见 banking_recon.py。
"""

from __future__ import annotations

import csv
import io
import sqlite3
from datetime import date
from typing import Any

from ..calculations.chart import pick_account_code
from ..calculations.gl import to_cents
from ..timeutil import now_str as _now
from ._core import _conn, fetch_all, fetch_one, get_write_lock
from .banking_payments import _money, payment_get
from .gl import gl_bootstrap, gl_create_entry, gl_get_account, gl_list_accounts


def _bank(row: Any) -> dict[str, Any]:
    return _money(row)


_BANK_SELECT = (
    "SELECT b.id,b.tenant_id,b.bank_account_id,b.txn_date,b.direction,b.amount_cents,"
    "b.counterparty,b.memo,b.bank_ref,b.status,b.payment_id,b.matched_by,b.matched_at,"
    "b.created_at,b.updated_at,p.payment_no,a.code AS bank_account_code,"
    "a.name AS bank_account_name"
    " FROM bank_transactions b"
    " LEFT JOIN payments p ON p.id=b.payment_id AND p.tenant_id=b.tenant_id"
    " LEFT JOIN gl_accounts a ON a.id=b.bank_account_id AND a.tenant_id=b.tenant_id"
)




async def bank_get(tenant_id: int, txn_id: int) -> dict[str, Any] | None:
    row = await fetch_one(
        _BANK_SELECT + " WHERE b.tenant_id=? AND b.id=?",
        (int(tenant_id), int(txn_id)),
    )
    return _bank(row) if row is not None else None


async def bank_list(
    tenant_id: int,
    status: str | None = None,
    bank_account_id: int | None = None,
) -> list[dict[str, Any]]:
    sql = _BANK_SELECT + " WHERE b.tenant_id=?"
    params: list[Any] = [int(tenant_id)]
    if status:
        sql += " AND b.status=?"
        params.append(str(status))
    if bank_account_id is not None:
        sql += " AND b.bank_account_id=?"
        params.append(int(bank_account_id))
    sql += " ORDER BY b.txn_date DESC,b.id DESC LIMIT 500"
    return [_bank(r) for r in await fetch_all(sql, tuple(params))]


async def _assert_bank_account(tenant_id: int, account_id: int) -> dict[str, Any]:
    account = await gl_get_account(tenant_id, account_id)
    if account is None or not account["is_active"] or account["type"] != "asset":
        raise ValueError("银行账户必须是启用的资产类科目")
    return account


async def bank_create(
    tenant_id: int,
    bank_account_id: int,
    txn_date: str,
    direction: str,
    amount: Any,
    counterparty: str = "",
    memo: str = "",
    bank_ref: str = "",
) -> dict[str, Any]:
    await _assert_bank_account(tenant_id, bank_account_id)
    try:
        d = date.fromisoformat(str(txn_date or "").strip())
    except ValueError:
        raise ValueError("交易日期需为 YYYY-MM-DD") from None
    if direction not in ("in", "out"):
        raise ValueError("direction 只能是 in / out")
    amount_cents = to_cents(amount)
    if amount_cents <= 0:
        raise ValueError("交易金额必须大于 0")
    conn = await _conn()
    cur = await conn.execute(
        "INSERT INTO bank_transactions(tenant_id,bank_account_id,txn_date,direction,"
        "amount_cents,counterparty,memo,bank_ref,status,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,'unmatched',?,?)",
        (
            int(tenant_id),
            int(bank_account_id),
            d.isoformat(),
            direction,
            amount_cents,
            str(counterparty or "")[:120],
            str(memo or "")[:200],
            str(bank_ref or "")[:120],
            _now(),
            _now(),
        ),
    )
    await conn.commit()
    created = await bank_get(tenant_id, int(cur.lastrowid))
    assert created is not None
    return created


def _parse_csv_rows(csv_text: str) -> list[dict[str, Any]]:
    text = str(csv_text or "").lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV 缺少表头")
    field_map = {str(x).strip().lower(): x for x in reader.fieldnames if x}
    required = {"date", "amount"}
    if not required.issubset(field_map):
        raise ValueError("CSV 至少需要 date,amount 两列")
    out: list[dict[str, Any]] = []
    for idx, raw in enumerate(reader, 2):
        def get(name: str, row: dict[str, Any] = raw) -> str:
            key = field_map.get(name)
            return str(row.get(key) or "").strip() if key else ""

        amount_text = get("amount")
        if not amount_text:
            raise ValueError(f"第 {idx} 行金额为空")
        negative = amount_text.startswith("-")
        amount_abs = amount_text.lstrip("+-")
        amount_cents = to_cents(amount_abs)
        if amount_cents <= 0:
            raise ValueError(f"第 {idx} 行金额必须大于 0")
        direction = get("direction").lower()
        if direction not in ("in", "out"):
            direction = "out" if negative else "in"
        try:
            d = date.fromisoformat(get("date"))
        except ValueError:
            raise ValueError(f"第 {idx} 行日期需为 YYYY-MM-DD") from None
        out.append(
            {
                "txn_date": d.isoformat(),
                "direction": direction,
                "amount_cents": amount_cents,
                "counterparty": get("counterparty")[:120],
                "memo": get("memo")[:200],
                "bank_ref": get("ref")[:120],
            }
        )
    return out


async def bank_import_csv(
    tenant_id: int, bank_account_id: int, csv_text: str, auto_entry: bool = True
) -> dict[str, Any]:
    """导入银行流水；auto_entry=True 时顺手把每条流水转成一张草稿凭证。

    定位是"全托管"：用户只负责把流水弄进来，分录由系统按规则生成（借方费用/资产、
    贷方银行，或反向），生成的只是草稿——报表页的"一键出报表"会代过账。这样
    "导入流水 → 出报表"整条链路没有任何需要用户懂会计的环节。
    """
    await _assert_bank_account(tenant_id, bank_account_id)
    rows = _parse_csv_rows(csv_text)
    if not rows:
        raise ValueError("CSV 没有数据行")
    conn = await _conn()
    inserted: list[dict[str, Any]] = []
    async with get_write_lock():
        await conn.execute("BEGIN IMMEDIATE")
        try:
            for r in rows:
                cur = await conn.execute(
                    "INSERT INTO bank_transactions(tenant_id,bank_account_id,txn_date,direction,"
                    "amount_cents,counterparty,memo,bank_ref,status,created_at,updated_at)"
                    " VALUES(?,?,?,?,?,?,?,?,'unmatched',?,?)",
                    (
                        int(tenant_id),
                        int(bank_account_id),
                        r["txn_date"],
                        r["direction"],
                        int(r["amount_cents"]),
                        r["counterparty"],
                        r["memo"],
                        r["bank_ref"],
                        _now(),
                        _now(),
                    ),
                )
                inserted.append({**r, "id": int(cur.lastrowid)})
            await conn.execute("COMMIT")
        except BaseException:
            await conn.execute("ROLLBACK")
            raise

    result: dict[str, Any] = {"imported": len(inserted), "entries_created": 0}
    if auto_entry and inserted:
        result["entries_created"] = await _entries_for_import(tenant_id, bank_account_id, inserted)
    return result


async def _entries_for_import(
    tenant_id: int, bank_account_id: int, rows: list[dict[str, Any]]
) -> int:
    """给刚导入的流水批量生成草稿凭证，返回成功条数。

    任何一条失败（期间已关账、科目被删等）都不影响其余流水，也不影响导入本身——
    导入的数据是事实，凭证是可重建的派生物。
    """
    # 不同月份可能跨期，按"年月"各自建账一次
    booted: set[tuple[int, int]] = set()
    accounts = {str(a.get("code")): int(a["id"]) for a in await gl_list_accounts(tenant_id)}
    made = 0
    for r in rows:
        day = date.fromisoformat(str(r["txn_date"]))
        if (day.year, day.month) not in booted:
            await gl_bootstrap(tenant_id, str(r["txn_date"]))
            accounts = {str(a.get("code")): int(a["id"]) for a in await gl_list_accounts(tenant_id)}
            booted.add((day.year, day.month))
        code = pick_account_code(
            str(r["direction"]), str(r.get("memo", "")), str(r.get("counterparty", ""))
        )
        contra = accounts.get(code)
        if contra is None:
            continue
        amount = round(int(r["amount_cents"]) / 100, 2)
        if amount <= 0:
            continue
        bank_side = {"account_id": int(bank_account_id), "debit": 0.0, "credit": 0.0}
        other_side = {"account_id": contra, "debit": 0.0, "credit": 0.0}
        if str(r["direction"]) == "out":
            other_side["debit"], bank_side["credit"] = amount, amount
        else:
            bank_side["debit"], other_side["credit"] = amount, amount
        label = " ".join(x for x in (str(r.get("counterparty", "")), str(r.get("memo", ""))) if x).strip()
        try:
            entry = await gl_create_entry(
                tenant_id, str(r["txn_date"]), label or "银行流水", [other_side, bank_side], 0
            )
        except (TypeError, ValueError):
            continue
        await _bind_entry(tenant_id, int(r["id"]), int(entry["id"]))
        made += 1
    return made


async def _bind_entry(tenant_id: int, txn_id: int, entry_id: int) -> None:
    conn = await _conn()
    await conn.execute(
        "UPDATE bank_transactions SET gl_entry_id=?,updated_at=? WHERE tenant_id=? AND id=?",
        (int(entry_id), _now(), int(tenant_id), int(txn_id)),
    )
    await conn.commit()


async def bank_match(
    tenant_id: int, txn_id: int, payment_id: int, matched_by: int
) -> dict[str, Any]:
    txn = await bank_get(tenant_id, txn_id)
    if txn is None:
        raise ValueError("银行流水不存在")
    if txn["status"] != "unmatched":
        raise ValueError("只有未匹配流水可以匹配")
    payment = await payment_get(tenant_id, payment_id)
    if payment is None:
        raise ValueError("付款记录不存在")
    if txn["direction"] != "out":
        raise ValueError("只有支出流水可以匹配付款")
    if int(txn["amount_cents"]) != int(payment["amount_cents"]):
        raise ValueError("流水金额与付款金额不一致")
    if int(txn["bank_account_id"]) != int(payment["bank_account_id"]):
        raise ValueError("流水账户与付款账户不一致")
    existing = await fetch_one(
        "SELECT id FROM bank_transactions WHERE tenant_id=? AND payment_id=?",
        (int(tenant_id), int(payment_id)),
    )
    if existing is not None:
        raise ValueError("该付款已经匹配过流水")
    conn = await _conn()
    try:
        cur = await conn.execute(
            "UPDATE bank_transactions SET status='matched',payment_id=?,matched_by=?,"
            "matched_at=?,updated_at=? WHERE tenant_id=? AND id=? AND status='unmatched'",
            (
                int(payment_id),
                int(matched_by),
                _now(),
                _now(),
                int(tenant_id),
                int(txn_id),
            ),
        )
        await conn.commit()
    except sqlite3.IntegrityError as exc:
        # 连接是 autocommit：失败的 UPDATE 本身不会落地，无需再发 ROLLBACK
        # （无活动事务时 ROLLBACK 会抛 OperationalError，把真正的冲突原因盖掉）。
        raise ValueError("该付款已经匹配过流水") from exc
    if not cur.rowcount:
        raise ValueError("流水已被处理")
    matched = await bank_get(tenant_id, txn_id)
    assert matched is not None
    return matched


async def bank_unmatch(tenant_id: int, txn_id: int) -> dict[str, Any]:
    txn = await bank_get(tenant_id, txn_id)
    if txn is None:
        raise ValueError("银行流水不存在")
    if txn["status"] != "matched":
        raise ValueError("只有已匹配流水可以取消匹配")
    conn = await _conn()
    await conn.execute(
        "UPDATE bank_transactions SET status='unmatched',payment_id=NULL,matched_by=NULL,"
        "matched_at='',updated_at=? WHERE tenant_id=? AND id=? AND status='matched'",
        (_now(), int(tenant_id), int(txn_id)),
    )
    await conn.commit()
    updated = await bank_get(tenant_id, txn_id)
    assert updated is not None
    return updated



"""银行流水 · 读取与建流水：列表/详情与账户校验。"""

from __future__ import annotations

from datetime import date
from typing import Any

from ..calculations.gl import to_cents
from ..timeutil import now_str as _now
from ._core import _conn, fetch_all, fetch_one
from .banking_payments import _money
from .gl import gl_get_account


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

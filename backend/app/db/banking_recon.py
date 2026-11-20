"""银行对账：账面余额、未匹配计数、建单与关单。

从 banking.py 拆出。
"""

from __future__ import annotations

from typing import Any

from ..calculations.gl import to_cents
from ..timeutil import now_str as _now
from ._core import _conn, fetch_all, fetch_one
from .banking_bank import _assert_bank_account

_RECON_SELECT = (
    "SELECT r.id,r.tenant_id,r.bank_account_id,r.period_id,"
    "r.statement_balance_cents,r.book_balance_cents,r.difference_cents,"
    "r.status,r.note,r.created_by,r.created_at,r.closed_by,r.closed_at,"
    "a.code AS bank_account_code,a.name AS bank_account_name,"
    "p.year,p.month,p.start_date,p.end_date,p.status AS period_status"
    " FROM bank_reconciliations r"
    " LEFT JOIN gl_accounts a ON a.id=r.bank_account_id AND a.tenant_id=r.tenant_id"
    " LEFT JOIN gl_periods p ON p.id=r.period_id AND p.tenant_id=r.tenant_id"
)


def _recon(row: Any) -> dict[str, Any]:
    data = dict(row)
    for key in ("statement_balance_cents", "book_balance_cents", "difference_cents"):
        data[key.replace("_cents", "")] = round(int(data.get(key) or 0) / 100, 2)
    return data


async def reconciliation_get(tenant_id: int, recon_id: int) -> dict[str, Any] | None:
    row = await fetch_one(
        _RECON_SELECT + " WHERE r.tenant_id=? AND r.id=?",
        (int(tenant_id), int(recon_id)),
    )
    return _recon(row) if row is not None else None


async def reconciliation_list(tenant_id: int) -> list[dict[str, Any]]:
    return [
        _recon(r)
        for r in await fetch_all(
            _RECON_SELECT + " WHERE r.tenant_id=? ORDER BY r.id DESC LIMIT 200",
            (int(tenant_id),),
        )
    ]


async def _book_balance_cents(
    tenant_id: int, bank_account_id: int, end_date: str
) -> int:
    row = await fetch_one(
        "SELECT COALESCE(SUM(l.debit_cents-l.credit_cents),0) AS bal"
        " FROM gl_entry_lines l"
        " JOIN gl_entries e ON e.id=l.entry_id AND e.tenant_id=l.tenant_id"
        " WHERE l.tenant_id=? AND l.account_id=? AND e.status='posted'"
        " AND e.entry_date<=?",
        (int(tenant_id), int(bank_account_id), str(end_date)),
    )
    return int(row["bal"]) if row is not None else 0


async def _unmatched_bank_count(
    tenant_id: int, bank_account_id: int, start_date: str, end_date: str
) -> int:
    row = await fetch_one(
        "SELECT COUNT(*) AS n FROM bank_transactions"
        " WHERE tenant_id=? AND bank_account_id=? AND status='unmatched'"
        " AND txn_date>=? AND txn_date<=?",
        (int(tenant_id), int(bank_account_id), str(start_date), str(end_date)),
    )
    return int(row["n"]) if row is not None else 0


async def reconciliation_create(
    tenant_id: int,
    bank_account_id: int,
    period_id: int,
    statement_balance: Any,
    created_by: int,
    note: str = "",
) -> dict[str, Any]:
    await _assert_bank_account(tenant_id, bank_account_id)
    from .gl import gl_get_period

    period = await gl_get_period(tenant_id, period_id)
    if period is None:
        raise ValueError("会计期间不存在")
    statement_cents = to_cents(statement_balance)
    book_cents = await _book_balance_cents(
        tenant_id, bank_account_id, period["end_date"]
    )
    difference = statement_cents - book_cents
    existing = await fetch_one(
        "SELECT id,status FROM bank_reconciliations"
        " WHERE tenant_id=? AND bank_account_id=? AND period_id=?",
        (int(tenant_id), int(bank_account_id), int(period_id)),
    )
    now = _now()
    conn = await _conn()
    if existing is not None:
        if str(existing["status"]) != "open":
            raise ValueError("该账户本期已签核，不能修改")
        await conn.execute(
            "UPDATE bank_reconciliations SET statement_balance_cents=?,"
            "book_balance_cents=?,difference_cents=?,note=?,created_by=?"
            " WHERE tenant_id=? AND id=?",
            (
                statement_cents,
                book_cents,
                difference,
                str(note or "")[:300],
                int(created_by),
                int(tenant_id),
                int(existing["id"]),
            ),
        )
        await conn.commit()
        created = await reconciliation_get(tenant_id, int(existing["id"]))
        assert created is not None
        return created
    cur = await conn.execute(
        "INSERT INTO bank_reconciliations(tenant_id,bank_account_id,period_id,"
        "statement_balance_cents,book_balance_cents,difference_cents,status,note,"
        "created_by,created_at) VALUES(?,?,?,?,?,?, 'open',?,?,?)",
        (
            int(tenant_id),
            int(bank_account_id),
            int(period_id),
            statement_cents,
            book_cents,
            difference,
            str(note or "")[:300],
            int(created_by),
            now,
        ),
    )
    await conn.commit()
    created = await reconciliation_get(tenant_id, int(cur.lastrowid))
    assert created is not None
    return created


async def reconciliation_close(
    tenant_id: int, recon_id: int, closed_by: int
) -> dict[str, Any]:
    recon = await reconciliation_get(tenant_id, recon_id)
    if recon is None:
        raise ValueError("对账记录不存在")
    if recon["status"] != "open":
        return recon
    period = {
        "start_date": recon["start_date"],
        "end_date": recon["end_date"],
    }
    book_cents = await _book_balance_cents(
        tenant_id, int(recon["bank_account_id"]), period["end_date"]
    )
    statement_cents = int(recon["statement_balance_cents"])
    difference = statement_cents - book_cents
    if difference != 0:
        raise ValueError(
            f"账面与对账单差额 {difference / 100:.2f} 元，先通过总账调整凭证后再签核"
        )
    unmatched = await _unmatched_bank_count(
        tenant_id,
        int(recon["bank_account_id"]),
        period["start_date"],
        period["end_date"],
    )
    if unmatched > 0:
        raise ValueError(f"本期仍有 {unmatched} 条未匹配流水，先完成匹配")
    conn = await _conn()
    await conn.execute(
        "UPDATE bank_reconciliations SET status='closed',book_balance_cents=?,"
        "difference_cents=0,closed_by=?,closed_at=? WHERE tenant_id=? AND id=?",
        (book_cents, int(closed_by), _now(), int(tenant_id), int(recon_id)),
    )
    await conn.commit()
    closed = await reconciliation_get(tenant_id, recon_id)
    assert closed is not None
    return closed


async def bank_summary(
    tenant_id: int, bank_account_id: int | None = None
) -> dict[str, Any]:
    payment_row = await fetch_one(
        "SELECT COUNT(*) AS n,COALESCE(SUM(amount_cents),0) AS total"
        " FROM payments WHERE tenant_id=?",
        (int(tenant_id),),
    )
    bank_params: list[Any] = [int(tenant_id)]
    bank_where = " WHERE tenant_id=?"
    if bank_account_id is not None:
        bank_where += " AND bank_account_id=?"
        bank_params.append(int(bank_account_id))
    bank_row = await fetch_one(
        "SELECT"
        " COALESCE(SUM(CASE WHEN direction='out' THEN amount_cents ELSE 0 END),0) AS out_total,"
        " COALESCE(SUM(CASE WHEN direction='in' THEN amount_cents ELSE 0 END),0) AS in_total,"
        " COALESCE(SUM(CASE WHEN status='unmatched' AND direction='out'"
        " THEN amount_cents ELSE 0 END),0) AS unmatched_out_total,"
        " COALESCE(SUM(CASE WHEN status='unmatched' THEN 1 ELSE 0 END),0) AS unmatched_count,"
        " COALESCE(SUM(CASE WHEN status='matched' THEN 1 ELSE 0 END),0) AS matched_count"
        " FROM bank_transactions" + bank_where,
        tuple(bank_params),
    )
    payments_count = int(payment_row["n"]) if payment_row else 0
    payments_total = int(payment_row["total"]) if payment_row else 0
    return {
        "payments_count": payments_count,
        "payments_total": round(payments_total / 100, 2),
        "payments_total_cents": payments_total,
        "bank_in_total": round(int(bank_row["in_total"]) / 100, 2) if bank_row else 0,
        "bank_out_total": round(int(bank_row["out_total"]) / 100, 2) if bank_row else 0,
        "unmatched_count": int(bank_row["unmatched_count"]) if bank_row else 0,
        "unmatched_out_total": round(
            int(bank_row["unmatched_out_total"]) / 100, 2
        ) if bank_row else 0,
        "matched_count": int(bank_row["matched_count"]) if bank_row else 0,
        "balanced": bool(bank_row and int(bank_row["unmatched_count"]) == 0),
    }

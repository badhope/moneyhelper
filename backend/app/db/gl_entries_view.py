"""凭证读取：行/凭证序列化与单条、列表查询（只读）。"""

from __future__ import annotations

from typing import Any

from ..money import yuan as _money
from ._core import fetch_all, fetch_one


def _line_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "debit": _money(row.get("debit_cents")),
        "credit": _money(row.get("credit_cents")),
    }

def _entry_payload(row: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, Any]:
    debit_cents = sum(int(x.get("debit_cents") or 0) for x in lines)
    credit_cents = sum(int(x.get("credit_cents") or 0) for x in lines)
    return {
        **row,
        "debit": _money(debit_cents),
        "credit": _money(credit_cents),
        "debit_cents": debit_cents,
        "credit_cents": credit_cents,
        "lines": [_line_payload(x) for x in lines],
    }

async def gl_get_entry(tenant_id: int, entry_id: int) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT id,tenant_id,entry_no,entry_date,period_id,description,status,source,"
        "reversal_of,created_by,created_at,posted_at"
        " FROM gl_entries WHERE tenant_id=? AND id=?",
        (int(tenant_id), int(entry_id)),
    )
    if row is None:
        return None
    lines = await fetch_all(
        "SELECT id,tenant_id,entry_id,line_no,account_id,debit_cents,credit_cents,memo"
        " FROM gl_entry_lines WHERE tenant_id=? AND entry_id=? ORDER BY line_no",
        (int(tenant_id), int(entry_id)),
    )
    return _entry_payload(dict(row), lines)


async def gl_list_entries(
    tenant_id: int, period_id: int | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    clamped = max(1, min(int(limit or 200), 500))
    sql = (
        "SELECT e.id,e.tenant_id,e.entry_no,e.entry_date,e.period_id,e.description,"
        "e.status,e.source,e.reversal_of,e.created_by,e.created_at,e.posted_at,"
        "COALESCE((SELECT SUM(l.debit_cents) FROM gl_entry_lines l"
        " WHERE l.tenant_id=e.tenant_id AND l.entry_id=e.id),0) AS debit_cents,"
        "COALESCE((SELECT SUM(l.credit_cents) FROM gl_entry_lines l"
        " WHERE l.tenant_id=e.tenant_id AND l.entry_id=e.id),0) AS credit_cents"
        " FROM gl_entries e WHERE e.tenant_id=?"
    )
    params: list[Any] = [int(tenant_id)]
    if period_id is not None:
        sql += " AND e.period_id=?"
        params.append(int(period_id))
    sql += " ORDER BY e.id DESC LIMIT ?"
    params.append(clamped)
    rows = await fetch_all(sql, tuple(params))
    return [
        {
            **r,
            "debit": _money(r.get("debit_cents")),
            "credit": _money(r.get("credit_cents")),
        }
        for r in rows
    ]

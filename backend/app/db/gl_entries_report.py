"""试算平衡：按科目汇总借贷发生额与期末余额。"""

from __future__ import annotations

from typing import Any

from ..calculations.gl import GL_NORMAL_BALANCE
from ..money import yuan as _money
from ._core import fetch_all
from .gl_accounts import gl_get_period


async def gl_trial_balance(tenant_id: int, period_id: int) -> dict[str, Any]:
    period = await gl_get_period(tenant_id, period_id)
    if period is None:
        raise ValueError("会计期间不存在")
    rows = await fetch_all(
        "SELECT a.id,a.code,a.name,a.type,"
        "COALESCE(SUM(l.debit_cents),0) AS debit_cents,"
        "COALESCE(SUM(l.credit_cents),0) AS credit_cents"
        " FROM gl_entry_lines l"
        " JOIN gl_entries e ON e.id=l.entry_id AND e.tenant_id=l.tenant_id"
        " JOIN gl_accounts a ON a.id=l.account_id AND a.tenant_id=l.tenant_id"
        " WHERE l.tenant_id=? AND e.period_id=? AND e.status='posted'"
        " GROUP BY a.id,a.code,a.name,a.type ORDER BY a.code",
        (int(tenant_id), int(period_id)),
    )
    items = []
    total_debit = 0
    total_credit = 0
    for r in rows:
        debit = int(r.get("debit_cents") or 0)
        credit = int(r.get("credit_cents") or 0)
        total_debit += debit
        total_credit += credit
        items.append(
            {
                "account_id": r["id"],
                "code": r["code"],
                "name": r["name"],
                "type": r["type"],
                "normal_balance": GL_NORMAL_BALANCE.get(str(r["type"]), ""),
                "debit": _money(debit),
                "credit": _money(credit),
                "balance": _money(debit - credit),
                "debit_cents": debit,
                "credit_cents": credit,
            }
        )
    return {
        "period": period,
        "items": items,
        "total_debit": _money(total_debit),
        "total_credit": _money(total_credit),
        "total_debit_cents": total_debit,
        "total_credit_cents": total_credit,
        "balanced": total_debit == total_credit,
    }

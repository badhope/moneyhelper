"""财税时序聚合（4.17.1）：把总账已过账凭证压成按月时间轴。

只读、确定性、按租户隔离。数据源只有 `gl_periods / gl_entries / gl_entry_lines /
gl_accounts` 的已过账记录；不推算税局申报状态，也不把发票或银行流水混进来。
缺失月份显式返回 `status=missing`，不拿 0 冒充“已结账”。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ._core import fetch_all

# 现金流账户：默认账套里的银行存款 + 库存现金。
_CASH_CODES = ("1001", "1002")
# 应交税费：贷方为计提，借方为缴纳/抵扣。
_TAX_CODE = "2203"


def _money(cents: int | float | None) -> float:
    return round(float(cents or 0) / 100.0, 2)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


async def finance_timeline(tenant_id: int, months: int = 12) -> dict[str, Any]:
    """返回最近 N 个自然月的财税时间轴。

    - 每个月的收入/费用/利润来自已过账分录，收入按贷方净额、费用按借方净额；
    - 现金流入/流出只统计 1001/1002；
    - 税费计提/缴纳只统计 2203；
    - 没有会计期间的月份标 `missing`，有期间但无凭证的月份仍返回 0 与 `posted_entries=0`。
    """
    n = max(1, min(int(months or 12), 36))
    today = date.today()
    first_year, first_month = _shift_month(today.year, today.month, -(n - 1))

    rows = await fetch_all(
        "SELECT p.year,p.month,p.status,p.closed_at,"
        " COALESCE(SUM(CASE WHEN a.type='income'"
        "   THEN l.credit_cents-l.debit_cents ELSE 0 END),0) AS income_cents,"
        " COALESCE(SUM(CASE WHEN a.type='expense'"
        "   THEN l.debit_cents-l.credit_cents ELSE 0 END),0) AS expense_cents,"
        " COALESCE(SUM(CASE WHEN a.code IN ('1001','1002')"
        "   THEN l.debit_cents ELSE 0 END),0) AS cash_in_cents,"
        " COALESCE(SUM(CASE WHEN a.code IN ('1001','1002')"
        "   THEN l.credit_cents ELSE 0 END),0) AS cash_out_cents,"
        " COALESCE(SUM(CASE WHEN a.code='2203'"
        "   THEN l.credit_cents ELSE 0 END),0) AS tax_accrued_cents,"
        " COALESCE(SUM(CASE WHEN a.code='2203'"
        "   THEN l.debit_cents ELSE 0 END),0) AS tax_paid_cents,"
        " COUNT(DISTINCT CASE WHEN e.status='posted' THEN e.id END) AS posted_entries,"
        "(SELECT COUNT(*) FROM gl_entries d WHERE d.tenant_id=p.tenant_id"
        " AND d.period_id=p.id AND d.status='draft') AS draft_entries"
        " FROM gl_periods p"
        " LEFT JOIN gl_entries e ON e.tenant_id=p.tenant_id"
        "   AND e.period_id=p.id AND e.status='posted'"
        " LEFT JOIN gl_entry_lines l ON l.tenant_id=e.tenant_id AND l.entry_id=e.id"
        " LEFT JOIN gl_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id"
        " WHERE p.tenant_id=?"
        " GROUP BY p.id ORDER BY p.year DESC,p.month DESC",
        (int(tenant_id),),
    )
    by_key = {(int(r["year"]), int(r["month"])): r for r in rows}

    out: list[dict[str, Any]] = []
    for i in range(n):
        year, month = _shift_month(first_year, first_month, i)
        row = by_key.get((year, month))
        key = f"{year:04d}-{month:02d}"
        if row is None:
            out.append(
                {
                    "month": key,
                    "status": "missing",
                    "closed_at": "",
                    "income": 0.0,
                    "expense": 0.0,
                    "profit": 0.0,
                    "cash_in": 0.0,
                    "cash_out": 0.0,
                    "cash_net": 0.0,
                    "tax_accrued": 0.0,
                    "tax_paid": 0.0,
                    "tax_net": 0.0,
                    "posted_entries": 0,
                    "draft_entries": 0,
                    "source": "none",
                }
            )
            continue

        income = _money(row["income_cents"])
        expense = _money(row["expense_cents"])
        cash_in = _money(row["cash_in_cents"])
        cash_out = _money(row["cash_out_cents"])
        tax_accrued = _money(row["tax_accrued_cents"])
        tax_paid = _money(row["tax_paid_cents"])
        out.append(
            {
                "month": key,
                "status": str(row["status"]),
                "closed_at": str(row.get("closed_at") or ""),
                "income": income,
                "expense": expense,
                "profit": round(income - expense, 2),
                "cash_in": cash_in,
                "cash_out": cash_out,
                "cash_net": round(cash_in - cash_out, 2),
                "tax_accrued": tax_accrued,
                "tax_paid": tax_paid,
                "tax_net": round(tax_accrued - tax_paid, 2),
                "posted_entries": int(row.get("posted_entries") or 0),
                "draft_entries": int(row.get("draft_entries") or 0),
                "source": "gl_posted",
            }
        )

    with_data = [m for m in out if m["source"] == "gl_posted"]
    return {
        "months": out,
        "range": {"from": out[0]["month"], "to": out[-1]["month"]},
        "period_count": len(with_data),
        "missing_count": n - len(with_data),
        "source": "gl_entries(status=posted)",
        "boundary": (
            "只统计已过账总账凭证；未过账草稿、发票、银行流水与税局申报状态不计入，"
            "不代表完税或已申报。"
        ),
    }




async def finance_timeline_month(tenant_id: int, month: str) -> dict[str, Any]:
    """单月下钻：返回该月已过账凭证与逐行科目发生额。

    `month` 必须是 `YYYY-MM`；没有会计期间的月份返回 `status=missing` 与空列表，
    不拿上月或估算值补。只读，不改账。
    """
    import re

    text = str(month or "").strip()
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", text):
        raise ValueError("月份必须是 YYYY-MM")
    year, mon = int(text[:4]), int(text[5:])
    if not 2000 <= year <= 2100:
        raise ValueError("年份必须在 2000-2100")

    period = await fetch_all(
        "SELECT id,status,closed_at FROM gl_periods WHERE tenant_id=? AND year=? AND month=?",
        (int(tenant_id), year, mon),
    )
    if not period:
        return {
            "month": text, "status": "missing", "closed_at": "", "entries": [],
            "posted_entries": 0, "draft_entries": 0, "totals": {"debit": 0.0, "credit": 0.0},
            "boundary": "只读已过账凭证；没有会计期间时返回 empty，不用 0 或上月数据代替。",
        }
    p = period[0]

    entries = await fetch_all(
        "SELECT id,entry_no,entry_date,description,source,posted_at FROM gl_entries"
        " WHERE tenant_id=? AND period_id=? AND status='posted'"
        " ORDER BY entry_date,id",
        (int(tenant_id), int(p["id"])),
    )
    lines = await fetch_all(
        "SELECT l.entry_id,l.line_no,l.debit_cents,l.credit_cents,l.memo,"
        "a.code,a.name,a.type FROM gl_entry_lines l"
        " JOIN gl_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id"
        " JOIN gl_entries e ON e.tenant_id=l.tenant_id AND e.id=l.entry_id"
        " WHERE e.tenant_id=? AND e.period_id=? AND e.status='posted'"
        " ORDER BY l.entry_id,l.line_no",
        (int(tenant_id), int(p["id"])),
    )
    by_entry: dict[int, list[dict[str, Any]]] = {}
    total_debit = total_credit = 0
    for line in lines:
        debit = int(line["debit_cents"] or 0)
        credit = int(line["credit_cents"] or 0)
        total_debit += debit
        total_credit += credit
        by_entry.setdefault(int(line["entry_id"]), []).append({
            "line_no": int(line["line_no"]),
            "account_code": str(line["code"]),
            "account_name": str(line["name"]),
            "account_type": str(line["type"]),
            "debit": _money(debit),
            "credit": _money(credit),
            "memo": str(line.get("memo") or ""),
        })
    draft = await fetch_all(
        "SELECT COUNT(*) AS n FROM gl_entries WHERE tenant_id=? AND period_id=? AND status='draft'",
        (int(tenant_id), int(p["id"])),
    )
    return {
        "month": text,
        "status": str(p["status"]),
        "closed_at": str(p.get("closed_at") or ""),
        "entries": [
            {
                "id": int(e["id"]),
                "entry_no": str(e["entry_no"]),
                "entry_date": str(e["entry_date"]),
                "description": str(e["description"] or ""),
                "source": str(e["source"] or ""),
                "posted_at": str(e.get("posted_at") or ""),
                "lines": by_entry.get(int(e["id"]), []),
            }
            for e in entries
        ],
        "posted_entries": len(entries),
        "draft_entries": int(draft[0]["n"] or 0) if draft else 0,
        "totals": {"debit": _money(total_debit), "credit": _money(total_credit)},
        "boundary": "只读已过账凭证；没有会计期间时返回 empty，不用 0 或上月数据代替。",
    }


__all__ = ["finance_timeline", "finance_timeline_month"]

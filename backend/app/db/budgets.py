"""预算域：月度预算设置与用量统计。"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from ._core import (
    NON_CONSUMPTION_CATEGORIES,
    _conn,
    fetch_all,
)
from .tenant import current_user_id

# --------------------------------------------------------------------------
# 预算（budgets：month + category → amount；__total 为总预算）
# --------------------------------------------------------------------------


async def list_budgets(month: str) -> list[dict[str, Any]]:
    """当前租户在指定月份的预算。"""
    from .tenant import current_user_id

    return await fetch_all(
        "SELECT month, category, amount FROM budgets WHERE user_id=? AND month=? ORDER BY category",
        (current_user_id(), month),
    )


async def budget_usage(month: str) -> dict[str, Any]:
    """当月预算使用情况：与 /api/budgets 返回的 usage 字段同源。

    返回：
    - total_budget / total_spent / total_pct / over / left / left_daily / days_left
    - categories: [{category, budget, spent, pct, over}]
    """

    rows = await list_budgets(month)
    spent_by_cat = await month_expense_by_category(month)
    for cat in NON_CONSUMPTION_CATEGORIES:
        spent_by_cat.pop(cat, None)
    total_spent = round(sum(spent_by_cat.values()), 2)
    total_budget = next((r["amount"] for r in rows if r["category"] == "__total"), 0.0)

    cat_usage = []
    for r in rows:
        key = r["category"]
        if key == "__total":
            continue
        budget = float(r["amount"] or 0)
        spent = round(spent_by_cat.get(key, 0.0), 2)
        cat_usage.append(
            {
                "category": "总预算" if key == "__total" else key,
                "budget": budget,
                "spent": spent,
                "pct": round(spent / budget * 100, 1) if budget else 0,
                "over": spent > budget,
            }
        )

    total_pct = round(total_spent / total_budget * 100, 1) if total_budget else 0
    now = datetime.now().astimezone()
    next_month = datetime(
        now.year + (now.month == 12), (now.month % 12) + 1, 1, tzinfo=now.tzinfo
    )
    days_left = max(
        1, (next_month - now.replace(hour=0, minute=0, second=0, microsecond=0)).days
    )
    left_daily = (
        round((total_budget - total_spent) / days_left, 2) if total_budget else 0.0
    )

    return {
        "total_budget": total_budget,
        "total_spent": total_spent,
        "total_pct": total_pct,
        "over": total_budget > 0 and total_spent > total_budget,
        "left": round(total_budget - total_spent, 2),
        "left_daily": left_daily,
        "days_left": days_left,
        "categories": cat_usage,
    }


async def total_cash() -> float:
    """活期现金总额：position 中 kind='现金' 的行 shares*last 求和（无现金行返回 0）。

    注意：这只是活期头寸，不含投资/股票/基金市值。
    """
    rows = await fetch_all(
        "SELECT SUM(shares * last) AS cash FROM positions"
        " WHERE user_id=? AND kind = '现金'",
        (current_user_id(),),
    )
    return float((rows[0].get("cash") or 0) if rows else 0.0)


async def save_budgets(month: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    """整月替换式保存：先删该月旧预算，再写入新列表。

    同月重复分类取最后一项（主键 (month,category) 不允许重复）；
    任一语句失败整体回滚，避免 DELETE 已执行而 INSERT 未完成的半截状态。
    """
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError(f"budget month 格式非法: {month!r}，应为 YYYY-MM")
    from .tenant import current_user_id

    conn = await _conn()
    seen: dict[str, float] = {}
    for it in items:
        cat = str(it.get("category", "")).strip() or "__total"
        amt = float(it.get("amount", 0) or 0)
        if amt <= 0:
            continue
        seen[cat[:40]] = amt
    try:
        await conn.execute(
            "DELETE FROM budgets WHERE user_id=? AND month=?", (current_user_id(), month)
        )
        for cat, amt in seen.items():
            await conn.execute(
                "INSERT INTO budgets(user_id,month,category,amount) VALUES(?,?,?,?)",
                (current_user_id(), month, cat, amt),
            )
        await conn.commit()
    except Exception:  # aqg: top-level boundary — 事务失败统一回滚后原样抛出，不吞异常
        await conn.rollback()
        raise
    return {"ok": True, "month": month, "count": len(seen)}


async def month_expense_by_category(month: str) -> dict[str, float]:
    """当月支出按分类汇总（amount<0 视为支出，取绝对值）。"""
    rows = await fetch_all(
        "SELECT category, SUM(-amount) AS spent FROM transactions"
        " WHERE user_id=? AND date LIKE ? AND amount < 0 GROUP BY category",
        (current_user_id(), f"{month}%"),
    )
    return {r["category"]: float(r["spent"] or 0) for r in rows}


async def month_cashflow(month: str, essential_categories: list[str] | None = None) -> dict[str, Any]:
    """当月现金流聚合（SQL GROUP BY，不把明细拉到 Python 侧再算）。

    这是 M5.3「后端预聚合」的落点：账本超过十万行时，原先
    `list_transactions()` + Python 过滤会把整库搬进内存，单次 /api/dashboard
    要几百毫秒并且随行数线性增长。现在只返回几个聚合数字。

    返回 income / expense / net / savings_rate / by_category（前 6 大）/ essential。
    """
    uid = current_user_id()
    prefix = f"{month}%"
    totals = await fetch_all(
        "SELECT"
        " SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS income,"
        " SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END) AS expense"
        " FROM transactions WHERE user_id=? AND date LIKE ?",
        (uid, prefix),
    )
    row = totals[0] if totals else {}
    income = float(row.get("income") or 0)
    expense = float(row.get("expense") or 0)

    cat_rows = await fetch_all(
        "SELECT category, SUM(-amount) AS spent FROM transactions"
        " WHERE user_id=? AND date LIKE ? AND amount < 0"
        " GROUP BY category ORDER BY spent DESC LIMIT 6",
        (uid, prefix),
    )
    by_category = [
        {"category": str(r["category"]), "amount": round(float(r["spent"] or 0), 2)}
        for r in cat_rows
    ]

    essential = 0.0
    cats = [c.strip() for c in (essential_categories or []) if c.strip()]
    if cats:
        marks = ",".join("?" for _ in cats)
        ess_rows = await fetch_all(
            f"SELECT SUM(-amount) AS spent FROM transactions"
            f" WHERE user_id=? AND date LIKE ? AND amount < 0 AND category IN ({marks})",
            (uid, prefix, *cats),
        )
        essential = float((ess_rows[0] if ess_rows else {}).get("spent") or 0)

    return {
        "month": month,
        "income": round(income, 2),
        "expense": round(expense, 2),
        "net": round(income - expense, 2),
        "savings_rate": round((income - expense) / income * 100, 1) if income else 0.0,
        "by_category": by_category,
        "essential": round(essential, 2),
    }


async def count_transactions() -> int:
    """当前租户流水总条数（分页展示用，避免为了显示总数而拉全表）。"""
    rows = await fetch_all("SELECT COUNT(*) AS n FROM transactions WHERE user_id=?", (current_user_id(),))
    return int((rows[0] if rows else {}).get("n") or 0)

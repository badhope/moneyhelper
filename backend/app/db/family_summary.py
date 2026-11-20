"""家庭汇总：成员净资产、未结借款与整体视图。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ._core import (
    fetch_all,
    fetch_one,
)
from .family_loans import list_loans
from .family_members import list_members
from .tenant import current_user_id

# --------------------------------------------------------------------------
# 成员汇总 / 家庭仪表板
# --------------------------------------------------------------------------


async def member_summary(member_id: int) -> dict[str, Any]:
    """查询单个成员的收支汇总"""
    income = await fetch_one(
        "SELECT COALESCE(SUM(amount), 0) as val FROM transactions "
        "WHERE user_id=? AND owner_id=? AND amount > 0 AND is_shared=1",
        (current_user_id(), member_id),
    )
    expense = await fetch_one(
        "SELECT COALESCE(SUM(ABS(amount)), 0) as val FROM transactions "
        "WHERE user_id=? AND owner_id=? AND amount < 0 AND is_shared=1",
        (current_user_id(), member_id),
    )
    count_row = await fetch_one(
        "SELECT COUNT(*) as val FROM transactions WHERE user_id=? AND owner_id=?",
        (current_user_id(), member_id),
    )
    return {
        "member_id": member_id,
        "income": float(income["val"]) if income else 0.0,
        "expense": float(expense["val"]) if expense else 0.0,
        "transaction_count": int(count_row["val"]) if count_row else 0,
    }


async def all_members_summary() -> list[dict[str, Any]]:
    """查询所有成员的收支汇总"""
    members = await list_members()
    result = []
    for m in members:
        s = await member_summary(m["id"])
        s["display_name"] = m["display_name"]
        s["role"] = m["role"]
        s["avatar_color"] = m["avatar_color"]
        result.append(s)
    return result


async def member_outstanding_loans() -> list[dict[str, Any]]:
    """未结清借贷（附成员显示名）"""
    loans = await list_loans(settled=False)
    members = {m["id"]: m["display_name"] for m in await list_members()}
    result = []
    for ln in loans:
        result.append(
            {
                "id": ln["id"],
                "from_member_id": ln["from_member_id"],
                "from_name": members.get(ln["from_member_id"], ""),
                "to_member_id": ln["to_member_id"],
                "to_name": members.get(ln["to_member_id"], ""),
                "amount": ln["amount"],
                "currency": ln["currency"],
                "note": ln["note"],
                "created_at": ln["created_at"],
            }
        )
    return result


async def family_summary() -> dict[str, Any]:
    """家庭整体汇总仪表板数据"""
    # 全局统计：所有 shared=1 的流水 + owner_id=NULL 的流水（向后兼容单用户）
    income_row = await fetch_one(
        "SELECT COALESCE(SUM(amount), 0) as val FROM transactions "
        "WHERE user_id=? AND amount > 0 AND (is_shared=1 OR owner_id IS NULL)",
        (current_user_id(),),
    )
    expense_row = await fetch_one(
        "SELECT COALESCE(SUM(ABS(amount)), 0) as val FROM transactions "
        "WHERE user_id=? AND amount < 0 AND (is_shared=1 OR owner_id IS NULL)",
        (current_user_id(),),
    )
    total_income = float(income_row["val"]) if income_row else 0.0
    total_expense = float(expense_row["val"]) if expense_row else 0.0

    # 各成员占比
    members = await list_members()
    member_stats = []
    for m in members:
        s = await member_summary(m["id"])
        member_stats.append(
            {
                "id": m["id"],
                "display_name": m["display_name"],
                "role": m["role"],
                "avatar_color": m["avatar_color"],
                "income": s["income"],
                "expense": s["expense"],
                "balance": round(s["income"] - s["expense"], 2),
                "pct": round(s["expense"] / total_expense * 100, 1)
                if total_expense > 0
                else 0.0,
                "transaction_count": s["transaction_count"],
            }
        )

    # 未结清借贷
    loans = await member_outstanding_loans()

    # Top categories（本月）
    now = datetime.now()
    month_prefix = now.strftime("%Y-%m")
    cat_rows = await fetch_all(
        "SELECT category, COALESCE(SUM(ABS(amount)), 0) as total "
        "FROM transactions WHERE user_id=? AND amount < 0 AND date >= ? AND date < ? "
        "GROUP BY category ORDER BY total DESC LIMIT 5",
        (current_user_id(), f"{month_prefix}-01", f"{month_prefix}-32"),
    )
    top_categories = [
        {"category": r["category"], "amount": round(float(r["total"]), 2)}
        for r in cat_rows
    ]

    return {
        "household_income": round(total_income, 2),
        "household_expense": round(total_expense, 2),
        "household_net": round(total_income - total_expense, 2),
        "members": member_stats,
        "outstanding_loans": loans,
        "top_categories": top_categories,
    }

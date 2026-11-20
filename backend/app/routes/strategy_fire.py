"""FIRE 测算：按目标支出与提取率估算达成年限。"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query

from .. import db
from ..auth import get_current_user
from ..calculations import (
    compute_fire,
)
from .strategy_common import _months_ago

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/api/strategy/fire")
async def strategy_fire(
    withdrawal_rate: float = Query(default=4.0, ge=0.5, le=10.0),
    expected_return: float = Query(default=5.0, ge=-10.0, le=30.0),
) -> dict[str, Any]:
    """FIRE 计算：目标本金、储蓄率、预计年限。数据来自账本与净值。"""
    txns = await db.list_transactions()
    month_prefix = date.today().strftime("%Y-%m")
    monthly = [t for t in txns if str(t.get("date", "")).startswith(month_prefix)]
    income = sum(float(t.get("amount", 0)) for t in monthly if float(t.get("amount", 0)) > 0)
    expense = -sum(float(t.get("amount", 0)) for t in monthly if float(t.get("amount", 0)) < 0)
    # 本月样本不足时回退到近 3 个月月均，避免月初 FIRE 数字剧烈跳动
    if income <= 0 or expense <= 0:
        recent = [t for t in txns if str(t.get("date", ""))[:7] >= _months_ago(3)]
        months = {str(t.get("date", ""))[:7] for t in recent if t.get("date")}
        n = max(1, len(months))
        income = sum(float(t.get("amount", 0)) for t in recent if float(t.get("amount", 0)) > 0) / n
        expense = -sum(float(t.get("amount", 0)) for t in recent if float(t.get("amount", 0)) < 0) / n

    positions = await db.list_positions()
    debts = await db.list_debts()
    net = sum(float(p.get("shares", 0) or 0) * float(p.get("last", 0) or 0) for p in positions) - sum(
        float(d.get("balance", 0) or 0) for d in debts
    )
    sr = None if income <= 0 else (income - expense) / income * 100
    result = compute_fire(expense, income, sr, net, expected_return, withdrawal_rate)
    return {"available": income > 0 or expense > 0, "monthly_income": round(income, 2), "monthly_expense": round(expense, 2), **result}

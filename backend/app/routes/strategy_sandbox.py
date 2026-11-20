"""反事实沙盒（M5.5）：以本月实际收支为基线做 if……会怎样推演。"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query

from .. import db
from ..auth import get_current_user
from .strategy_common import _months_ago

router = APIRouter(dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------------
# 反事实沙盒（M5.5）：if……会怎样
# ---------------------------------------------------------------------------


async def _sandbox_base(category: str = "") -> Any:
    """组装沙盒输入：用本月实际收支，缺数据时回退近 3 个月月均。"""
    from ..calculations.sandbox import ScenarioInput

    txns = await db.list_transactions()
    month_prefix = date.today().strftime("%Y-%m")
    monthly = [t for t in txns if str(t.get("date", "")).startswith(month_prefix)]
    income = sum(float(t.get("amount", 0)) for t in monthly if float(t.get("amount", 0)) > 0)
    expense = -sum(float(t.get("amount", 0)) for t in monthly if float(t.get("amount", 0)) < 0)
    if income <= 0 or expense <= 0:
        recent = [t for t in txns if str(t.get("date", ""))[:7] >= _months_ago(3)]
        months = {str(t.get("date", ""))[:7] for t in recent if t.get("date")}
        n = max(1, len(months))
        income = sum(float(t.get("amount", 0)) for t in recent if float(t.get("amount", 0)) > 0) / n
        expense = -sum(float(t.get("amount", 0)) for t in recent if float(t.get("amount", 0)) < 0) / n

    positions = await db.list_positions()
    cash = sum(
        float(p.get("shares", 0)) * float(p.get("last", 0))
        for p in positions
        if p.get("kind") == "现金"
    )
    settings = await db.get_settings()
    essential_cats = {c.strip() for c in (settings.get("essential_categories") or "").split(",") if c.strip()}
    essential = -sum(
        float(t.get("amount", 0))
        for t in monthly
        if float(t.get("amount", 0)) < 0 and str(t.get("category") or "") in essential_cats
    )
    if essential <= 0:
        essential = expense * 0.5
    target_expense = 0.0
    if category:
        target_expense = -sum(
            float(t.get("amount", 0))
            for t in monthly
            if float(t.get("amount", 0)) < 0 and str(t.get("category") or "") == category
        )
    dca_total = 0.0
    for plan in await db.list_dca_plans():
        if plan.get("active", 1):
            dca_total += float(plan.get("amount") or 0)
    return ScenarioInput(
        monthly_income=round(income, 2),
        monthly_expense=round(expense, 2),
        cash=round(cash, 2),
        essential_monthly=round(essential, 2),
        target_category_expense=round(target_expense, 2),
        dca_monthly=round(dca_total, 2),
    )


@router.get("/api/strategy/sandbox/base")
async def sandbox_base(category: str = "") -> dict[str, Any]:
    """沙盒基线：当前月收入/支出/现金/必要支出/该类目支出/定投合计。"""
    base = await _sandbox_base(category)
    return {
        "monthly_income": base.monthly_income,
        "monthly_expense": base.monthly_expense,
        "cash": base.cash,
        "essential_monthly": base.essential_monthly,
        "target_category_expense": base.target_category_expense,
        "dca_monthly": base.dca_monthly,
        "category": category,
        "available": base.monthly_income > 0,
    }


@router.get("/api/strategy/sandbox")
async def sandbox_simulate(
    kind: str = Query(default="save_more"),
    amount: float = Query(default=0.0),
    percent: float = Query(default=0.0),
    category: str = Query(default=""),
    expected_return: float = Query(default=5.0, ge=-10.0, le=30.0),
    withdrawal_rate: float = Query(default=4.0, ge=0.5, le=10.0),
) -> Any:
    """反事实测算：less_spend / save_more / dca_change / one_off。"""
    from ..calculations.sandbox import simulate

    base = await _sandbox_base(category)
    try:
        return simulate(
            base,
            kind=kind,
            amount=amount,
            percent=percent,
            return_rate=expected_return / 100,
            withdrawal_rate=withdrawal_rate / 100,
        )
    except ValueError as exc:
        from fastapi.responses import JSONResponse

        return JSONResponse({"error": str(exc)}, status_code=400)

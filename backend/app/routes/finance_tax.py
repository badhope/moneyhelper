"""公司财税路由（v4.5）：税负测算 / 个税 / 工资核算 / 月结清单 / 现金流预测 /
订阅识别 / 异常扣款。

所有计算都在 calculations 包（纯函数），本层只做参数清洗与落库组装。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from .. import db
from ..auth import get_current_user
from ..calculations import (
    cashflow_forecast,
    corporate_income_tax,
    detect_anomalies,
    detect_subscriptions,
    individual_income_tax,
    month_end_checklist,
    payroll,
    tax_summary,
    vat,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


def _bad(msg: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=code)


def _f(payload: dict[str, Any], key: str, default: float = 0.0) -> float:
    """读取数值参数；只有缺省/None/空串才回落默认值。

    不能用 `value or default`：显式传入 0 是合法值（例如零税率、零成本），
    被 `or` 替换成默认税率会静默改变计算结果。
    """
    raw = (payload or {}).get(key, default)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{key} 必须是数字") from None


# ---------------------------------------------------------------------------
# 税负
# ---------------------------------------------------------------------------


@router.post("/api/finance/tax/vat")
async def calc_vat(payload: dict[str, Any]) -> Any:
    try:
        return vat(
            sales=_f(payload, "sales"),
            purchases=_f(payload, "purchases"),
            rate=_f(payload, "rate", 0.13),
            simple=bool((payload or {}).get("simple")),
            simple_rate=_f(payload, "simple_rate", 0.03),
            location=str((payload or {}).get("location") or "city"),
            exempt_threshold=_f(payload, "exempt_threshold"),
        )
    except ValueError as exc:
        return _bad(str(exc))


@router.post("/api/finance/tax/cit")
async def calc_cit(payload: dict[str, Any]) -> Any:
    try:
        return corporate_income_tax(
            revenue=_f(payload, "revenue"),
            cost=_f(payload, "cost"),
            expenses=_f(payload, "expenses"),
            other_deductions=_f(payload, "other_deductions"),
            loss_carryforward=_f(payload, "loss_carryforward"),
            category=str((payload or {}).get("category") or "standard"),
            tax_adjustments=_f(payload, "tax_adjustments"),
        )
    except ValueError as exc:
        return _bad(str(exc))


@router.post("/api/finance/tax/iit")
async def calc_iit(payload: dict[str, Any]) -> Any:
    try:
        return individual_income_tax(
            monthly_salary=_f(payload, "monthly_salary"),
            months=int((payload or {}).get("months") or 1),
            social_insurance=_f(payload, "social_insurance"),
            housing_fund=_f(payload, "housing_fund"),
            special_additional=_f(payload, "special_additional"),
            other_deductions=_f(payload, "other_deductions"),
            already_withheld=_f(payload, "already_withheld"),
        )
    except ValueError as exc:
        return _bad(str(exc))


@router.post("/api/finance/tax/payroll")
async def calc_payroll(payload: dict[str, Any]) -> Any:
    try:
        result = payroll(
            gross_salary=_f(payload, "gross_salary"),
            social_base=_f(payload, "social_base") if (payload or {}).get("social_base") else None,
            housing_base=_f(payload, "housing_base") if (payload or {}).get("housing_base") else None,
            base_min=_f(payload, "base_min", 3500),
            base_max=_f(payload, "base_max", 35000),
            # 公积金上下限独立：多数城市公积金上限高于社保，共用 base_max
            # 会把用户显式传入的高基数悄悄压回社保上限。不传则沿用社保口径。
            housing_base_min=(
                _f(payload, "housing_base_min") if (payload or {}).get("housing_base_min") else None
            ),
            housing_base_max=(
                _f(payload, "housing_base_max") if (payload or {}).get("housing_base_max") else None
            ),
            special_additional=_f(payload, "special_additional"),
            other_deductions=_f(payload, "other_deductions"),
            already_withheld=_f(payload, "already_withheld"),
            months=int((payload or {}).get("months") or 1),
            employee_rates=(payload or {}).get("employee_rates") or None,
            employer_rates=(payload or {}).get("employer_rates") or None,
        )
    except ValueError as exc:
        return _bad(str(exc))
    return {
        "gross": result.gross,
        "employee": result.employee,
        "employer": result.employer,
        "employee_total": result.employee_total,
        "employer_total": result.employer_total,
        "taxable_income": result.taxable_income,
        "income_tax": result.income_tax,
        # months>1 时 income_tax 是累计口径：单月与期间两个实发都给出，
        # 前端不必自己猜该减哪一份。
        "current_month_tax": result.current_month_tax,
        "net_pay": result.net_pay,
        "period_net_pay": result.period_net_pay,
        "employer_cost": result.employer_cost,
        "notes": result.notes,
        "disclaimer": "社保/公积金比例按通用城镇职工默认值，各地差异大，请按本地口径调整参数。",
    }


@router.post("/api/finance/tax/summary")
async def calc_tax_summary(payload: dict[str, Any]) -> Any:
    try:
        return tax_summary(
            revenue=_f(payload, "revenue"),
            cost=_f(payload, "cost"),
            expenses=_f(payload, "expenses"),
            vat_rate=_f(payload, "vat_rate", 0.13),
            vat_simple=bool((payload or {}).get("vat_simple")),
            location=str((payload or {}).get("location") or "city"),
            cit_category=str((payload or {}).get("cit_category") or "standard"),
            payroll_gross=_f(payload, "payroll_gross"),
            payroll_months=int((payload or {}).get("payroll_months") or 12),
        )
    except ValueError as exc:
        return _bad(str(exc))


@router.get("/api/finance/month-end/{month}")
async def get_month_end(month: str, completed: str = "") -> Any:
    """月度结账清单；completed 传逗号分隔的已完成项 id。"""
    try:
        return month_end_checklist(month, completed=[c for c in completed.split(",") if c])
    except ValueError as exc:
        return _bad(str(exc))


# ---------------------------------------------------------------------------
# 现金流 / 订阅 / 异常（用真实账本数据）
# ---------------------------------------------------------------------------


async def _all_transactions() -> list[dict[str, Any]]:
    return await db.list_transactions()


@router.get("/api/finance/cashflow/forecast")
async def forecast(months_ahead: int = 3, opening_balance: float | None = None) -> dict[str, Any]:
    """现金流三档预测。opening_balance 缺省时用账本现金类资产估算。"""
    positions = await db.list_positions()
    cash = sum(
        float(p.get("shares", 0)) * float(p.get("last", 0))
        for p in positions
        if p.get("kind") == "现金"
    )
    return cashflow_forecast(
        await _all_transactions(),
        months_ahead=max(1, min(months_ahead, 12)),
        opening_balance=cash if opening_balance is None else float(opening_balance),
    )


@router.get("/api/finance/subscriptions/detect")
async def subscriptions_detect() -> dict[str, Any]:
    """从流水里识别订阅：含涨价标记与下次扣款日。"""
    return detect_subscriptions(await _all_transactions(), as_of=date.today())


@router.get("/api/finance/anomalies")
async def anomalies(lookback_days: int = 180) -> dict[str, Any]:
    return detect_anomalies(
        await _all_transactions(),
        as_of=date.today(),
        lookback_days=max(30, min(lookback_days, 730)),
    )


__all__ = ["router"]

"""公司财税路由（v4.5）：税负测算 / 个税 / 工资核算 / 月结清单 / 现金流预测 /
订阅识别 / 异常扣款。

所有计算都在 calculations 包（纯函数），本层只做参数清洗与落库组装。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends

from .. import db
from ..auth import get_current_user
from ..automation_runner import list_workflows, run_workflow
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
from ..db import attribution as attribution_db
from ..db import automation as automation_db
from ..db.tenant import current_tenant_id, current_user_id
from ..finance_attribution import suggest_attributions, validate_category
from ..provenance import record_provenance
from ._responses import bad as _bad

router = APIRouter(dependencies=[Depends(get_current_user)])




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


# ---------------------------------------------------------------------------
# 财税时序（4.17.1）：只读总账已过账凭证，按月压成一条时间轴
# ---------------------------------------------------------------------------


@router.get("/api/finance/timeline")
async def finance_timeline_view(months: int = 12) -> Any:
    return await db.finance_timeline(current_tenant_id(), months=months)


# ---------------------------------------------------------------------------
# 收支归因（4.17.1）：规则/历史候选 + 用户确认，确认前不改账
# ---------------------------------------------------------------------------


@router.get("/api/finance/attribution/candidates")
async def attribution_candidates(limit: int = 50) -> Any:
    rows = await db.list_transactions(limit=800)
    confirmations = await attribution_db.list_confirmations(
        current_tenant_id(), current_user_id()
    )
    out = suggest_attributions(rows, confirmations, limit=limit)
    out["scan_limit"] = 800
    return out


@router.post("/api/finance/attribution/confirm")
async def attribution_confirm(payload: dict[str, Any]) -> Any:
    body = payload or {}
    try:
        tx_id = int(body.get("transaction_id") or 0)
        category = validate_category(body.get("category"))
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    if tx_id <= 0:
        return _bad("transaction_id 必须是正整数")

    tx = await attribution_db.get_transaction(current_user_id(), tx_id)
    if tx is None:
        return _bad(f"流水 {tx_id} 不存在")

    source = str(body.get("source") or "manual")
    if source not in {"rule", "history", "existing", "manual"}:
        source = "manual"
    try:
        confidence = max(0.0, min(float(body.get("confidence") or 0), 1.0))
    except (TypeError, ValueError):
        confidence = 0.0
    matched = body.get("matched")
    matched_list = [str(x)[:24] for x in matched][:5] if isinstance(matched, list) else []

    previous = str(tx.get("category") or "")
    await db.update_transaction(tx_id, category=category)
    confirmation = await attribution_db.upsert_confirmation(
        tenant_id=current_tenant_id(),
        user_id=current_user_id(),
        transaction_id=tx_id,
        original_category=previous,
        confirmed_category=category,
        source=source,
        rule_id=str(body.get("rule_id") or "")[:64],
        confidence=confidence,
        matched=matched_list,
    )
    await record_provenance(
        "attribution_confirm",
        "transaction",
        str(tx_id),
        before={"category": previous},
        after={"category": category},
        source="api",
        metadata={
            "rule_id": confirmation["rule_id"],
            "confidence": confirmation["confidence"],
            "matched": matched_list,
            "attribution_source": source,
        },
    )
    return {
        "ok": True,
        "transaction_id": tx_id,
        "previous_category": previous,
        "category": category,
        "confirmation": confirmation,
    }


# ---------------------------------------------------------------------------
# 自动化运行台账（4.17.0）：真实后台任务的可审计入口
# ---------------------------------------------------------------------------


@router.get("/api/automation/workflows")
async def automation_workflows() -> Any:
    return {"workflows": list_workflows()}


@router.get("/api/automation/runs")
async def automation_runs(limit: int = 20) -> Any:
    runs = await automation_db.list_runs(max(1, min(limit, 200)))
    return {"runs": runs, "count": len(runs)}


@router.post("/api/automation/workflows/{key}/run")
async def automation_run(key: str, payload: dict[str, Any] | None = None) -> Any:
    """手动补跑：与定时任务走同一条实现；同工作流串行。"""
    body = payload or {}
    idem = str(body.get("idempotency_key") or "").strip()[:120]
    try:
        return await run_workflow(key, trigger="manual", idempotency_key=idem)
    except ValueError as exc:
        return _bad(str(exc))


__all__ = ["router"]

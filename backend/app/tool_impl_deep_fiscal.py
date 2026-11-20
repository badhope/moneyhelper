"""深化工具·财税与现金流域：税负、现金流预测、订阅识别、债务清偿、异常扣款。"""

from __future__ import annotations

import json
from typing import Any

from . import db
from .calculations import cashflow_forecast, detect_anomalies, detect_subscriptions


async def tool_tax_calc(args: dict[str, Any]) -> str:
    """税负测算：增值税及附加 / 企业所得税 / 个税累计预扣 / 工资五险一金 / 综合税负。"""
    from .calculations import (
        corporate_income_tax,
        individual_income_tax,
        payroll,
        tax_summary,
        vat,
    )

    kind = str(args.get("kind") or "summary")
    try:
        if kind == "vat":
            out = vat(
                sales=float(args.get("sales") or args.get("revenue") or 0),
                purchases=float(args.get("purchases") or args.get("cost") or 0),
                rate=float(args.get("vat_rate") or 0.13),
                simple=bool(args.get("vat_simple")),
                location=str(args.get("location") or "city"),
            )
        elif kind == "cit":
            out = corporate_income_tax(
                revenue=float(args.get("revenue") or 0),
                cost=float(args.get("cost") or 0),
                expenses=float(args.get("expenses") or 0),
                category=str(args.get("cit_category") or "standard"),
            )
        elif kind == "iit":
            out = individual_income_tax(
                monthly_salary=float(args.get("monthly_salary") or 0),
                months=int(args.get("months") or 1),
                social_insurance=float(args.get("social_insurance") or 0),
                housing_fund=float(args.get("housing_fund") or 0),
                special_additional=float(args.get("special_additional") or 0),
            )
        elif kind == "payroll":
            res = payroll(
                gross_salary=float(args.get("gross_salary") or args.get("monthly_salary") or 0),
                special_additional=float(args.get("special_additional") or 0),
                months=int(args.get("months") or 1),
            )
            out = {
                "gross": res.gross,
                "employee": res.employee,
                "employer": res.employer,
                "employee_total": res.employee_total,
                "employer_total": res.employer_total,
                "income_tax": res.income_tax,
                "current_month_tax": res.current_month_tax,
                "net_pay": res.net_pay,
                "period_net_pay": res.period_net_pay,
                "employer_cost": res.employer_cost,
                "notes": res.notes,
            }
        else:
            out = tax_summary(
                revenue=float(args.get("revenue") or 0),
                cost=float(args.get("cost") or 0),
                expenses=float(args.get("expenses") or 0),
                vat_rate=float(args.get("vat_rate") or 0.13),
                vat_simple=bool(args.get("vat_simple")),
                location=str(args.get("location") or "city"),
                cit_category=str(args.get("cit_category") or "standard"),
                payroll_gross=float(args.get("payroll_gross") or 0),
            )
    except ValueError as exc:
        return f"税负测算失败：{exc}"
    return json.dumps({"kind": kind, "result": out}, ensure_ascii=False, default=str)


async def tool_cashflow_forecast(args: dict[str, Any]) -> str:
    """现金流三档预测：基于历史月度净流入分布，给出悲观/中性/乐观的余额路径。"""
    positions = await db.list_positions()
    cash = sum(
        float(p.get("shares", 0)) * float(p.get("last", 0))
        for p in positions
        if p.get("kind") == "现金"
    )
    opening = float(args.get("opening_balance") or 0) or cash
    out = cashflow_forecast(
        await db.list_transactions(),
        months_ahead=int(args.get("months_ahead") or 3),
        opening_balance=opening,
    )
    return json.dumps(out, ensure_ascii=False, default=str)


async def tool_scan_subscriptions(_args: dict[str, Any]) -> str:
    """识别订阅扣款：周期、金额、下次扣款日、涨价标记。"""
    out = detect_subscriptions(await db.list_transactions())
    return json.dumps(out, ensure_ascii=False, default=str)


async def tool_debt_payoff_plan(args: dict[str, Any]) -> str:
    """债务清偿规划：按账本负债做逐月摊还模拟，给出还清顺序、月数、总利息与可省利息。"""
    from .calculations import compare_methods, plan_payoff

    debts = []
    for r in await db.list_debts():
        name = str(r.get("name") or "").strip()
        if not name:
            continue
        debts.append(
            {
                "name": name,
                "balance": float(r.get("balance") or 0),
                "rate": float(r.get("rate") or 0),
                "min_payment": float(r.get("monthly") or 0),
            }
        )
    if not debts:
        return json.dumps(
            {
                "available": False,
                "reason": "账本里还没有负债记录，先让用户录入欠款本金、年利率与月供",
            },
            ensure_ascii=False,
        )
    extra = float(args.get("extra_payment") or 0)
    method = str(args.get("method") or "avalanche").lower()
    if args.get("compare"):
        return json.dumps(compare_methods(debts, extra), ensure_ascii=False, default=str)
    order = [x.strip() for x in str(args.get("custom_order") or "").split(",") if x.strip()]
    plan = plan_payoff(
        debts,
        extra_payment=extra,
        method=method,  # type: ignore[arg-type]
        custom_order=order or None,
        include_schedule=False,
    )
    out = plan.to_dict(include_schedule=False)
    out["available"] = True
    out["debts"] = debts
    return json.dumps(out, ensure_ascii=False, default=str)


async def tool_scan_anomalies(args: dict[str, Any]) -> str:
    """异常扣款检测：中位数 + MAD 判离群，输出异常倍数与建议。"""
    out = detect_anomalies(
        await db.list_transactions(), lookback_days=int(args.get("lookback_days") or 180)
    )
    return json.dumps(out, ensure_ascii=False, default=str)

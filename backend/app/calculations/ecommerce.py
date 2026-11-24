"""电商经营测算（纯确定性，4.23.0）。

面向“卖货到底赚不赚钱”的一页账：GMV、退款、平台佣金、支付费、推广、
货品成本、履约、增值税与所得税。输出净销售额、贡献毛利、净利、
盈亏平衡 ROAS 与单均结果，不接平台、不猜流量。
"""

from __future__ import annotations

import math
from typing import Any


def _num(data: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = float(data.get(key, default))
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        raise ValueError(f"{key} 必须是有限数字")
    return value


def _pct(data: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = _num(data, key, default)
    if value < 0:
        raise ValueError(f"{key} 不能为负")
    if value > 100:
        raise ValueError(f"{key} 不能超过 100%")
    return value


def _money(value: float) -> float:
    return round(float(value) + 1e-9, 2)


def _ratio(value: float) -> float:
    return round(float(value) + 1e-9, 4)


def calculate(raw: dict[str, Any]) -> dict[str, Any]:
    gmv = _num(raw, "gmv")
    refunds = _num(raw, "refunds")
    orders = int(_num(raw, "orders"))
    if gmv < 0 or refunds < 0:
        raise ValueError("GMV 与退款不能为负")
    if refunds > gmv:
        raise ValueError("退款不能大于 GMV")
    if orders < 0:
        raise ValueError("订单数不能为负")

    commission = _pct(raw, "commission_pct")
    payment = _pct(raw, "payment_pct")
    vat_rate = _pct(raw, "vat_rate_pct", 13.0)
    surtax = _pct(raw, "surtax_pct", 12.0)
    income_tax_rate = _pct(raw, "income_tax_pct", 25.0)
    ad_spend = _num(raw, "ad_spend")
    cogs = _num(raw, "cogs")
    fulfillment = _num(raw, "fulfillment")
    other_cost = _num(raw, "other_cost")
    input_vat = _num(raw, "input_vat")
    if min(ad_spend, cogs, fulfillment, other_cost, input_vat) < 0:
        raise ValueError("成本项不能为负")

    net_sales = gmv - refunds
    output_vat = net_sales / (1 + vat_rate / 100) * (vat_rate / 100) if vat_rate else 0.0
    vat_payable = max(output_vat - input_vat, 0.0)
    surtax_cost = vat_payable * (surtax / 100)
    platform_fee = net_sales * (commission / 100)
    payment_fee = net_sales * (payment / 100)

    gross_profit = net_sales - cogs
    contribution_before_ad = (
        net_sales - cogs - platform_fee - payment_fee - fulfillment - other_cost - surtax_cost
    )
    contribution_after_ad = contribution_before_ad - ad_spend
    profit_before_tax = contribution_after_ad
    income_tax = max(profit_before_tax, 0.0) * (income_tax_rate / 100)
    net_profit = profit_before_tax - income_tax

    net_margin = net_profit / net_sales if net_sales else 0.0
    gross_margin = gross_profit / net_sales if net_sales else 0.0
    contribution_margin = contribution_after_ad / net_sales if net_sales else 0.0
    ros = net_profit / gmv if gmv else 0.0
    refund_rate = refunds / gmv if gmv else 0.0
    aov = gmv / orders if orders else 0.0
    per_order_profit = net_profit / orders if orders else 0.0
    ad_roas = net_sales / ad_spend if ad_spend else 0.0
    breakeven_ad_spend = max(contribution_before_ad, 0.0)
    breakeven_roas = net_sales / breakeven_ad_spend if breakeven_ad_spend > 0 else 0.0

    warnings: list[dict[str, str]] = []
    if net_sales <= 0:
        warnings.append({"level": "danger", "text": "退款后净销售额为零或为负"})
    if net_profit < 0:
        warnings.append({"level": "danger", "text": "当前测算为亏损，先别加推广预算"})
    if contribution_before_ad <= 0:
        warnings.append({"level": "danger", "text": "商品与平台扣费本身不赚钱，加推广也补不回来"})
    elif ad_spend > contribution_before_ad:
        warnings.append({"level": "warn", "text": "推广费已吃掉全部商品贡献"})
    if refund_rate > 0.2:
        warnings.append({"level": "warn", "text": f"退款率 {refund_rate:.1%} 偏高，先查质量与描述"})
    if cogs > net_sales > 0:
        warnings.append({"level": "danger", "text": "货品成本高于净销售额"})
    if input_vat > output_vat and output_vat > 0:
        warnings.append({"level": "info", "text": "进项税大于销项税，本期增值税留抵"})

    if net_profit > 0 and net_margin >= 0.08:
        verdict = "healthy"
    elif net_profit > 0:
        verdict = "thin"
    else:
        verdict = "loss"

    return {
        "verdict": verdict,
        "net_sales": _money(net_sales),
        "refund_rate": _ratio(refund_rate),
        "gross_profit": _money(gross_profit),
        "gross_margin": _ratio(gross_margin),
        "platform_fee": _money(platform_fee),
        "payment_fee": _money(payment_fee),
        "output_vat": _money(output_vat),
        "vat_payable": _money(vat_payable),
        "surtax": _money(surtax_cost),
        "contribution_before_ad": _money(contribution_before_ad),
        "ad_spend": _money(ad_spend),
        "contribution_after_ad": _money(contribution_after_ad),
        "contribution_margin": _ratio(contribution_margin),
        "profit_before_tax": _money(profit_before_tax),
        "income_tax": _money(income_tax),
        "net_profit": _money(net_profit),
        "net_margin": _ratio(net_margin),
        "ros": _ratio(ros),
        "aov": _money(aov),
        "per_order_profit": _money(per_order_profit),
        "ad_roas": _ratio(ad_roas),
        "breakeven_ad_spend": _money(breakeven_ad_spend),
        "breakeven_roas": _ratio(breakeven_roas),
        "warnings": warnings,
        "formula_note": "增值税按含税净销售额价税分离；附加税按应纳增值税计；所得税只对正利润计提。",
    }

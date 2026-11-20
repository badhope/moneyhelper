"""企业所得税：25%/15%/20%小微减半/5%，支持以前年度亏损结转。"""

from __future__ import annotations

from typing import Any

from .tax_common import _round

CIT_RATES = {
    "standard": 0.25,
    "high_tech": 0.15,
    "small_micro": 0.05,  # 小微企业 2023-2027：应纳税所得额 ≤300 万，实际税负 5%
    "small_micro_20": 0.20,
}

SMALL_MICRO_LIMIT = 3_000_000.0

def corporate_income_tax(
    *,
    revenue: float,
    cost: float = 0.0,
    expenses: float = 0.0,
    other_deductions: float = 0.0,
    loss_carryforward: float = 0.0,
    category: str = "standard",
    tax_adjustments: float = 0.0,
) -> dict[str, Any]:
    """企业所得税：应纳税所得额 = 收入 - 成本 - 费用 - 其他扣除 - 弥补亏损 + 纳税调增。

    category：standard 25% / high_tech 15% / small_micro 5%（≤300 万部分）。
    小微超过 300 万时，全额按 25% 计（现行口径不是超额累进）。
    """
    if revenue < 0:
        raise ValueError("收入不能为负")
    if category not in CIT_RATES:
        raise ValueError(f"category 只能是 {'/'.join(CIT_RATES)}")

    accounting_profit = revenue - cost - expenses - other_deductions
    taxable = accounting_profit - max(0.0, loss_carryforward) + tax_adjustments
    taxable = max(0.0, taxable)
    effective_category = category
    note = ""
    if category == "small_micro" and taxable > SMALL_MICRO_LIMIT:
        effective_category = "standard"
        note = f"应纳税所得额 {taxable:,.2f} 超过 300 万，不再适用小微优惠，按 25% 计"
    rate = CIT_RATES[effective_category]
    tax = _round(taxable * rate, 2)
    return {
        "accounting_profit": _round(accounting_profit, 2),
        "taxable_income": _round(taxable, 2),
        "loss_used": _round(min(max(0.0, loss_carryforward), max(0.0, accounting_profit)), 2),
        "rate": rate,
        "category": effective_category,
        "tax_payable": tax,
        "net_profit": _round(accounting_profit - tax, 2),
        "effective_rate": _round(tax / taxable, 4) if taxable > 0 else 0.0,
        "note": note,
    }

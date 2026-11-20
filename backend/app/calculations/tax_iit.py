"""个人所得税（工资薪金累计预扣）：7 级超额累进 + 5000 起征 + 专项附加扣除。"""

from __future__ import annotations

from typing import Any

from .tax_common import _round

IIT_BRACKETS: tuple[tuple[float, float, float], ...] = (
    (0.0, 36_000.0, 0.03),
    (36_000.0, 144_000.0, 0.10),
    (144_000.0, 300_000.0, 0.20),
    (300_000.0, 420_000.0, 0.25),
    (420_000.0, 660_000.0, 0.30),
    (660_000.0, 960_000.0, 0.35),
    (960_000.0, float("inf"), 0.45),
)

IIT_MONTHLY_THRESHOLD = 5_000.0

IIT_QUICK_DEDUCTION = (0.0, 2_520.0, 16_920.0, 31_920.0, 52_920.0, 85_920.0, 181_920.0)

def _iit_annual(taxable: float) -> float:
    """按年应纳税所得额查 7 级超额累进，返回税额。"""
    if taxable <= 0:
        return 0.0
    for idx, (_low, high, rate) in enumerate(IIT_BRACKETS):
        if taxable <= high:
            return _round(taxable * rate - IIT_QUICK_DEDUCTION[idx], 2)
    return _round(taxable * 0.45 - IIT_QUICK_DEDUCTION[-1], 2)

def individual_income_tax(
    *,
    monthly_salary: float,
    months: int = 1,
    social_insurance: float = 0.0,
    housing_fund: float = 0.0,
    special_additional: float = 0.0,
    other_deductions: float = 0.0,
    already_withheld: float = 0.0,
) -> dict[str, Any]:
    """工资薪金个税（累计预扣法）。

    累计应纳税所得额 = 累计收入 - 累计减除费用（5000×月数）- 累计三险一金
                     - 累计专项附加扣除 - 累计其他扣除
    本期应预扣 = 累计应纳税额 - 已预扣税额（可为 0，不倒贴）。

    返回累计口径与本期口径，便于工资条逐月核对。
    """
    if monthly_salary < 0:
        raise ValueError("工资不能为负")
    if months < 1 or months > 12:
        raise ValueError("months 需在 1-12")

    gross = monthly_salary * months
    basic = IIT_MONTHLY_THRESHOLD * months
    social = social_insurance * months
    fund = housing_fund * months
    special = special_additional * months
    other = other_deductions * months
    taxable = max(0.0, gross - basic - social - fund - special - other)
    cumulative_tax = _iit_annual(taxable)
    current = max(0.0, _round(cumulative_tax - max(0.0, already_withheld), 2))
    return {
        "months": months,
        "cumulative_income": _round(gross, 2),
        "cumulative_threshold": _round(basic, 2),
        "cumulative_social": _round(social, 2),
        "cumulative_housing_fund": _round(fund, 2),
        "cumulative_special_additional": _round(special, 2),
        "cumulative_other": _round(other, 2),
        "taxable_income": _round(taxable, 2),
        "cumulative_tax": cumulative_tax,
        "already_withheld": _round(already_withheld, 2),
        "current_withholding": current,
        "effective_rate": _round(cumulative_tax / gross, 4) if gross > 0 else 0.0,
    }

"""工资核算：五险一金个人/企业两侧、基数上下限钳制、应发代扣实发与企业成本。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .tax_common import _round
from .tax_iit import individual_income_tax

DEFAULT_EMPLOYEE_RATES = {"pension": 0.08, "medical": 0.02, "unemployment": 0.005, "housing_fund": 0.12}

DEFAULT_EMPLOYER_RATES = {
    "pension": 0.16,
    "medical": 0.08,
    "unemployment": 0.005,
    "injury": 0.002,
    "maternity": 0.0,
    "housing_fund": 0.12,
}

@dataclass
class PayrollResult:
    gross: float
    employee: dict[str, float]
    employer: dict[str, float]
    employee_total: float
    employer_total: float
    taxable_income: float
    income_tax: float
    net_pay: float
    employer_cost: float
    # months>1 时 income_tax 是累计口径，这两个字段把"单月"与"期间"分开，
    # 避免把 N 个月的税减在 1 个月的工资上（见 payroll() 内注释）。
    current_month_tax: float = 0.0
    period_net_pay: float = 0.0
    notes: list[str] = field(default_factory=list)

def payroll(
    *,
    gross_salary: float,
    social_base: float | None = None,
    housing_base: float | None = None,
    employee_rates: dict[str, float] | None = None,
    employer_rates: dict[str, float] | None = None,
    base_min: float = 3_500.0,
    base_max: float = 35_000.0,
    housing_base_min: float | None = None,
    housing_base_max: float | None = None,
    special_additional: float = 0.0,
    other_deductions: float = 0.0,
    already_withheld: float = 0.0,
    months: int = 1,
) -> PayrollResult:
    """月度工资核算：应发 → 五险一金 → 个税 → 实发；并给出企业总成本。

    缴费基数默认等于应发工资，并按 [base_min, base_max] 钳制（各地上下限差异大，
    调用方可直接传入本地口径）。公积金基数可单独指定，且上下限独立
    （housing_base_min / housing_base_max，默认沿用社保口径）——
    公积金上限普遍高于社保，共用一个 base_max 会把用户显式传入的
    高基数悄悄压回去（旧实现：传 housing_base=50000、base_max=35000，
    结果按 35000 计，只在 notes 里留一句钳制提示）。

    months > 1 时 income_tax 是**累计口径**（累计应预扣 − 已预扣），
    net_pay 始终是**单月实发**，period_net_pay 才是这 months 个月的合计实发。
    """
    if gross_salary < 0:
        raise ValueError("应发工资不能为负")
    if base_min > base_max:
        # 区间反了会让 min(max(...)) 静默退化成 base_max，
        # 基数与提示文案互相矛盾（实测提示"钳制为 3500"而区间写的是 [35000, 3500]）。
        raise ValueError(f"缴费基数下限不能大于上限（base_min={base_min} > base_max={base_max}）")
    h_min = base_min if housing_base_min is None else float(housing_base_min)
    h_max = base_max if housing_base_max is None else float(housing_base_max)
    if h_min > h_max:
        raise ValueError(
            f"公积金基数下限不能大于上限（housing_base_min={h_min} > housing_base_max={h_max}）"
        )
    er = {**DEFAULT_EMPLOYEE_RATES, **(employee_rates or {})}
    cr = {**DEFAULT_EMPLOYER_RATES, **(employer_rates or {})}

    s_base = min(max(float(social_base if social_base is not None else gross_salary), base_min), base_max)
    h_base = min(max(float(housing_base if housing_base is not None else gross_salary), h_min), h_max)
    notes: list[str] = []
    if (social_base is not None and float(social_base) != s_base) or (
        social_base is None and gross_salary != s_base
    ):
        notes.append(f"社保基数按 [{base_min:.0f}, {base_max:.0f}] 钳制为 {s_base:.2f}")
    if housing_base is not None and float(housing_base) != h_base:
        notes.append(f"公积金基数按 [{h_min:.0f}, {h_max:.0f}] 钳制为 {h_base:.2f}")

    employee = {
        "pension": _round(s_base * er["pension"], 2),
        "medical": _round(s_base * er["medical"], 2),
        "unemployment": _round(s_base * er["unemployment"], 2),
        "housing_fund": _round(h_base * er["housing_fund"], 2),
    }
    employer = {
        "pension": _round(s_base * cr["pension"], 2),
        "medical": _round(s_base * cr["medical"], 2),
        "unemployment": _round(s_base * cr["unemployment"], 2),
        "injury": _round(s_base * cr["injury"], 2),
        "maternity": _round(s_base * cr["maternity"], 2),
        "housing_fund": _round(h_base * cr["housing_fund"], 2),
    }
    employee_total = _round(sum(employee.values()), 2)
    employer_total = _round(sum(employer.values()), 2)

    tax = individual_income_tax(
        monthly_salary=gross_salary,
        months=months,
        social_insurance=employee["pension"] + employee["medical"] + employee["unemployment"],
        housing_fund=employee["housing_fund"],
        special_additional=special_additional,
        other_deductions=other_deductions,
        already_withheld=already_withheld,
    )
    income_tax = tax["current_withholding"]
    # net_pay 是"单月实发"，而 income_tax 在 months>1 时覆盖整个累计期间。
    # 旧实现把 N 个月的税减在 1 个月的工资上：月薪 3 万、months=3、
    # already_withheld=0 时 income_tax=2955（三个月累计），net_pay 报 20295，
    # 而该月正确实发是 21425 —— 前端「实发工资」卡片直接少了一个月的税，
    # 且没有任何字段说明这是累计口径。
    if months > 1 and max(0.0, already_withheld) <= 0.0:
        prev = individual_income_tax(
            monthly_salary=gross_salary,
            months=months - 1,
            social_insurance=employee["pension"] + employee["medical"] + employee["unemployment"],
            housing_fund=employee["housing_fund"],
            special_additional=special_additional,
            other_deductions=other_deductions,
        )
        current_month_tax = max(0.0, _round(tax["cumulative_tax"] - prev["cumulative_tax"], 2))
        notes.append(
            f"months={months}：income_tax 为累计应预扣（{income_tax:,.2f}），"
            f"net_pay 按当月应预扣 {current_month_tax:,.2f} 计算，"
            f"期间合计实发见 period_net_pay"
        )
    else:
        current_month_tax = income_tax
    net_pay = _round(gross_salary - employee_total - current_month_tax, 2)
    period_net_pay = _round(
        gross_salary * months - employee_total * months - income_tax, 2
    )
    return PayrollResult(
        gross=_round(gross_salary, 2),
        employee=employee,
        employer=employer,
        employee_total=employee_total,
        employer_total=employer_total,
        taxable_income=tax["taxable_income"],
        income_tax=income_tax,
        current_month_tax=current_month_tax,
        net_pay=net_pay,
        period_net_pay=period_net_pay,
        employer_cost=_round(gross_salary + employer_total, 2),
        notes=notes,
    )

"""中国大陆税负与薪酬核算引擎（确定性，纯函数）。

覆盖四类真实场景，参数全部显式传入，不猜政策：

1. **增值税及附加**：一般纳税人（13% / 9% / 6%）与简易计税（5% / 3% / 1%），
   附加税按「城建税 7%/5%/1% + 教育费附加 3% + 地方教育附加 2%」计算，
   附加税以实际缴纳的增值税为计税依据。
2. **企业所得税**：25% 标准税率、15% 高新技术、20% 小微（含 2023-2027 减半口径）、
   5% 小微优惠档；支持弥补以前年度亏损（5 年结转）。
3. **个人所得税（工资薪金，累计预扣法）**：7 级超额累进 + 每月 5000 起征点 +
   三险一金专项扣除 + 子女教育/继续教育/大病医疗/住房贷款利息/住房租金/赡养老人/
   3 岁以下婴幼儿照护 专项附加扣除。
4. **工资核算**：五险一金个人与企业两侧，按缴费基数上下限钳制；输出应发、代扣、实发、
   企业总成本。

边界与免责：
- 社保比例按「通用城镇职工」口径给默认值，各地差异极大（尤其公积金 5%-12%、医保地方附加），
  因此**所有比例都作为参数**，默认值只用于演示；
- 税收优惠（小微、高新、研发加计）需用户确认自身资质，本模块只做算术，不做资格判定；
- 输出带 `disclaimer`，不构成正式税务意见。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# 增值税
# ---------------------------------------------------------------------------

# 一般计税税率（2026 年现行：13% 货物/13% 服务中的动产租赁、9% 交通运输/建筑/不动产、6% 现代服务）
VAT_GENERAL_RATES = (0.13, 0.09, 0.06, 0.0)
# 简易计税征收率
VAT_SIMPLE_RATES = (0.05, 0.03, 0.01)
# 附加税：城建税按纳税人所在地（市区 7% / 县城镇 5% / 其他 1%）
SURCHARGE_RATES = {"city": 0.07, "county": 0.05, "other": 0.01}
EDU_SURCHARGE = 0.03
LOCAL_EDU_SURCHARGE = 0.02


def vat(
    *,
    sales: float,
    purchases: float = 0.0,
    rate: float = 0.13,
    simple: bool = False,
    simple_rate: float = 0.03,
    location: str = "city",
    exempt_threshold: float = 0.0,
) -> dict[str, Any]:
    """增值税及附加。

    一般计税：销项 = 销售额（不含税）× 税率；进项 = 采购额（不含税）× 税率；
    应纳 = 销项 - 进项（负数按 0 计，留抵下期，这里不虚拟抵扣）。
    简易计税：应纳 = 销售额（不含税）× 征收率，进项不得抵扣。

    exempt_threshold：小规模纳税人月销售额未超阈值免征（默认 0=不启用）。
    """
    if sales < 0 or purchases < 0:
        raise ValueError("销售额与采购额不能为负")
    if location not in SURCHARGE_RATES:
        raise ValueError(f"location 只能是 {'/'.join(SURCHARGE_RATES)}")

    if exempt_threshold and sales <= exempt_threshold:
        return {
            "method": "exempt",
            "output_vat": 0.0,
            "input_vat": 0.0,
            "vat_payable": 0.0,
            "surcharge": 0.0,
            "total": 0.0,
            "note": f"销售额 {sales:.2f} 未超过免征阈值 {exempt_threshold:.2f}",
        }

    if simple:
        if simple_rate not in VAT_SIMPLE_RATES:
            raise ValueError(f"简易计税征收率只能是 {VAT_SIMPLE_RATES}")
        output_vat = round(sales * simple_rate, 2)
        input_vat = 0.0
        payable = output_vat
        method = f"simple@{simple_rate:.0%}"
    else:
        if rate not in VAT_GENERAL_RATES:
            raise ValueError(f"一般计税税率只能是 {VAT_GENERAL_RATES}")
        output_vat = round(sales * rate, 2)
        input_vat = round(purchases * rate, 2)
        payable = max(0.0, round(output_vat - input_vat, 2))
        method = f"general@{rate:.0%}"

    city_rate = SURCHARGE_RATES[location]
    surcharge = round(payable * (city_rate + EDU_SURCHARGE + LOCAL_EDU_SURCHARGE), 2)
    return {
        "method": method,
        "output_vat": output_vat,
        "input_vat": input_vat,
        "vat_payable": payable,
        "surcharge_detail": {
            "city_construction": round(payable * city_rate, 2),
            "education": round(payable * EDU_SURCHARGE, 2),
            "local_education": round(payable * LOCAL_EDU_SURCHARGE, 2),
        },
        "surcharge": surcharge,
        "total": round(payable + surcharge, 2),
        "note": "进项大于销项时留抵下期，本次按 0 申报"
        if (not simple and output_vat < input_vat)
        else "",
    }


# ---------------------------------------------------------------------------
# 企业所得税
# ---------------------------------------------------------------------------

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
    tax = round(taxable * rate, 2)
    return {
        "accounting_profit": round(accounting_profit, 2),
        "taxable_income": round(taxable, 2),
        "loss_used": round(min(max(0.0, loss_carryforward), max(0.0, accounting_profit)), 2),
        "rate": rate,
        "category": effective_category,
        "tax_payable": tax,
        "net_profit": round(accounting_profit - tax, 2),
        "effective_rate": round(tax / taxable, 4) if taxable > 0 else 0.0,
        "note": note,
    }


# ---------------------------------------------------------------------------
# 个人所得税（累计预扣法）
# ---------------------------------------------------------------------------

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
# 速算扣除数（按年累计口径）
IIT_QUICK_DEDUCTION = (0.0, 2_520.0, 16_920.0, 31_920.0, 52_920.0, 85_920.0, 181_920.0)


def _iit_annual(taxable: float) -> float:
    """按年应纳税所得额查 7 级超额累进，返回税额。"""
    if taxable <= 0:
        return 0.0
    for idx, (_low, high, rate) in enumerate(IIT_BRACKETS):
        if taxable <= high:
            return round(taxable * rate - IIT_QUICK_DEDUCTION[idx], 2)
    return round(taxable * 0.45 - IIT_QUICK_DEDUCTION[-1], 2)


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
    current = max(0.0, round(cumulative_tax - max(0.0, already_withheld), 2))
    return {
        "months": months,
        "cumulative_income": round(gross, 2),
        "cumulative_threshold": round(basic, 2),
        "cumulative_social": round(social, 2),
        "cumulative_housing_fund": round(fund, 2),
        "cumulative_special_additional": round(special, 2),
        "cumulative_other": round(other, 2),
        "taxable_income": round(taxable, 2),
        "cumulative_tax": cumulative_tax,
        "already_withheld": round(already_withheld, 2),
        "current_withholding": current,
        "effective_rate": round(cumulative_tax / gross, 4) if gross > 0 else 0.0,
    }


# ---------------------------------------------------------------------------
# 工资核算（五险一金）
# ---------------------------------------------------------------------------

# 默认比例按「通用城镇职工」：养老 8%、医疗 2%、失业 0.5%、公积金 12%（个人侧）
DEFAULT_EMPLOYEE_RATES = {"pension": 0.08, "medical": 0.02, "unemployment": 0.005, "housing_fund": 0.12}
# 企业侧：养老 16%、医疗 8%（含生育合并口径各地不同）、失业 0.5%、工伤 0.2%、公积金 12%
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
    special_additional: float = 0.0,
    other_deductions: float = 0.0,
    already_withheld: float = 0.0,
    months: int = 1,
) -> PayrollResult:
    """月度工资核算：应发 → 五险一金 → 个税 → 实发；并给出企业总成本。

    缴费基数默认等于应发工资，并按 [base_min, base_max] 钳制（各地上下限差异大，
    调用方可直接传入本地口径）。公积金基数可单独指定（常见上限高于社保）。
    """
    if gross_salary < 0:
        raise ValueError("应发工资不能为负")
    er = {**DEFAULT_EMPLOYEE_RATES, **(employee_rates or {})}
    cr = {**DEFAULT_EMPLOYER_RATES, **(employer_rates or {})}

    s_base = min(max(float(social_base if social_base is not None else gross_salary), base_min), base_max)
    h_base = min(max(float(housing_base if housing_base is not None else gross_salary), base_min), base_max)
    notes: list[str] = []
    if (social_base is not None and float(social_base) != s_base) or (
        social_base is None and gross_salary != s_base
    ):
        notes.append(f"社保基数按 [{base_min:.0f}, {base_max:.0f}] 钳制为 {s_base:.2f}")
    if housing_base is not None and float(housing_base) != h_base:
        notes.append(f"公积金基数钳制为 {h_base:.2f}")

    employee = {
        "pension": round(s_base * er["pension"], 2),
        "medical": round(s_base * er["medical"], 2),
        "unemployment": round(s_base * er["unemployment"], 2),
        "housing_fund": round(h_base * er["housing_fund"], 2),
    }
    employer = {
        "pension": round(s_base * cr["pension"], 2),
        "medical": round(s_base * cr["medical"], 2),
        "unemployment": round(s_base * cr["unemployment"], 2),
        "injury": round(s_base * cr["injury"], 2),
        "maternity": round(s_base * cr["maternity"], 2),
        "housing_fund": round(h_base * cr["housing_fund"], 2),
    }
    employee_total = round(sum(employee.values()), 2)
    employer_total = round(sum(employer.values()), 2)

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
    net_pay = round(gross_salary - employee_total - income_tax, 2)
    return PayrollResult(
        gross=round(gross_salary, 2),
        employee=employee,
        employer=employer,
        employee_total=employee_total,
        employer_total=employer_total,
        taxable_income=tax["taxable_income"],
        income_tax=income_tax,
        net_pay=net_pay,
        employer_cost=round(gross_salary + employer_total, 2),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# 月度结账清单（公司财务工作流）
# ---------------------------------------------------------------------------

MONTH_END_CHECKLIST: tuple[dict[str, str], ...] = (
    {"id": "bank_recon", "title": "银行对账", "detail": "银行存款日记账与银行对账单逐笔核对，未达账项编制余额调节表"},
    {"id": "cash_count", "title": "现金盘点", "detail": "库存现金实盘与账面核对，差异查明原因并审批"},
    {"id": "invoice_match", "title": "发票勾稽", "detail": "进项/销项发票与账面收入成本匹配，查验异常发票"},
    {"id": "payroll_accrual", "title": "工资计提", "detail": "计提本月工资、社保、公积金，核对个税申报表"},
    {"id": "vat_filing", "title": "增值税申报", "detail": "销项-进项核对，确认留抵与附加税计税依据"},
    {"id": "cit_accrual", "title": "企业所得税计提", "detail": "按季度预缴口径计提，检查纳税调整事项"},
    {"id": "accruals", "title": "费用计提与摊销", "detail": "房租、利息、折旧、长期待摊费用按期分摊"},
    {"id": "inventory", "title": "存货盘点", "detail": "账实核对，计提跌价准备，处理盘盈盘亏"},
    {"id": "ar_ap", "title": "往来核对", "detail": "应收/应付账龄分析，超期款项催收或付款安排"},
    {"id": "statements", "title": "报表勾稽", "detail": "资产负债表平衡、利润表与现金流量表勾稽、所有者权益变动核对"},
    {"id": "tax_calendar", "title": "税务日历", "detail": "确认次月申报期限与优惠备案到期日"},
    {"id": "archive", "title": "凭证归档", "detail": "凭证装订、附件齐全、电子档案备份"},
)


def month_end_checklist(month: str, *, completed: list[str] | None = None) -> dict[str, Any]:
    """生成月度结账清单：返回每项状态与完成度。

    month: YYYY-MM；completed: 已完成的项 id 列表（前端勾选后回传）。
    """
    if not month or len(month) != 7 or month[4] != "-":
        raise ValueError("month 需为 YYYY-MM")
    done = set(completed or [])
    items = [
        {**item, "done": item["id"] in done}
        for item in MONTH_END_CHECKLIST
    ]
    done_count = sum(1 for i in items if i["done"])
    return {
        "month": month,
        "items": items,
        "done": done_count,
        "total": len(items),
        "progress_pct": round(done_count / len(items) * 100, 1),
        "disclaimer": "清单为通用流程模板，具体科目与申报口径以主管税务机关及企业会计政策为准。",
    }


def tax_summary(
    *,
    revenue: float,
    cost: float,
    expenses: float,
    vat_rate: float = 0.13,
    vat_simple: bool = False,
    location: str = "city",
    cit_category: str = "standard",
    payroll_gross: float = 0.0,
    payroll_months: int = 12,
) -> dict[str, Any]:
    """一键税负测算：增值税及附加 + 企业所得税 + 人工成本，输出综合税负率。

    口径：revenue / cost 均按不含税金额；payroll_gross 为月应发工资合计。
    """
    v = vat(sales=revenue, purchases=cost, rate=vat_rate, simple=vat_simple, location=location)
    # 附加税可税前扣除，故先从利润中扣掉
    cit = corporate_income_tax(
        revenue=revenue,
        cost=cost,
        expenses=expenses + v["surcharge"],
        category=cit_category,
    )
    annual_payroll = payroll_gross * payroll_months
    total_tax = round(v["total"] + cit["tax_payable"], 2)
    return {
        "vat": v,
        "cit": cit,
        "annual_payroll_cost": round(annual_payroll, 2),
        "total_tax": total_tax,
        "tax_burden_pct": round(total_tax / revenue * 100, 2) if revenue > 0 else 0.0,
        "disclaimer": "测算结果不构成税务意见；优惠资格、税前扣除凭证与地方附加比例需按实际确认。",
    }

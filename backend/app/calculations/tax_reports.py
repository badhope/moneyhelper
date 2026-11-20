"""税务报表口径：月末结账清单与税负汇总（增值税+企业所得税）。"""

from __future__ import annotations

from typing import Any

from .tax_cit import corporate_income_tax
from .tax_common import _round
from .tax_vat import vat

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
    # 只校验长度和分隔符会放过 "2026-13" / "2026-00"：清单照样生成，
    # 但那条记录挂在一个不存在的月份上，之后按月查询永远查不到。
    yy, mm = month[:4], month[5:]
    if not (yy.isdigit() and mm.isdigit()) or not 1 <= int(mm) <= 12:
        raise ValueError(f"month 不是合法年月：{month}（需为 YYYY-MM，月份 01-12）")
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
        "progress_pct": _round(done_count / len(items) * 100, 1),
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
    total_tax = _round(v["total"] + cit["tax_payable"], 2)
    return {
        "vat": v,
        "cit": cit,
        "annual_payroll_cost": _round(annual_payroll, 2),
        "total_tax": total_tax,
        "tax_burden_pct": _round(total_tax / revenue * 100, 2) if revenue > 0 else 0.0,
        "disclaimer": "测算结果不构成税务意见；优惠资格、税前扣除凭证与地方附加比例需按实际确认。",
    }

"""模板化中文/英文财报叙述，确定性拼接，不调用模型。"""

from __future__ import annotations

from typing import Any


def _fmt(v: float | None, suffix: str = "") -> str:
    return f"{v:,.2f}{suffix}" if v is not None else "—"


def _report_text(
    company: str,
    currency: str,
    parsed: list[dict[str, Any]],
    latest: dict[str, Any],
    prev: dict[str, Any] | None,
    dupont: dict[str, Any],
    alerts: list[dict[str, Any]],
    lang: str = "zh",
) -> str:
    """模板化财报分析报告（确定性，无需模型；模型存在时可在此之上润色）。"""
    m = latest
    lines = [f"【{company}】财报分析（{parsed[-1]['period']}）" if lang == "zh" else f"[{company}] Statement analysis ({parsed[-1]['period']})"]
    if lang == "zh":
        lines.append(
            f"营业收入 {_fmt(m.get('revenue'))}，净利润 {_fmt(m.get('net_profit'))}；"
            f"毛利率 {_fmt(m.get('gross_margin_pct'), '%')}，净利率 {_fmt(m.get('net_margin_pct'), '%')}，"
            f"ROE {_fmt(m.get('roe_pct'), '%')}，ROA {_fmt(m.get('roa_pct'), '%')}。"
        )
        lines.append(
            f"资产负债率 {_fmt(m.get('debt_ratio_pct'), '%')}，流动比率 {_fmt(m.get('current_ratio'))}，"
            f"速动比率 {_fmt(m.get('quick_ratio'))}；"
            f"总资产周转率 {_fmt(m.get('asset_turnover'))}，存货周转率 {_fmt(m.get('inventory_turnover'))}，"
            f"应收账款周转率 {_fmt(m.get('receivables_turnover'))}。"
        )
        if m.get("revenue_yoy_pct") is not None:
            lines.append(
                f"成长性：营收同比 {_fmt(m.get('revenue_yoy_pct'), '%')}，"
                f"净利润同比 {_fmt(m.get('net_profit_yoy_pct'), '%')}。"
            )
        if dupont["complete"]:
            lines.append(
                f"杜邦拆解：ROE = 净利率 {_fmt(dupont['net_margin_pct'], '%')} × 周转率 {_fmt(dupont['asset_turnover'])}"
                f" × 权益乘数 {_fmt(dupont['equity_multiplier'])}。"
            )
        if ocf := m.get("ocf"):
            lines.append(f"现金流：经营 {ocf:,.0f}，投资 {_fmt(m.get('icf'))}，融资 {_fmt(m.get('fcf'))}；"
                         f"经营现金流/净利润 {_fmt(m.get('ocf_to_np'))}。")
        if alerts:
            lines.append("异常预警：" + "；".join(a["text"] for a in alerts) + "。")
        else:
            lines.append("未发现明显异常预警项。")
        lines.append("本报告为报表口径还原与规则引擎输出，供决策参考，不构成投资建议。")
    else:
        lines.append(
            f"Revenue {_fmt(m.get('revenue'))}, net profit {_fmt(m.get('net_profit'))}; "
            f"gross margin {_fmt(m.get('gross_margin_pct'), '%')}, net margin {_fmt(m.get('net_margin_pct'), '%')}, "
            f"ROE {_fmt(m.get('roe_pct'), '%')}, ROA {_fmt(m.get('roa_pct'), '%')}."
        )
        lines.append(
            f"Debt ratio {_fmt(m.get('debt_ratio_pct'), '%')}, current ratio {_fmt(m.get('current_ratio'))}, "
            f"quick ratio {_fmt(m.get('quick_ratio'))}; asset turnover {_fmt(m.get('asset_turnover'))}, "
            f"inventory turnover {_fmt(m.get('inventory_turnover'))}, receivables turnover {_fmt(m.get('receivables_turnover'))}."
        )
        if m.get("revenue_yoy_pct") is not None:
            lines.append(
                f"Growth: revenue YoY {_fmt(m.get('revenue_yoy_pct'), '%')}, "
                f"net profit YoY {_fmt(m.get('net_profit_yoy_pct'), '%')}."
            )
        if dupont["complete"]:
            lines.append(
                f"DuPont: ROE = net margin {_fmt(dupont['net_margin_pct'], '%')} × turnover {_fmt(dupont['asset_turnover'])}"
                f" × equity multiplier {_fmt(dupont['equity_multiplier'])}."
            )
        if m.get("ocf") is not None:
            lines.append(
                f"Cash flow: operating {m['ocf']:,.0f}, investing {_fmt(m.get('icf'))}, financing {_fmt(m.get('fcf'))}; "
                f"OCF/net profit {_fmt(m.get('ocf_to_np'))}."
            )
        if alerts:
            lines.append("Alerts: " + "; ".join(a["text"] for a in alerts) + ".")
        else:
            lines.append("No significant anomalies detected.")
        lines.append("Report is a deterministic restatement of the statements — for reference only, not investment advice.")
    return "\n".join(lines)

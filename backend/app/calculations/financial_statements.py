"""财报分析引擎（企业财务表深度分析 · 纯函数确定性计算）。

输入：标准化的三表 JSON（资产负债表 / 利润表 / 现金流量表，可含多期）。
输出：20+ 财务指标（盈利能力 / 偿债能力 / 营运能力 / 成长能力 / 现金流质量）、
     杜邦分析拆解、同比环比趋势、异常预警清单、模板化分析报告。

输入口径（单位：元，周期建议 YYYY-MM-DD / YYYY-MM）：
{
  "company": "示例公司",
  "currency": "CNY",
  "periods": [
    {
      "period": "2024-12-31",
      "balance_sheet": {
        "total_assets": 0, "total_liabilities": 0, "total_equity": 0,
        "current_assets": 0, "current_liabilities": 0,
        "cash_and_equivalents": 0, "inventory": 0, "accounts_receivable": 0, "goodwill": 0
      },
      "income_statement": {
        "revenue": 0, "gross_profit": 0, "operating_profit": 0, "net_profit": 0,
        "ebit": 0, "interest_expense": 0
      },
      "cashflow_statement": {
        "operating_cashflow": 0, "investing_cashflow": 0, "financing_cashflow": 0
      }
    }
  ]
}

设计原则：
1. 纯函数、无 I/O；金额 round(...,2)，比率 round(...,2)（百分比）。
2. 数据不足的指标返回 None 并标注口径，绝不返回看似合理的假数值。
3. 异常预警按规则引擎输出（code 稳定），不依赖模型；模型只负责叙述。
4. 全部指标为「报表口径还原」，供用户核对原始三表；非审计、非投资建议。
"""

from __future__ import annotations

from typing import Any

GOODWILL_WARN_RATIO = 0.20
OCF_NP_WARN_RATIO = 0.50
DEBT_RATIO_WARN = 0.70
CURRENT_RATIO_WARN = 1.0
GROSS_MARGIN_DROP_PCT = 5.0


def _num(raw: Any) -> float | None:
    """数值解析：None/空/非数字 → None；0 与负数合法。"""
    if raw is None or raw == "" or raw == "-" or isinstance(raw, bool):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _pct(n: float | None, d: float | None) -> float | None:
    """比率 → 百分比；分母无效返回 None。"""
    if n is None or d is None or d == 0:
        return None
    return round(n / d * 100.0, 2)


def _ratio(n: float | None, d: float | None) -> float | None:
    """倍数比率（如周转率、流动比率）；分母无效返回 None。"""
    if n is None or d is None or d == 0:
        return None
    return round(n / d, 2)


def _yoy(cur: float | None, prev: float | None) -> float | None:
    """同比变化百分比；上一期缺失/为 0 返回 None。"""
    if cur is None or prev is None or prev == 0:
        return None
    return round((cur - prev) / abs(prev) * 100.0, 2)


def compute_period_metrics(bs: dict[str, Any], is_: dict[str, Any], cf: dict[str, Any]) -> dict[str, Any]:
    """单期 20+ 指标。字段名与前端组件一一对应。"""
    ta = _num(bs.get("total_assets"))
    tl = _num(bs.get("total_liabilities"))
    te = _num(bs.get("total_equity"))
    ca = _num(bs.get("current_assets"))
    cl = _num(bs.get("current_liabilities"))
    cash = _num(bs.get("cash_and_equivalents"))
    inv = _num(bs.get("inventory"))
    ar = _num(bs.get("accounts_receivable"))
    gw = _num(bs.get("goodwill"))

    rev = _num(is_.get("revenue"))
    gp = _num(is_.get("gross_profit"))
    op = _num(is_.get("operating_profit"))
    np = _num(is_.get("net_profit"))
    ebit = _num(is_.get("ebit")) if _num(is_.get("ebit")) is not None else op
    ie = _num(is_.get("interest_expense"))

    ocf = _num(cf.get("operating_cashflow"))
    icf = _num(cf.get("investing_cashflow"))
    fcf = _num(cf.get("financing_cashflow"))

    equity = te if te is not None else (ta - tl if ta is not None and tl is not None else None)

    return {
        # 盈利能力
        "gross_margin_pct": _pct(gp, rev),
        "operating_margin_pct": _pct(op, rev),
        "net_margin_pct": _pct(np, rev),
        "roe_pct": _pct(np, equity),
        "roa_pct": _pct(np, ta),
        # 偿债能力
        "debt_ratio_pct": _pct(tl, ta),
        "current_ratio": _ratio(ca, cl),
        "quick_ratio": _ratio(ca - inv if ca is not None and inv is not None else None, cl),
        "interest_coverage": _ratio(ebit, ie),
        # 营运能力
        "asset_turnover": _ratio(rev, ta),
        "inventory_turnover": _ratio(rev, inv),
        "receivables_turnover": _ratio(rev, ar),
        # 现金流质量
        "ocf_to_np": _ratio(ocf, np),
        "ocf_ratio_pct": _pct(ocf, rev),
        "ocf": ocf,
        "icf": icf,
        "fcf": fcf,
        # 原始值（供趋势图与核对）
        "revenue": rev,
        "net_profit": np,
        "gross_profit": gp,
        "total_assets": ta,
        "total_liabilities": tl,
        "total_equity": equity,
        "inventory": inv,
        "accounts_receivable": ar,
        "goodwill": gw,
        "cash": cash,
    }


def analyze_statements(payload: dict[str, Any]) -> dict[str, Any] | None:
    """入口：校验输入 → 逐期指标 → 趋势 → 杜邦 → 预警 → 报告文本。

    返回 None 表示输入无效（无 periods 或无可计算期）。
    """
    periods_raw = payload.get("periods") or []
    if not isinstance(periods_raw, list) or not periods_raw:
        return None

    company = str(payload.get("company") or "").strip() or "未命名公司"
    currency = str(payload.get("currency") or "CNY").strip()

    parsed: list[dict[str, Any]] = []
    for p in periods_raw[:12]:  # 最多 12 期，防超大 payload
        if not isinstance(p, dict):
            continue
        period = str(p.get("period") or "").strip()
        bs = p.get("balance_sheet") or {}
        is_ = p.get("income_statement") or {}
        cf = p.get("cashflow_statement") or {}
        if not isinstance(bs, dict) or not isinstance(is_, dict) or not isinstance(cf, dict):
            continue
        metrics = compute_period_metrics(bs, is_, cf)
        if metrics["revenue"] is None and metrics["net_profit"] is None:
            continue  # 三表都是空的期没有分析价值
        # 保留原始现金流三流（供前端 stacked 图与多期对比）
        parsed.append(
            {
                "period": period or f"period-{len(parsed)+1}",
                "metrics": metrics,
                "cashflow": {
                    "operating": _num(cf.get("operating_cashflow")),
                    "investing": _num(cf.get("investing_cashflow")),
                    "financing": _num(cf.get("financing_cashflow")),
                },
            }
        )
    if not parsed:
        return None
    parsed.sort(key=lambda x: x["period"])  # 按时间升序，保证同比口径

    # 同比成长
    for i, item in enumerate(parsed):
        m = item["metrics"]
        if i > 0:
            pm = parsed[i - 1]["metrics"]
            m["revenue_yoy_pct"] = _yoy(m["revenue"], pm["revenue"])
            m["net_profit_yoy_pct"] = _yoy(m["net_profit"], pm["net_profit"])
            m["assets_yoy_pct"] = _yoy(m["total_assets"], pm["total_assets"])
        else:
            m["revenue_yoy_pct"] = None
            m["net_profit_yoy_pct"] = None
            m["assets_yoy_pct"] = None

    latest = parsed[-1]["metrics"]
    prev = parsed[-2]["metrics"] if len(parsed) > 1 else None

    alerts = _build_alerts(parsed, latest, prev)
    dupont = _dupont(latest)
    report_text = _report_text(company, currency, parsed, latest, prev, dupont, alerts)

    return {
        "company": company,
        "currency": currency,
        "period_count": len(parsed),
        "periods": parsed,
        "latest": latest,
        "trends": {
            "periods": [p["period"] for p in parsed],
            "revenue": [p["metrics"]["revenue"] for p in parsed],
            "net_profit": [p["metrics"]["net_profit"] for p in parsed],
            "gross_margin": [p["metrics"]["gross_margin_pct"] for p in parsed],
            "net_margin": [p["metrics"]["net_margin_pct"] for p in parsed],
            "roe": [p["metrics"]["roe_pct"] for p in parsed],
            "debt_ratio": [p["metrics"]["debt_ratio_pct"] for p in parsed],
            "ocf": [p["metrics"]["ocf"] for p in parsed],
            "current_ratio": [p["metrics"]["current_ratio"] for p in parsed],
            "asset_turnover": [p["metrics"]["asset_turnover"] for p in parsed],
            "cashflow_stack": {
                "operating": [p["cashflow"]["operating"] for p in parsed],
                "investing": [p["cashflow"]["investing"] for p in parsed],
                "financing": [p["cashflow"]["financing"] for p in parsed],
            },
        },
        "dupont": dupont,
        "alerts": alerts,
        "report_text": report_text,
    }


def _dupont(latest: dict[str, Any]) -> dict[str, Any]:
    """杜邦分析：ROE = 净利率 × 总资产周转率 × 权益乘数。缺任一因子则分解为 None。"""
    nm = latest.get("net_margin_pct")
    at = latest.get("asset_turnover")
    ta = latest.get("total_assets")
    te = latest.get("total_equity")
    em = _ratio(ta, te)
    return {
        "net_margin_pct": nm,
        "asset_turnover": at,
        "equity_multiplier": em,
        "roe_pct": latest.get("roe_pct"),
        "complete": None not in (nm, at, em),
    }


def _build_alerts(
    parsed: list[dict[str, Any]],
    latest: dict[str, Any],
    prev: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """异常预警规则引擎（确定性）。code 稳定，供前端聚合图标。"""
    alerts: list[dict[str, Any]] = []
    m = latest
    ta = m.get("total_assets")

    def add(code: str, level: str, text: str) -> None:
        alerts.append({"code": code, "level": level, "text": text})

    # 1) 经营现金流为负
    if m.get("ocf") is not None and m["ocf"] < 0:
        add("OCF_NEGATIVE", "bad", f"经营活动现金流为负（{m['ocf']:,.0f} 元），造血能力需关注")
    # 2) 利润含金量：经营现金流/净利润 < 0.5
    ocf_np = m.get("ocf_to_np")
    if ocf_np is not None and m.get("net_profit") and m["net_profit"] > 0 and ocf_np < OCF_NP_WARN_RATIO:
        add("LOW_OCF_QUALITY", "warn", f"经营现金流/净利润仅 {ocf_np}，利润含金量偏低")
    # 3) 商誉占比
    gw = m.get("goodwill")
    if gw is not None and ta and gw / ta > GOODWILL_WARN_RATIO:
        add("GOODWILL_RISK", "warn", f"商誉占总资产 {gw / ta * 100:.1f}%，减值风险需关注")
    # 4) 资产负债率
    if m.get("debt_ratio_pct") is not None and m["debt_ratio_pct"] > DEBT_RATIO_WARN * 100:
        add("HIGH_DEBT", "warn", f"资产负债率 {m['debt_ratio_pct']}%，杠杆偏高")
    # 5) 流动比率 < 1
    if m.get("current_ratio") is not None and m["current_ratio"] < CURRENT_RATIO_WARN:
        add("LOW_LIQUIDITY", "warn", f"流动比率 {m['current_ratio']} < 1，短期偿债压力")
    # 6) 毛利率大幅下滑
    if prev and m.get("gross_margin_pct") is not None and prev.get("gross_margin_pct") is not None:
        drop = prev["gross_margin_pct"] - m["gross_margin_pct"]
        if drop > GROSS_MARGIN_DROP_PCT:
            add("MARGIN_SLIP", "warn", f"毛利率较上期下滑 {drop:.1f} 个百分点")
    # 7) 应收异常：营收下滑但应收账款上升，或应收增速远超营收
    if prev:
        rev_yoy = m.get("revenue_yoy_pct")
        ar_cur, ar_prev = m.get("accounts_receivable"), prev.get("accounts_receivable")
        rev_cur, rev_prev = m.get("revenue"), prev.get("revenue")
        if ar_cur is not None and ar_prev is not None and rev_cur is not None and rev_prev is not None:
            ar_yoy = _yoy(ar_cur, ar_prev)
            if rev_cur < rev_prev and ar_cur > ar_prev:
                add("RECEIVABLE_ANOMALY", "warn", "营收下滑但应收账款上升，收入质量存疑")
            elif rev_yoy is not None and ar_yoy is not None and ar_yoy > rev_yoy + 30:
                add("RECEIVABLE_ANOMALY", "warn", f"应收账款增速（{ar_yoy}%）远超营收增速（{rev_yoy}%）")
    # 8) 存货高企
    if prev:
        inv_cur, inv_prev = m.get("inventory"), prev.get("inventory")
        rev_cur, rev_prev = m.get("revenue"), prev.get("revenue")
        if inv_cur is not None and inv_prev is not None and rev_cur is not None and rev_prev is not None and rev_prev != 0:
            inv_yoy = _yoy(inv_cur, inv_prev)
            rev_yoy = _yoy(rev_cur, rev_prev)
            if inv_yoy is not None and rev_yoy is not None and inv_yoy > 0 and rev_yoy < 0:
                add("INVENTORY_BUILDUP", "warn", "营收下滑而存货上升，存在滞销/积压风险")
            elif inv_yoy is not None and rev_yoy is not None and inv_yoy > rev_yoy * 2 and rev_yoy > 0:
                add("INVENTORY_BUILDUP", "warn", f"存货增速（{inv_yoy}%）显著快于营收增速（{rev_yoy}%）")

    order = {
        "OCF_NEGATIVE": 0,
        "LOW_OCF_QUALITY": 1,
        "HIGH_DEBT": 2,
        "LOW_LIQUIDITY": 3,
        "MARGIN_SLIP": 4,
        "RECEIVABLE_ANOMALY": 5,
        "INVENTORY_BUILDUP": 6,
        "GOODWILL_RISK": 7,
    }
    alerts.sort(key=lambda a: order.get(a["code"], 99))
    return alerts


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

"""入口分析：多期口径、同比、杜邦拆解、预警与报告文本组装。"""

from __future__ import annotations

from typing import Any

from .financial_statements_alerts import _build_alerts
from .financial_statements_metrics import _num, _ratio, _yoy, compute_period_metrics
from .financial_statements_report import _report_text


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

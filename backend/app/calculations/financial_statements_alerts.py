"""异常预警规则引擎：code 稳定，只依据指标与阈值。"""

from __future__ import annotations

from typing import Any

from .financial_statements_metrics import _yoy

GOODWILL_WARN_RATIO = 0.20
OCF_NP_WARN_RATIO = 0.50
DEBT_RATIO_WARN = 0.70
CURRENT_RATIO_WARN = 1.0
GROSS_MARGIN_DROP_PCT = 5.0


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

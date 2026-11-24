"""个人资产调优（4.19.0）：只输出可解释候选与风险，不代下单、不代还款。

输入全部来自仪表盘已算好的确定性口径：应急金、负债、集中度、现金流、
目标配置与再平衡。这里不引入新的收益预测，也不把候选写成“建议买入”。
"""

from __future__ import annotations

from typing import Any

from ._shared import pick_lang as _t
from .strategy import compute_rebalance

_KIND_ORDER = {"debt": 0, "liquidity": 1, "concentration": 2, "rebalance": 3, "savings": 4}
_URGENT = 10
_HIGH = 20
_MEDIUM = 30
_LOW = 40


def _money(v: float) -> str:
    return f"{v / 10000:.1f}万" if abs(v) >= 10000 else f"{v:.0f}"


def _candidate(
    kind: str,
    priority: int,
    title: str,
    detail: str,
    impact: str,
    risk: str,
    *,
    amount: float = 0.0,
    symbol: str = "",
    action_tab: str = "overview",
    confidence: str = "high",
) -> dict[str, Any]:
    return {
        "kind": kind,
        "priority": priority,
        "title": title,
        "detail": detail,
        "impact": impact,
        "risk": risk,
        "amount": round(float(amount or 0), 2),
        "symbol": symbol,
        "action_tab": action_tab,
        "confidence": confidence,
        "requires_confirmation": True,
    }


def build_asset_tune(
    *,
    positions: list[dict[str, Any]] | None = None,
    targets: list[dict[str, Any]] | None = None,
    emergency: dict[str, Any] | None = None,
    debts: list[dict[str, Any]] | None = None,
    cashflow: dict[str, Any] | None = None,
    concentration: dict[str, Any] | None = None,
    lang: str = "zh",
    band_pct: float = 5.0,
) -> dict[str, Any]:
    """返回调优候选。缺数据的维度直接跳过，不用默认值编造。"""
    rows = [p for p in (positions or []) if isinstance(p, dict)]
    em = emergency or {}
    flow = cashflow or {}
    conc = concentration or {}
    items: list[dict[str, Any]] = []

    # 1. 应急金缺口：先保流动性，再谈收益。
    try:
        months = float(em.get("months_covered") or 0)
        target_months = float(em.get("target_months") or 0)
        essential = float(em.get("essential_monthly") or 0)
    except (TypeError, ValueError):
        months = target_months = essential = 0.0
    if em.get("has_data") and essential > 0 and target_months > 0 and months < target_months:
        gap = (target_months - months) * essential
        items.append(_candidate(
            "liquidity", _URGENT,
            _t(lang, "应急金不足 %.1f 个月", "Emergency buffer short by %.1f months") % months,
            _t(lang, "现金可覆盖 %.1f 个月必要支出，目标 %.0f 个月；缺口约 %s。",
               "Cash covers %.1f months of essentials vs target %.0f; gap about %s.")
            % (months, target_months, _money(gap)),
            _t(lang, "补足后不会因突发支出被迫卖出资产",
               "A full buffer avoids forced asset sales"),
            _t(lang, "现金被锁定，短期收益可能下降", "Cash drag may lower short-term yield"),
            amount=gap, action_tab="holdings",
        ))

    # 2. 高息负债：按利率从高到低列，金额取余额，不假设用哪笔现金还。
    high = sorted(
        [d for d in (debts or []) if isinstance(d, dict) and float(d.get("rate") or 0) >= 8],
        key=lambda d: (-float(d.get("rate") or 0), str(d.get("name") or "")),
    )
    for d in high:
        name = str(d.get("name") or "").strip()
        try:
            balance = float(d.get("balance") or 0)
            rate = float(d.get("rate") or 0)
        except (TypeError, ValueError):
            continue
        if not name or balance <= 0:
            continue
        annual = balance * rate / 100
        items.append(_candidate(
            "debt", _URGENT,
            _t(lang, "高息负债：%s", "High-interest debt: %s") % name,
            _t(lang, "余额 %s，年利率 %.1f%%，年化利息约 %s。",
               "Balance %s at %.1f%%, about %s interest per year.")
            % (_money(balance), rate, _money(annual)),
            _t(lang, "每还 1 万元每年少付约 %.0f 元利息", "Each 10k repaid saves about %.0f per year")
            % (rate * 100),
            _t(lang, "一次性还款会占用现金，需先留足应急金",
               "Lump-sum repayment uses cash; keep the buffer first"),
            amount=balance, action_tab="overview",
        ))

    # 3. 集中度：给“降到阈值”的金额，不给具体标的买卖指令。
    non_cash = sum(float(p.get("market_value") or 0) for p in rows if str(p.get("kind")) != "现金")
    threshold = float(conc.get("threshold_pct") or 40)
    for b in conc.get("asset_breaches") or []:
        if not isinstance(b, dict):
            continue
        name = str(b.get("name") or "").strip()
        pct = float(b.get("investable_pct") or 0)
        mv = float(b.get("market_value") or 0)
        if not name or non_cash <= 0 or pct <= threshold:
            continue
        excess = mv - non_cash * threshold / 100
        items.append(_candidate(
            "concentration", _URGENT,
            _t(lang, "单一持仓超限：%s", "Single holding over limit: %s") % name,
            _t(lang, "占可投资资产 %.1f%%，阈值 %.0f%%；降至阈值约需减少 %s。",
               "%.1f%% of investable assets vs %.0f%% cap; about %s to trim.")
            % (pct, threshold, _money(excess)),
            _t(lang, "降低单一标的波动对整体的冲击", "Reduces one name's impact on the whole"),
            _t(lang, "集中持仓也可能继续上涨，减仓会放弃部分上行",
               "Concentrated names can keep rising; trimming gives up some upside"),
            amount=excess, symbol=name, action_tab="holdings",
        ))

    # 4. 目标配置漂移：复用 compute_rebalance，保留其“未设目标不计算”的边界。
    plan = compute_rebalance(
        [{"symbol": p.get("symbol"), "name": p.get("name"), "kind": p.get("kind"),
          "shares": p.get("shares"), "last": p.get("last")} for p in rows],
        targets or [],
        band_pct=band_pct,
    )
    for item in plan.items:
        if item.action == "hold":
            continue
        try:
            amount = abs(float(item.amount or 0))
            current = float(item.current_pct or 0)
            target = float(item.target_pct or 0)
        except (TypeError, ValueError):
            continue
        if amount < 500:
            continue
        verb = _t(lang, "买入", "Buy") if item.action == "buy" else _t(lang, "卖出", "Sell")
        items.append(_candidate(
            "rebalance", _HIGH,
            _t(lang, "配置漂移：%s %s", "Allocation drift: %s %s") % (verb, item.name or item.symbol),
            _t(lang, "当前 %.1f%% → 目标 %.1f%%，偏离容忍带；金额约 %s。",
               "Current %.1f%% vs target %.1f%%, outside the band; about %s.")
            % (current, target, _money(amount)),
            _t(lang, "回到目标权重，降低组合漂移", "Returns to target weights and reduces drift"),
            _t(lang, "交易成本与滑点会侵蚀收益；不承诺跑赢原配置",
               "Costs and slippage can erode gains; no promise of outperformance"),
            amount=amount, symbol=str(item.symbol or ""), action_tab="strategy",
        ))

    # 5. 储蓄率：只给“每月多存多少”的口径。
    try:
        income = float(flow.get("income") or 0)
        rate = float(flow.get("savings_rate") or 0)
    except (TypeError, ValueError):
        income = rate = 0.0
    if income > 0 and rate < 20:
        need = income * (20 - rate) / 100
        items.append(_candidate(
            "savings", _MEDIUM,
            _t(lang, "储蓄率 %.1f%%，低于 20%%", "Savings rate %.1f%%, below 20%%") % rate,
            _t(lang, "本月收入 %s，储蓄率 %.1f%%；每月多存约 %s 可达 20%%。",
               "Income %s, savings rate %.1f%%; about %s more per month reaches 20%%.")
            % (_money(income), rate, _money(need)),
            _t(lang, "提高储蓄率是增强韧性最快的方式", "The fastest way to build resilience"),
            _t(lang, "压缩消费可能影响生活质量，需要用户自己权衡",
               "Cutting spending may hurt quality of life; the trade-off is yours"),
            amount=need, action_tab="overview", confidence="medium",
        ))

    items.sort(key=lambda x: (x["priority"], _KIND_ORDER.get(x["kind"], 99), x["title"]))
    return {
        "candidates": items,
        "count": len(items),
        "metrics": {
            "emergency_months": round(months, 1),
            "emergency_target_months": round(target_months, 1),
            "non_cash_value": round(non_cash, 2),
            "high_rate_debts": len(high),
            "rebalance_needed": bool(plan.needs_rebalance),
            "rebalance_max_drift_pct": plan.max_drift_pct,
            "rebalance_notes": list(plan.notes),
        },
        "boundary": (
            _t(lang,
               "这里只给确定性候选与风险，不代下单、不代还款、不预测收益；"
               "每笔动作都需用户确认，且不构成投资建议。",
               "Deterministic candidates and risks only; no orders, payments or return forecasts. "
               "Every action needs user confirmation and is not investment advice.")
        ),
    }


__all__ = ["build_asset_tune"]

"""组合分析与计划类工具（从 tools.py 拆出）：风险指标、再平衡、估值分位、定投、FIRE。

这几个都是「基于现有持仓/流水做确定性推算」，模型只挑工具，数字仍来自本地计算。
"""

from __future__ import annotations

import json
from typing import Any

from . import db

_BENCHMARK_NAMES = {"sh000300": "沪深300", "sh000001": "上证指数", "sz399001": "深证成指", "sz399006": "创业板指"}

async def tool_get_portfolio_risk(args: dict[str, Any]) -> str:
    """组合风险指标：波动率/夏普/索提诺/最大回撤/Beta/Alpha/与基准对比。"""
    from .calculations import build_equity_curve, compute_risk_metrics
    from .quotes import index_kline, kline

    bench = str(args.get("benchmark") or "sh000300").strip() or "sh000300"
    if bench not in _BENCHMARK_NAMES:
        return f"不支持的基准 {bench}，可选：{'、'.join(_BENCHMARK_NAMES)}"
    positions = await db.list_positions()
    holdings = []
    cash = 0.0
    for p in positions:
        if str(p.get("kind") or "") == "现金":
            cash += float(p.get("shares", 0) or 0) * float(p.get("last", 0) or 0)
        else:
            holdings.append(
                {"symbol": str(p.get("symbol") or ""), "shares": float(p.get("shares", 0) or 0)}
            )
    if not holdings:
        return "当前没有非现金持仓，无法计算组合风险。"
    history: dict[str, list[dict[str, Any]]] = {}
    for h in holdings:
        k = await kline(h["symbol"], "daily", 750)
        if k and k.get("points"):
            history[h["symbol"]] = k["points"]
    curve = build_equity_curve(holdings, history, cash)
    if len(curve) < 20:
        return "行情历史不足（至少需要 20 个交易日），暂时算不出可靠的风险指标。"
    bi = await index_kline(bench, 750)
    bench_values = None
    if bi and bi.get("points"):
        bench_values = [float(p["close"]) for p in bi["points"] if p.get("close")]
        if len(bench_values) > len(curve):
            bench_values = bench_values[-len(curve) :]
    m = compute_risk_metrics(curve, bench_values)
    d = m.to_dict()
    d["benchmark_name"] = _BENCHMARK_NAMES.get(bench, bench)
    d["basis"] = "按当前持仓回溯的模拟净值，不是实盘历史成交净值"
    return json.dumps(d, ensure_ascii=False)
async def tool_get_rebalance_plan(args: dict[str, Any]) -> str:
    """再平衡：目标配置偏离度 + 建议买入/卖出金额与股数。"""
    from .calculations import compute_rebalance

    try:
        band = float(args.get("band_pct") or 5.0)
    except (TypeError, ValueError):
        band = 5.0
    positions = await db.list_positions()
    targets = await db.list_allocation_targets()
    if not targets:
        return (
            "还没有设置目标配置，无法给出再平衡建议。"
            "请先在「持仓 → 目标配置」里设置各标的的目标权重（合计 100%）。"
        )
    plan = compute_rebalance(positions, targets, band)
    return json.dumps(plan.to_dict(), ensure_ascii=False)
async def tool_get_valuation(args: dict[str, Any]) -> str:
    """估值位置分位：当前价在近期区间中的位置（0=最低，100=最高）。"""
    from .calculations import compute_valuation
    from .quotes import kline

    raw = str(args.get("symbols") or "").strip()
    wanted = [s.strip() for s in raw.split(",") if s.strip()]
    positions = await db.list_positions()
    chosen = []
    for p in positions:
        sym = str(p.get("symbol") or "")
        if not sym or str(p.get("kind") or "") == "现金":
            continue
        if wanted and sym not in wanted:
            continue
        chosen.append(p)
    if not chosen:
        return "没有可评估的持仓（目标标的为空或不在持仓中）。"
    out = []
    for p in chosen:
        k = await kline(str(p.get("symbol")), "daily", 750)
        if not k:
            continue
        closes = [float(pt["close"]) for pt in (k.get("points") or []) if pt.get("close")]
        v = compute_valuation(str(p.get("symbol")), str(p.get("name") or ""), closes, 750)
        if v:
            out.append(v.to_dict())
    if not out:
        return "行情不可用，暂时算不出估值分位。"
    out.sort(key=lambda x: x["percentile"])
    return json.dumps(
        {
            "items": out,
            "note": "位置分位 = 当前价在近 750 个交易日区间中的位置；只描述贵不贵，不预测涨跌",
        },
        ensure_ascii=False,
    )
async def tool_get_dca_plans(_args: dict[str, Any]) -> str:
    """定投计划：每期金额、累计投入、成本线、当前盈亏、下一期日期。"""
    from .calculations import compute_dca_stats, next_run_date
    from .quotes import kline, quote_now

    plans = await db.list_dca_plans()
    if not plans:
        return "还没有定投计划。可以说「每月 10 号定投 3000 沪深300」来创建。"
    out = []
    for plan in plans:
        sym = str(plan.get("symbol") or "")
        k = await kline(sym, "daily", 750)
        closes = [
            {"date": p.get("date"), "close": p.get("close")}
            for p in ((k or {}).get("points") or [])
            if p.get("close")
        ]
        px = None
        if not closes:
            q = await quote_now(sym)
            px = (q or {}).get("price")
        stats = compute_dca_stats(plan, closes, float(px) if px else None)
        try:
            nxt = next_run_date(int(plan.get("day", 1) or 1), str(plan.get("frequency") or "monthly"))
            nxt_s = nxt.isoformat()
        except (ValueError, TypeError):
            nxt_s = None
        out.append({**plan, "stats": stats, "next_run": nxt_s})
    return json.dumps({"items": out}, ensure_ascii=False)
async def tool_get_fire_plan(_args: dict[str, Any]) -> str:
    """FIRE 进度：目标本金、储蓄率、预计达成年限。"""
    from datetime import date as _date

    from .calculations import compute_fire

    txns = await db.list_transactions()
    month_prefix = _date.today().strftime("%Y-%m")
    monthly = [t for t in txns if str(t.get("date", "")).startswith(month_prefix)]
    income = sum(float(t.get("amount", 0)) for t in monthly if float(t.get("amount", 0)) > 0)
    expense = -sum(float(t.get("amount", 0)) for t in monthly if float(t.get("amount", 0)) < 0)
    positions = await db.list_positions()
    debts = await db.list_debts()
    net = sum(float(p.get("shares", 0) or 0) * float(p.get("last", 0) or 0) for p in positions) - sum(
        float(d.get("balance", 0) or 0) for d in debts
    )
    if income <= 0 and expense <= 0:
        return "账本里还没有本月收支记录，无法估算 FIRE 进度。"
    sr = None if income <= 0 else (income - expense) / income * 100
    return json.dumps(compute_fire(expense, income, sr, net), ensure_ascii=False)

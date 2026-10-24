"""投资策略路由：风险指标 / 再平衡 / 估值温度计 / 定投计划 / FIRE。

数值一律由 calculations 包确定性计算；本层只做取数与组装。
所有端点都允许在行情不可用时降级（返回 available=false 与原因），
绝不因为外部行情失败返回 500。
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import analysis, db, quotes
from ..auth import get_current_user
from ..calculations import (
    build_equity_curve,
    compute_dca_stats,
    compute_fire,
    compute_rebalance,
    compute_risk_metrics,
    compute_valuation,
    next_run_date,
)

router = APIRouter(dependencies=[Depends(get_current_user)])

BENCHMARKS = {
    "sh000300": "沪深300",
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sz399006": "创业板指",
}


async def _holdings_for_curve(limit: int = 750) -> tuple[list[dict[str, Any]], float, dict[str, Any]]:
    """取非现金持仓 + 各自日线，返回 (holdings, cash, 行情诊断)。"""
    positions = await db.list_positions()
    cash = 0.0
    holdings: list[dict[str, Any]] = []
    for p in positions:
        if str(p.get("kind") or "") == "现金":
            cash += float(p.get("shares", 0) or 0) * float(p.get("last", 0) or 0)
            continue
        holdings.append(
            {
                "symbol": str(p.get("symbol") or ""),
                "name": str(p.get("name") or ""),
                "shares": float(p.get("shares", 0) or 0),
                "last": float(p.get("last", 0) or 0),
            }
        )
    diagnostics: dict[str, Any] = {"requested": len(holdings), "resolved": 0, "missing": []}
    price_history: dict[str, list[dict[str, Any]]] = {}
    if holdings:
        results = await asyncio.gather(
            *(quotes.kline(h["symbol"], "daily", limit) for h in holdings),
            return_exceptions=True,
        )
        for h, res in zip(holdings, results, strict=False):
            if isinstance(res, Exception) or not res:
                diagnostics["missing"].append(h["name"] or h["symbol"])
                continue
            pts = res.get("points") or []
            if len(pts) >= 2:
                price_history[h["symbol"]] = pts
                diagnostics["resolved"] += 1
            else:
                diagnostics["missing"].append(h["name"] or h["symbol"])
    return holdings, cash, {"price_history": price_history, "diagnostics": diagnostics}


@router.get("/api/strategy/risk")
async def strategy_risk(
    benchmark: str = Query(default="sh000300"),
    days: int = Query(default=750, ge=60, le=1000),
) -> dict[str, Any]:
    """组合风险指标 + 净值曲线 + 基准对比。

    明确口径：曲线是按**当前持仓回溯**的模拟净值，不是实盘历史成交净值。
    响应里的 `basis` 字段把这件事写进数据，前端必须展示。
    """
    if benchmark not in BENCHMARKS:
        raise HTTPException(400, f"不支持的基准：{benchmark}")
    holdings, cash, packed = await _holdings_for_curve(days)
    price_history = packed["price_history"]
    diag = packed["diagnostics"]

    if not holdings:
        return {
            "available": False,
            "reason": "没有非现金持仓，无法计算组合风险",
            "basis": "backtest",
            "benchmark": benchmark,
            "benchmark_name": BENCHMARKS[benchmark],
        }

    curve = build_equity_curve(holdings, price_history, cash)
    if len(curve) < 20:
        return {
            "available": False,
            "reason": "行情历史不足（至少需要 20 个交易日），请稍后重试或检查网络",
            "basis": "backtest",
            "benchmark": benchmark,
            "benchmark_name": BENCHMARKS[benchmark],
            "diagnostics": diag,
        }

    bench = await quotes.index_kline(benchmark, days)
    bench_values: list[float] | None = None
    if bench:
        pts = bench.get("points") or []
        bench_values = [float(p["close"]) for p in pts if p.get("close")]
        # 对齐长度：以组合曲线为准，取基准最后 N 个点
        if len(bench_values) > len(curve):
            bench_values = bench_values[-len(curve) :]

    metrics = compute_risk_metrics(curve, bench_values)
    return {
        "available": True,
        "basis": "backtest",
        "basis_note": "按当前持仓回溯的模拟净值，不是实盘历史成交净值",
        "benchmark": benchmark,
        "benchmark_name": BENCHMARKS[benchmark],
        "equity_curve": [round(v, 2) for v in curve],
        "benchmark_curve": [round(v, 2) for v in bench_values] if bench_values else None,
        "metrics": metrics.to_dict(),
        "diagnostics": diag,
        "generated_at": date.today().isoformat(),
    }


@router.get("/api/strategy/allocation")
async def strategy_allocation(band: float = Query(default=5.0, ge=1.0, le=20.0)) -> dict[str, Any]:
    """目标配置 + 当前漂移 + 调仓清单。"""
    positions = await db.list_positions()
    targets = await db.list_allocation_targets()
    plan = compute_rebalance(positions, targets, band)
    return {
        "available": bool(targets),
        "targets": targets,
        "plan": plan.to_dict(),
        "band_pct": band,
    }


@router.put("/api/strategy/allocation")
async def strategy_allocation_save(payload: dict[str, Any]) -> dict[str, Any]:
    targets = payload.get("targets")
    if not isinstance(targets, list):
        raise HTTPException(400, "targets 必须是数组")
    saved = await db.replace_allocation_targets(targets)
    analysis.invalidate_dashboard_cache()
    total = round(sum(float(t.get("target_pct", 0)) for t in saved), 2)
    return {
        "ok": True,
        "targets": saved,
        "total_pct": total,
        "warning": None if abs(total - 100) < 0.01 else f"目标合计 {total}%，建议调整为 100%",
    }


@router.get("/api/strategy/valuation")
async def strategy_valuation(
    symbols: str = Query(default="", description="逗号分隔，留空=全部非现金持仓"),
    days: int = Query(default=750, ge=60, le=1000),
) -> dict[str, Any]:
    """估值位置分位：当前价在近 N 个交易日区间中的位置。"""
    positions = await db.list_positions()
    wanted = [s.strip() for s in symbols.split(",") if s.strip()]
    chosen = []
    for p in positions:
        sym = str(p.get("symbol") or "")
        if not sym or str(p.get("kind") or "") == "现金":
            continue
        if wanted and sym not in wanted:
            continue
        chosen.append(p)
    if not chosen and not wanted:
        return {"available": False, "reason": "没有可评估的持仓", "items": [], "lookback_days": days}

    async def one(p: dict[str, Any]) -> dict[str, Any] | None:
        k = await quotes.kline(str(p.get("symbol")), "daily", days)
        if not k:
            return None
        closes = [float(pt["close"]) for pt in (k.get("points") or []) if pt.get("close")]
        v = compute_valuation(str(p.get("symbol")), str(p.get("name") or ""), closes, days)
        if not v:
            return None
        d = v.to_dict()
        d["shares"] = float(p.get("shares", 0) or 0)
        d["market_value"] = round(float(p.get("shares", 0) or 0) * v.current, 2)
        return d

    items = await asyncio.gather(*(one(p) for p in chosen))
    out = [i for i in items if i]
    out.sort(key=lambda i: i["percentile"])
    return {
        "available": bool(out),
        "reason": None if out else "行情不可用，稍后重试",
        "lookback_days": days,
        "items": out,
        "zones": [
            {"key": "cheap", "label": "低位区", "max": 20},
            {"key": "low", "label": "偏低", "max": 40},
            {"key": "fair", "label": "中枢", "max": 60},
            {"key": "high", "label": "偏高", "max": 80},
            {"key": "expensive", "label": "高位区", "max": 100},
        ],
    }


@router.get("/api/strategy/dca")
async def strategy_dca_list() -> dict[str, Any]:
    """定投计划列表 + 每条的实盘回测（累计投入/份额/成本线/盈亏）。"""
    plans = await db.list_dca_plans()
    if not plans:
        return {"items": [], "available": False}

    async def enrich(plan: dict[str, Any]) -> dict[str, Any]:
        sym = str(plan.get("symbol") or "")
        k = await quotes.kline(sym, "daily", 750)
        q = await quotes.quote_now(sym) if not k else None
        pts = (k or {}).get("points") or []
        closes = [{"date": p.get("date"), "close": p.get("close")} for p in pts if p.get("close")]
        px_now = (q or {}).get("price")
        stats = compute_dca_stats(plan, closes, float(px_now) if px_now else None)
        try:
            nxt = next_run_date(int(plan.get("day", 1) or 1), str(plan.get("frequency") or "monthly"))
        except (ValueError, TypeError):
            nxt = None
        return {
            **plan,
            "stats": stats,
            "next_run": nxt.isoformat() if nxt else None,
            "quote_available": bool(closes),
        }

    items = await asyncio.gather(*(enrich(p) for p in plans))
    return {"items": list(items), "available": True}


@router.post("/api/strategy/dca")
async def strategy_dca_save(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        plan = await db.upsert_dca_plan(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "plan": plan}


@router.delete("/api/strategy/dca/{plan_id}")
async def strategy_dca_delete(plan_id: str) -> dict[str, Any]:
    ok = await db.delete_dca_plan(plan_id)
    if not ok:
        raise HTTPException(404, "定投计划不存在")
    return {"ok": True}


@router.get("/api/strategy/fire")
async def strategy_fire(
    withdrawal_rate: float = Query(default=4.0, ge=0.5, le=10.0),
    expected_return: float = Query(default=5.0, ge=-10.0, le=30.0),
) -> dict[str, Any]:
    """FIRE 计算：目标本金、储蓄率、预计年限。数据来自账本与净值。"""
    txns = await db.list_transactions()
    month_prefix = date.today().strftime("%Y-%m")
    monthly = [t for t in txns if str(t.get("date", "")).startswith(month_prefix)]
    income = sum(float(t.get("amount", 0)) for t in monthly if float(t.get("amount", 0)) > 0)
    expense = -sum(float(t.get("amount", 0)) for t in monthly if float(t.get("amount", 0)) < 0)
    # 本月样本不足时回退到近 3 个月月均，避免月初 FIRE 数字剧烈跳动
    if income <= 0 or expense <= 0:
        recent = [t for t in txns if str(t.get("date", ""))[:7] >= _months_ago(3)]
        months = {str(t.get("date", ""))[:7] for t in recent if t.get("date")}
        n = max(1, len(months))
        income = sum(float(t.get("amount", 0)) for t in recent if float(t.get("amount", 0)) > 0) / n
        expense = -sum(float(t.get("amount", 0)) for t in recent if float(t.get("amount", 0)) < 0) / n

    positions = await db.list_positions()
    debts = await db.list_debts()
    net = sum(float(p.get("shares", 0) or 0) * float(p.get("last", 0) or 0) for p in positions) - sum(
        float(d.get("balance", 0) or 0) for d in debts
    )
    sr = None if income <= 0 else (income - expense) / income * 100
    result = compute_fire(expense, income, sr, net, expected_return, withdrawal_rate)
    return {"available": income > 0 or expense > 0, "monthly_income": round(income, 2), "monthly_expense": round(expense, 2), **result}


def _months_ago(n: int) -> str:
    today = date.today()
    y, m = today.year, today.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y:04d}-{m:02d}-01"

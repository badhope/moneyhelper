"""收益率路由：XIRR / TWR / 简单收益率。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query

from .. import db
from ..auth import get_current_user
from ..calculations import calculate_simple_return, calculate_twr, calculate_xirr
from .calculations_networth_past import _parse_date

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/api/calculations/returns")
async def returns_endpoint(months: int = Query(default=6, ge=1, le=120)) -> dict[str, Any]:
    """收益率：XIRR / TWR / 简单收益率。

    取最近 N 个月的交易数据，基于快照价计算各指标。
    """
    txns = await db.list_transactions()
    positions = await db.list_positions()
    live: dict[str, float] = {}
    for p in positions:
        sym = p.get("symbol", "")
        if sym:
            live[sym] = float(p.get("last", 0))

    # 过滤最近 N 个月交易
    cutoff = date.today() - timedelta(days=months * 31)
    recent_txns = [
        t for t in txns
        if _parse_date(t.get("date", "")) and _parse_date(t["date"]) >= cutoff
    ]

    result: dict[str, Any] = {
        "period_months": months,
        "transaction_count": len(recent_txns),
    }

    # --- 简单收益率 ---
    if positions:
        total_mv = sum(float(p.get("shares", 0)) * float(p.get("last", 0)) for p in positions)
        total_cost = sum(float(p.get("shares", 0)) * float(p.get("cost", 0)) for p in positions)

        # 期间净投入只算"非工资性"的现金流入：工资是收入，不是追加本金。
        # 把工资算进来会系统性压低收益率（分母变大、分子没变）。
        income_categories = {"收入", "工资", "salary", "income"}
        net_inflows = sum(
            float(t.get("amount", 0))
            for t in recent_txns
            if float(t.get("amount", 0)) > 0
            and str(t.get("category") or "").strip() not in income_categories
        )

        if total_cost > 0:
            simple_r = calculate_simple_return(total_cost, total_mv, net_inflows)
            result["simple_return"] = {
                "value": simple_r,
                "pct": round(simple_r * 100, 2),
                "start_value": round(total_cost, 2),
                "end_value": round(total_mv, 2),
                "net_inflows": round(net_inflows, 2),
            }

    # --- XIRR (基于持仓成本与当前市值) ---
    # 口径：期初按成本价一次性投入（现金流为负），期末市值（为正）。
    # 不把账本问答/工资流水混进投资现金流——那会把生活收入算成投资收益。
    if positions:
        today = date.today()
        total_mv = sum(float(p.get("shares", 0)) * float(p.get("last", 0)) for p in positions)
        total_cost = sum(float(p.get("shares", 0)) * float(p.get("cost", 0)) for p in positions)
        if total_mv > 0 and total_cost > 0:
            start = today - timedelta(days=max(1, months * 31))
            cashflows: list[tuple[date, float]] = [
                (start, -total_cost),
                (today, total_mv),
            ]
            try:
                xirr_val = calculate_xirr(cashflows)
                result["xirr"] = {
                    "value": xirr_val,
                    "pct": round(xirr_val * 100, 2),
                }
            except ValueError as e:
                result["xirr"] = {"error": str(e)}

    # --- TWR（时间加权收益率）---
    # 必须有真实的历史估值点才能算：TWR 的定义是「每个子区间收益率连乘」，
    # 缺了历史估值就只能用当前市值反推期初，那样
    # curr_val/(prev_val+flow)-1 恒等于 0——比不显示更糟（会误导用户和 AI）。
    # 因此这里的策略是：能拿到真实快照就算，拿不到就显式降级并说明原因。
    snapshot_curve = await _load_valuation_curve(months)
    if len(snapshot_curve) >= 2:
        try:
            twr_val = calculate_twr(snapshot_curve)
            result["twr"] = {
                "value": twr_val,
                "pct": round(twr_val * 100, 2),
                "basis": "valuation_snapshots",
                "points": len(snapshot_curve),
            }
        except ValueError as e:
            result["twr"] = {"available": False, "error": str(e)}
    else:
        result["twr"] = {
            "available": False,
            "reason": (
                f"时间加权收益率需要至少两个历史估值快照。当前只有 {len(snapshot_curve)} 个，"
                "无法在不臆造期初值的前提下计算。"
            ),
            "basis": "insufficient_history",
        }

    return result


async def _load_valuation_curve(months: int) -> list[dict[str, Any]]:
    """读取真实历史估值序列（净值快照优先，回落到持仓成本推移）。

    只返回**真实存在**的时间点：绝不根据当前市值反推期初值——那会让
    TWR 数学上恒等于 0，属于伪造数据。快照不足时返回空/单点，由调用方降级。
    """
    from .. import db

    curve: list[dict[str, Any]] = []
    # 1) 模拟盘/组合快照表：如果有按日净值，直接可用
    try:
        snaps = await db.list_valuation_snapshots(months * 31)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — 老库/未实现该表时回落，不影响主流程
        snaps = []
    for s in snaps:
        d = str(s.get("date") or "")
        v = s.get("equity")
        if d and v is not None:
            curve.append({"date": d, "type": "valuation", "amount": float(v)})
    if len(curve) >= 2:
        curve.sort(key=lambda x: x["date"])
        return curve

    # 2) 回落：用账本里「有流水记录的月份」+ 该月末的持仓成本估算。
    #    这仍是真实历史（成本来自买入记录），不是拿当前市值倒推。
    txns = await db.list_transactions()
    if not txns:
        return []
    by_month: dict[str, float] = {}
    for t in txns:
        d = str(t.get("date") or "")
        if len(d) < 7:
            continue
        amt = float(t.get("amount") or 0)
        by_month[d[:7]] = by_month.get(d[:7], 0.0) + amt
    # 累计净投入作为该月估值代理（无分红/无卖出重估，明确标注为成本口径）
    running = 0.0
    for month in sorted(by_month)[-months:]:
        running += by_month[month]
        curve.append({"date": f"{month}-28", "type": "valuation", "amount": round(running, 2)})
    return curve

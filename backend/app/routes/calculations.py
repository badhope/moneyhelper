"""金融计算引擎路由：净值 / 收益率 / 健康评分 / 目标进度。

所有数值计算由 calculations 包完成（纯确定性），本层只负责 I/O 拉取与结果包装。
LLM 不介入任何数字，仅负责解读。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query

from .. import db
from ..auth import get_current_user
from ..calculations import (
    calculate_goal_progress,
    calculate_net_worth,
    calculate_simple_return,
    calculate_twr,
    calculate_xirr,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


# --------------------------------------------------------------------------
# GET /api/calculations/net-worth
# --------------------------------------------------------------------------

@router.get("/api/calculations/net-worth")
async def net_worth_endpoint() -> dict[str, Any]:
    """当前净值 + 组成明细。

    净值必须与总览用同一份价格：原来这里直接读 positions[].last（快照价），
    而 /api/dashboard 用实时行情，同一屏出现「总资产 282,540」与「264,884」两个数。
    现在先取实时价（失败自动退回快照），两处口径一致。
    """
    from .. import quotes

    positions = await db.list_positions()
    debts = await db.list_debts()
    subs = await db.list_subscriptions()

    try:
        live = await quotes.live_quotes(positions)
    except Exception:  # noqa: BLE001 — 行情失败退回快照价，接口不能因此 500
        live = {}
    priced = [
        {**p, "last": float(live.get(p["symbol"], p.get("last", 0)))}
        for p in positions
    ]
    snapshot = calculate_net_worth(priced, debts=debts, subscriptions=subs)

    # 负债利率附加字段：前端负债明细展示用，键与 liability_breakdown 一致
    liability_rates = {
        (d.get("name") or "未知负债"): float(d.get("rate", 0) or 0) for d in debts
    }

    return {
        "date": snapshot.date.isoformat(),
        "total_assets": snapshot.total_assets,
        "total_liabilities": snapshot.total_liabilities,
        "net_worth": snapshot.net_worth,
        "asset_breakdown": snapshot.asset_breakdown,
        "liability_breakdown": snapshot.liability_breakdown,
        "liability_rates": liability_rates,
        "quote_source": quotes.last_source(),
    }


# --------------------------------------------------------------------------
# GET /api/calculations/returns?months=6
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# GET /api/calculations/health
# --------------------------------------------------------------------------

@router.get("/api/calculations/health")
async def health_endpoint() -> dict[str, Any]:
    """财务健康评分（0-100 分 + 等级 + 五维明细）。

    与 /api/health-check、体检页、呈批件共用 analysis.health_check 同一实现。
    历史缺陷：这里曾用 calculations.calculate_health_score 的连续打分，
    与 analysis 侧的定性折算各算一遍，同一份数据总览显示 51、体检页显示 50，
    用户会以为其中一个是 bug。现在只保留一条口径。
    """
    from .. import analysis, quotes

    dashboard = await analysis.collect_dashboard(lang="zh")
    positions = await db.list_positions()
    settings = await db.get_settings()
    debts = await db.list_debts()
    subs = await db.list_subscriptions()
    txns = await db.list_transactions()
    # 必须用实时行情，不能用 positions[].last 快照价：否则健康卡里的"总市值"
    # 与同屏总资产差十几万（282,540 vs 264,884），看起来像算错了。
    try:
        live = await quotes.live_quotes(positions)
    except Exception:  # noqa: BLE001 — 行情失败退回快照，健康分仍可给
        live = {p["symbol"]: float(p.get("last", 0)) for p in positions}
    market = analysis.market_view(positions, live)
    ledger = analysis.ledger_view(txns, subs, debts, settings, positions, live)
    flags = analysis.risk_checks(market, ledger, "zh")
    report = analysis.health_check(market, ledger, flags, await db.list_goals(), "zh")

    dimensions = report.get("dimensions") or []
    breakdown = {
        d["key"]: {
            "score": {"good": 20, "warn": 10, "bad": 0}.get(d.get("status"), 0),
            "max": int(d.get("max") or 20),
            "label": d.get("title", d["key"]),
            "detail": d.get("detail", ""),
        }
        for d in dimensions
    }
    return {
        "score": report.get("score", 0),
        "grade": report.get("grade", "-"),
        "breakdown": breakdown,
        "summary": report.get("summary", ""),
        "dimensions": dimensions,
        "source": dashboard.get("source", {}),
    }


# --------------------------------------------------------------------------
# GET /api/calculations/goals/progress
# --------------------------------------------------------------------------

@router.get("/api/calculations/goals/progress")
async def goals_progress_endpoint() -> dict[str, Any]:
    """目标进度列表，含确定性 on_track 判断。"""
    goals = await db.list_goals()
    positions = await db.list_positions()
    txns = await db.list_transactions()

    progress_list = calculate_goal_progress(goals, positions, txns)

    on_track_count = sum(1 for g in progress_list if g.on_track)
    off_track_count = len(progress_list) - on_track_count

    return {
        "total": len(progress_list),
        "on_track": on_track_count,
        "off_track": off_track_count,
        "goals": [
            {
                "name": g.name,
                "target_amount": g.target_amount,
                "current_amount": g.current_amount,
                "monthly_contribution": g.monthly_contribution,
                "months_remaining": g.months_remaining,
                "on_track": g.on_track,
                "required_monthly": g.required_monthly,
                "progress_pct": g.progress_pct,
            }
            for g in progress_list
        ],
    }


# --------------------------------------------------------------------------
# 辅助函数
# --------------------------------------------------------------------------

def _parse_date(val: str) -> date | None:
    """解析 YYYY-MM-DD 字符串为 date。"""
    if not val or len(str(val)) < 10:
        return None
    try:
        s = str(val)[:10]
        parts = s.split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return None




# --------------------------------------------------------------------------
# 净值序列与变动归因
# --------------------------------------------------------------------------


@router.get("/api/calculations/net-worth/history")
async def net_worth_history(days: int = 365) -> dict[str, Any]:
    """净资产序列（每日快照）。没有历史时返回 available=false 并说明原因。"""
    from .. import networth_series

    snaps = await networth_series.list_snapshots(days)
    return networth_series.series(snaps)


def _split_assets(data: dict[str, Any]) -> tuple[float, float]:
    """从净值接口的结果里拆出「现金」与「非现金市值」。

    asset_breakdown 是 {名称: 金额} 的字典，其中现金类目名包含「现金」。
    拆不出来时保守返回 (0, 总资产)——宁可把现金算进市值，也不要虚增总资产。
    """
    total = float(data.get("total_assets") or 0)
    breakdown = data.get("asset_breakdown")
    if not isinstance(breakdown, dict) or not breakdown:
        return 0.0, total
    cash = 0.0
    mv = 0.0
    for name, value in breakdown.items():
        try:
            v = float(value or 0)
        except (TypeError, ValueError):
            continue
        if "现金" in str(name) or "cash" in str(name).lower():
            cash += v
        else:
            mv += v
    return round(cash, 2), round(mv, 2)


@router.post("/api/calculations/net-worth/snapshot")
async def net_worth_snapshot() -> dict[str, Any]:
    """记录一条当日净值快照（幂等，同日覆盖）。"""
    from .. import networth_series

    data = await net_worth_endpoint()
    cash, mv = _split_assets(data)
    return await networth_series.save_snapshot(
        total_assets=float(data.get("total_assets") or 0),
        total_liabilities=float(data.get("total_liabilities") or 0),
        cash=cash,
        market_value=mv,
        source=str(data.get("quote_source") or "quotes"),
    )


@router.get("/api/calculations/net-worth/attribution")
async def net_worth_attribution(days: int = 31) -> dict[str, Any]:
    """区间净值变动归因：净储蓄 / 投资损益 / 负债变动 / 残差。"""
    from .. import db, networth_series

    snaps = await networth_series.list_snapshots(days + 1)
    if len(snaps) < 2:
        return {
            "available": False,
            "reason": "至少需要两天净值快照才能归因。明天再来看即可。",
        }
    start, end = snaps[0], snaps[-1]
    from ..db.tenant import current_user_id

    txs = await db.fetch_all(
        "SELECT date, amount FROM transactions WHERE user_id=? AND date>=? AND date<=?",
        (current_user_id(), start["date"], end["date"]),
    )
    net_inflow = round(sum(float(t["amount"] or 0) for t in txs), 2)
    out = networth_series.attribute(
        start_net_worth=float(start["net_worth"]),
        end_net_worth=float(end["net_worth"]),
        start_market_value=float(start.get("market_value") or 0),
        end_market_value=float(end.get("market_value") or 0),
        net_inflow=net_inflow,
        start_liabilities=float(start.get("total_liabilities") or 0),
        end_liabilities=float(end.get("total_liabilities") or 0),
    )
    out["start_date"] = start["date"]
    out["end_date"] = end["date"]
    out["net_inflow"] = net_inflow
    return out

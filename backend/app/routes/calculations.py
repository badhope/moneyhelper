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

    # --- TWR (构建 valuation 序列) ---
    # 按月构建估值点
    twr_txns = _build_twr_sequence(recent_txns, positions)
    if len(twr_txns) >= 2:
        try:
            twr_val = calculate_twr(twr_txns)
            result["twr"] = {
                "value": twr_val,
                "pct": round(twr_val * 100, 2),
            }
        except ValueError as e:
            result["twr"] = {"error": str(e)}

    return result


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


def _build_twr_sequence(
    transactions: list[dict[str, Any]],
    positions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """构建 TWR 所需的估值序列（按月聚合现金流 + 期末估值）。"""
    result: list[dict[str, Any]] = []

    # 计算每月净现金流
    monthly_flows: dict[str, float] = {}
    for t in transactions:
        d = str(t.get("date", ""))
        if len(d) >= 7:
            month = d[:7]
            monthly_flows[month] = monthly_flows.get(month, 0.0) + float(t.get("amount", 0))

    if not monthly_flows:
        return []

    # 按月份构建估值点（简化：使用最新持仓市值作为最新估值）
    total_mv = sum(float(p.get("shares", 0)) * float(p.get("last", 0)) for p in positions)
    sorted_months = sorted(monthly_flows.keys())

    for month in sorted_months:
        flow = monthly_flows[month]
        # 现金流作为 deposit/withdraw
        if flow > 0:
            result.append({"date": f"{month}-15", "type": "deposit", "amount": flow})
        elif flow < 0:
            result.append({"date": f"{month}-15", "type": "withdraw", "amount": -flow})

    # 最后一个估值点
    if total_mv > 0:
        today_str = date.today().strftime("%Y-%m-%d")
        result.append({"date": today_str, "type": "valuation", "amount": total_mv})

        # 添加期初估值（借用第一个月之前的市值）
        first_month = sorted_months[0]
        start_value = max(0.0, total_mv - sum(monthly_flows.values()))
        if start_value > 0:
            result.insert(0, {"date": f"{first_month}-01", "type": "valuation", "amount": start_value})

    return result

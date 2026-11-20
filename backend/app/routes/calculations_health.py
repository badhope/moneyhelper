"""健康评分与目标进度路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from .. import db
from ..auth import get_current_user
from ..calculations import calculate_goal_progress

router = APIRouter(dependencies=[Depends(get_current_user)])


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

"""定投计划：列表 / 保存 / 删除。"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .. import db, quotes
from ..auth import get_current_user
from ..calculations import (
    compute_dca_stats,
    next_run_date,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


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

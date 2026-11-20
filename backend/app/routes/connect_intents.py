"""交易意图与任务：意图 CRUD、paper 执行、实盘成交回填与拒绝。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..auth import get_current_user
from ..connect import service, store
from ..connect.catalog import get_connector
from ._responses import bad as _bad

router = APIRouter(dependencies=[Depends(get_current_user)])

# 交易意图
# ---------------------------------------------------------------------------


@router.get("/api/connect/intents")
async def intents(status: str = "", limit: int = 50) -> dict[str, Any]:
    return {"items": await store.list_intents(limit=limit, status=status)}


@router.post("/api/connect/intents")
async def create_intent(payload: dict[str, Any]) -> Any:
    try:
        return await store.create_intent(payload or {})
    except ValueError as exc:
        return _bad(str(exc))


@router.post("/api/connect/intents/{iid}/execute")
async def execute_intent(iid: str, payload: dict[str, Any] | None = None) -> Any:
    try:
        return await service.execute_trade_intent(iid, payload or {})
    except ValueError as exc:
        return _bad(str(exc))


@router.post("/api/connect/intents/{iid}/confirm")
async def confirm_intent(iid: str, payload: dict[str, Any]) -> Any:
    """实盘成交回填：记录实际成交价/数量，把意图标记为已执行。"""
    try:
        price = float((payload or {}).get("fill_price") or 0)
        shares = float((payload or {}).get("fill_shares") or 0)
    except (TypeError, ValueError):
        return _bad("成交价/数量必须是数字")
    if price <= 0 or shares <= 0:
        return _bad("成交价与数量必须大于 0")
    intent = await store.get_intent(iid)
    if intent is None:
        return _bad("交易意图不存在", 404)
    result = {**(intent.get("result") or {}), "fill_price": price, "fill_shares": shares, "confirmed_by_user": True}
    updated = await store.update_intent(iid, "executed", note="用户回填实盘成交", result=result)
    from ..provenance import record_provenance

    await record_provenance(
        action="connect_confirm_live_fill",
        entity_type="trade_intent",
        entity_id=iid,
        before={"status": intent["status"]},
        after={"status": "executed", "fill_price": price, "fill_shares": shares},
        source="connect",
    )
    return {"ok": True, "intent": updated}


@router.post("/api/connect/intents/{iid}/reject")
async def reject_intent(iid: str, payload: dict[str, Any] | None = None) -> Any:
    try:
        return await store.update_intent(
            iid, "rejected", note=str((payload or {}).get("reason") or "用户取消")
        )
    except ValueError as exc:
        return _bad(str(exc), 404)


@router.get("/api/connect/jobs")
async def jobs(limit: int = 30) -> dict[str, Any]:
    return {"items": await store.list_jobs(limit)}


__all__ = ["get_connector", "router"]

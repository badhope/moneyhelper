"""连接 CRUD 与同步：单个同步 / 一键同步全部（登录类返回配对码）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from ..connect import service, store
from ._responses import bad as _bad

router = APIRouter(dependencies=[Depends(get_current_user)])

# ---------------------------------------------------------------------------
# 连接 CRUD
# ---------------------------------------------------------------------------


@router.post("/api/connect/connections")
async def create_connection(payload: dict[str, Any]) -> Any:
    try:
        return await store.create_connection(
            str((payload or {}).get("connector_id") or ""),
            str((payload or {}).get("label") or ""),
            str((payload or {}).get("account_ref") or ""),
            payload.get("meta") if isinstance(payload.get("meta"), dict) else None,
        )
    except ValueError as exc:
        return _bad(str(exc))


@router.patch("/api/connect/connections/{cid}")
async def patch_connection(cid: str, payload: dict[str, Any]) -> Any:
    try:
        return await store.update_connection(cid, payload or {})
    except ValueError as exc:
        return _bad(str(exc), 404 if "不存在" in str(exc) else 400)


@router.delete("/api/connect/connections/{cid}")
async def remove_connection(cid: str) -> dict[str, Any]:
    ok = await store.delete_connection(cid)
    if not ok:
        raise HTTPException(404, "连接不存在")
    return {"deleted": cid}


@router.post("/api/connect/connections/{cid}/sync")
async def sync_one(cid: str, payload: dict[str, Any] | None = None) -> Any:
    try:
        return await service.sync_connection(cid, lang=str((payload or {}).get("lang") or "zh"))
    except ValueError as exc:
        return _bad(str(exc), 404)


@router.post("/api/connect/sync-all")
async def sync_all() -> dict[str, Any]:
    """一键同步全部已启用连接（公开源直连、登录类返回配对码）。"""
    results = []
    for c in await store.list_connections():
        if c["status"] == "disabled":
            continue
        try:
            results.append(await service.sync_connection(c["id"]))
        except Exception as exc:  # noqa: BLE001 — 单条失败不影响其余
            results.append({"id": c["id"], "status": "failed", "message": str(exc)})
    return {"items": results, "count": len(results)}

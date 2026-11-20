"""Studio 市场：目录、安装、推荐安装与卸载。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import auth
from ..logging_utils import get_logger
from ..studio import (
    installer,
    market,
    store,
)
from ._responses import fail as _err
from .studio import _require_admin

log = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# 市场
# ---------------------------------------------------------------------------


@router.get("/api/studio/market/list")
async def studio_market_list() -> dict:
    cfg = await store.get_config()
    installed = cfg.get("marketplace", {}).get("installed") or {}
    items = market.catalog()
    for item in items:
        item["installed"] = item["id"] in installed
    return {"ok": True, "items": items, "categories": market.categories()}


@router.post("/api/studio/market/install")
async def studio_market_install(
    payload: dict,
    _admin: dict = Depends(auth.require_instance_admin),
) -> dict:
    """市场安装会写实例级 mcp.json（含可执行命令），必须实例管理员。"""
    bad = await _require_admin()
    if bad:
        return bad
    item_id = str((payload or {}).get("id") or "").strip()
    if not item_id:
        return _err("id 必填")
    try:
        return await installer.install_market(item_id)
    except ValueError as exc:
        return _err(str(exc))


@router.post("/api/studio/market/install-recommended")
async def studio_market_install_recommended(
    _admin: dict = Depends(auth.require_instance_admin),
) -> dict:
    bad = await _require_admin()
    if bad:
        return bad
    return await installer.install_recommended()


@router.delete("/api/studio/market/{item_id}")
async def studio_market_uninstall(item_id: str) -> dict:
    bad = await _require_admin()
    if bad:
        return bad
    try:
        return await installer.uninstall_market(item_id)
    except ValueError as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------



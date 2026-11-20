"""Studio 资产 CRUD：按 kind 的列表/新增/修改/删除/启停。"""

from __future__ import annotations

from fastapi import APIRouter

from ..logging_utils import get_logger
from ..studio import (
    store,
)
from ._responses import fail as _err
from .studio import _audit, _check_kind, _require_admin

log = get_logger(__name__)

router = APIRouter()


@router.get("/api/studio/{kind}")
async def studio_list(kind: str) -> dict:
    bad = _check_kind(kind)
    if bad:
        return bad
    return {"ok": True, "kind": kind, "assets": await store.list_assets(kind)}


@router.post("/api/studio/{kind}")
async def studio_upsert(kind: str, payload: dict) -> dict:
    bad = _check_kind(kind) or await _require_admin()
    if bad:
        return bad
    asset_id = str((payload or {}).get("id") or "").strip() or store.new_id(kind[:-1])
    body = dict(payload or {})
    body.pop("id", None)
    try:
        saved = await store.upsert_asset(kind, asset_id, body)
    except ValueError as exc:
        return _err(str(exc))
    await _audit(f"studio.{kind}_created", kind, None, {"id": asset_id, "name": saved.get("name")})
    return {"ok": True, "asset": {"id": asset_id, **saved}}


@router.patch("/api/studio/{kind}/{asset_id}")
async def studio_update(kind: str, asset_id: str, payload: dict) -> dict:
    bad = _check_kind(kind) or await _require_admin()
    if bad:
        return bad
    assets = {a["id"]: a for a in await store.list_assets(kind)}
    existing = assets.get(asset_id)
    if existing is None:
        return _err(f"资产不存在：{asset_id}", 404)
    merged = {**existing, **(payload or {})}
    merged.pop("id", None)
    try:
        saved = await store.upsert_asset(kind, asset_id, merged)
    except ValueError as exc:
        return _err(str(exc))
    return {"ok": True, "asset": {"id": asset_id, **saved}}


@router.delete("/api/studio/{kind}/{asset_id}")
async def studio_delete(kind: str, asset_id: str, force: bool = False) -> dict:
    bad = _check_kind(kind) or await _require_admin()
    if bad:
        return bad
    try:
        removed = await store.delete_asset(kind, asset_id, force=force)
    except ValueError as exc:
        return _err(str(exc), 409)
    if not removed:
        return _err(f"资产不存在：{asset_id}", 404)
    await _audit(f"studio.{kind}_deleted", kind, {"id": asset_id}, None)
    return {"ok": True, "deleted": asset_id}


@router.post("/api/studio/{kind}/{asset_id}/toggle")
async def studio_toggle(kind: str, asset_id: str, payload: dict) -> dict:
    bad = _check_kind(kind) or await _require_admin()
    if bad:
        return bad
    enabled = bool((payload or {}).get("enabled", True))
    try:
        updated = await store.set_enabled(kind, asset_id, enabled)
    except PermissionError as exc:
        return _err(str(exc), 403)
    if updated is None:
        return _err(f"资产不存在：{asset_id}", 404)
    return {"ok": True, "asset": updated}

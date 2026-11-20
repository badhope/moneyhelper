"""组织路由·岗位管理：创建/更新/删除，均要求目标租户 owner/admin。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from .. import db
from ._responses import bad as _bad
from .org_scope import _ints, org_admin_scope

router = APIRouter()


@router.post("/api/org/positions")
async def create_position(
    payload: dict[str, Any],
    scope: int = Depends(org_admin_scope),
) -> Any:
    try:
        pos = await db.org_create_position(
            scope,
            str((payload or {}).get("name") or ""),
            _ints(payload, "department_id"),
            str((payload or {}).get("code") or ""),
            str((payload or {}).get("role_hint") or ""),
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "position": pos}


@router.patch("/api/org/positions/{pos_id}")
async def update_position(
    pos_id: int,
    payload: dict[str, Any],
    scope: int = Depends(org_admin_scope),
) -> Any:
    kwargs: dict[str, Any] = {}
    for key in ("name", "code", "role_hint", "status"):
        if key in (payload or {}):
            kwargs[key] = payload[key]
    if "department_id" in (payload or {}):
        kwargs["department_id"] = _ints(payload, "department_id")
    try:
        pos = await db.org_update_position(scope, pos_id, **kwargs)
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "position": pos}


@router.delete("/api/org/positions/{pos_id}")
async def delete_position(
    pos_id: int,
    scope: int = Depends(org_admin_scope),
) -> Any:
    try:
        await db.org_delete_position(scope, pos_id)
    except ValueError as exc:
        return _bad(str(exc))
    return {"ok": True}

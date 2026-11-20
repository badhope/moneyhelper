"""组织路由·成员管理：创建/更新/删除，均要求目标租户 owner/admin。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from .. import db
from ._responses import bad as _bad
from .org_scope import _ints, org_admin_scope

router = APIRouter()


@router.post("/api/org/members")
async def add_member(
    payload: dict[str, Any],
    scope: int = Depends(org_admin_scope),
) -> Any:
    if "user_id" not in (payload or {}):
        return _bad("需要 user_id")
    try:
        member = await db.org_add_member(
            scope,
            int(payload["user_id"]),
            str((payload or {}).get("role") or "member"),
            _ints(payload, "department_id"),
            _ints(payload, "position_id"),
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "member": member}


@router.patch("/api/org/members/{user_id}")
async def update_member(
    user_id: int,
    payload: dict[str, Any],
    scope: int = Depends(org_admin_scope),
) -> Any:
    kwargs: dict[str, Any] = {}
    for key in ("role", "status"):
        if key in (payload or {}):
            kwargs[key] = payload[key]
    if "department_id" in (payload or {}):
        kwargs["department_id"] = _ints(payload, "department_id")
    if "position_id" in (payload or {}):
        kwargs["position_id"] = _ints(payload, "position_id")
    try:
        member = await db.org_update_member(scope, user_id, **kwargs)
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "member": member}


@router.delete("/api/org/members/{user_id}")
async def remove_member(
    user_id: int,
    scope: int = Depends(org_admin_scope),
) -> Any:
    try:
        await db.org_remove_member(scope, user_id)
    except ValueError as exc:
        return _bad(str(exc))
    return {"ok": True}

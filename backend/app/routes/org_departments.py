"""组织路由·部门管理：创建/更新/删除，均要求目标租户 owner/admin。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from .. import db
from ._responses import bad as _bad
from .org_scope import _ints, org_admin_scope

router = APIRouter()


@router.post("/api/org/departments")
async def create_department(
    payload: dict[str, Any],
    scope: int = Depends(org_admin_scope),
) -> Any:
    try:
        dept = await db.org_create_department(
            scope,
            str((payload or {}).get("name") or ""),
            _ints(payload, "parent_id"),
            str((payload or {}).get("code") or ""),
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "department": dept}


@router.patch("/api/org/departments/{dept_id}")
async def update_department(
    dept_id: int,
    payload: dict[str, Any],
    scope: int = Depends(org_admin_scope),
) -> Any:
    kwargs: dict[str, Any] = {}
    for key in ("name", "code", "status"):
        if key in (payload or {}):
            kwargs[key] = payload[key]
    if "parent_id" in (payload or {}):
        kwargs["parent_id"] = _ints(payload, "parent_id")
    try:
        dept = await db.org_update_department(scope, dept_id, **kwargs)
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "department": dept}


@router.delete("/api/org/departments/{dept_id}")
async def delete_department(
    dept_id: int,
    scope: int = Depends(org_admin_scope),
) -> Any:
    try:
        await db.org_delete_department(scope, dept_id)
    except ValueError as exc:
        return _bad(str(exc))
    return {"ok": True}

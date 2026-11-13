"""企业组织 API（切片 1-3）：租户总览 + 部门/岗位/成员管理。

边界：
- 读总览：当前租户成员可读；可通过 `?tenant_id=` 切换到本人有效成员租户；
- 写操作：必须是目标租户的 owner/admin（本机/共享口令放行）；
- 所有查询/写入都带 tenant_id，拒绝跨租户引用；
- 租户切换只影响组织视图，不改变现有账本的 user_id 归属。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from .. import auth, authz, authz_guard, db
from ..db.tenant import current_tenant_id

router = APIRouter()


def _bad(msg: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=code)


def _ints(payload: dict[str, Any], key: str) -> int | None:
    value = (payload or {}).get(key)
    if value in (None, ""):
        return None
    return int(value)


async def org_read_scope(
    tenant_id: int | None = Query(default=None),
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    """解析本次组织请求的目标租户；默认当前租户。"""
    current = current_tenant_id()
    target = current if tenant_id is None else int(tenant_id)
    uid = int((user or {}).get("id") or 0)
    if target == current:
        await authz_guard.record(
            tenant_id=target,
            user=user,
            role=await authz_guard.tenant_role(target, uid),
            permission_id="org:read",
            allowed=True,
            reason="当前租户",
        )
        return target
    if uid == 0:
        await authz_guard.record(
            tenant_id=target,
            user=user,
            role=authz_guard.LOCAL_ROLE,
            permission_id="org:read",
            allowed=False,
            reason="不能切换到其他租户",
        )
        raise HTTPException(status_code=403, detail="不能切换到其他租户")
    role = await db.org_role(target, uid)
    if role is None:
        await authz_guard.record(
            tenant_id=target,
            user=user,
            role=None,
            permission_id="org:read",
            allowed=False,
            reason="非该租户成员",
        )
        raise HTTPException(status_code=403, detail="无权访问该租户")
    await authz_guard.record(
        tenant_id=target,
        user=user,
        role=role,
        permission_id="org:read",
        allowed=True,
        reason="成员可读",
    )
    return target


async def org_admin_scope(
    tenant_id: int | None = Query(default=None),
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    """解析本次组织写操作的目标租户，并要求该租户 owner/admin。"""
    current = current_tenant_id()
    target = current if tenant_id is None else int(tenant_id)
    uid = int((user or {}).get("id") or 0)
    if user is None:
        # 本机无账号模式：auth_gate 已确保没有账号体系；只允许本机租户 0。
        if target != 0:
            await authz_guard.record(
                tenant_id=target,
                user=user,
                role=authz_guard.LOCAL_ROLE,
                permission_id="org:write",
                allowed=False,
                reason="本机模式不能切换到其他租户",
            )
            raise HTTPException(status_code=403, detail="本机模式不能切换到其他租户")
        await authz_guard.record(
            tenant_id=target,
            user=user,
            role=authz_guard.LOCAL_ROLE,
            permission_id="org:write",
            allowed=True,
            reason="本机所有者",
        )
        return target
    if uid == 0:
        # 共享 API_TOKEN：实例管理员，但只能操作本机租户。
        if target != current:
            await authz_guard.record(
                tenant_id=target,
                user=user,
                role=authz_guard.LOCAL_ROLE,
                permission_id="org:write",
                allowed=False,
                reason="共享口令不能切换到其他租户",
            )
            raise HTTPException(status_code=403, detail="共享口令不能切换到其他租户")
        await authz_guard.record(
            tenant_id=target,
            user=user,
            role=authz_guard.LOCAL_ROLE,
            permission_id="org:write",
            allowed=True,
            reason="共享口令",
        )
        return target
    role = await db.org_role(target, uid)
    if not authz.allows(role, "org:write"):
        await authz_guard.record(
            tenant_id=target,
            user=user,
            role=role,
            permission_id="org:write",
            allowed=False,
            reason=f"角色 {role or '无'} 无 org:write",
        )
        raise HTTPException(status_code=403, detail="需要该租户的 owner/admin 权限")
    await authz_guard.record(
        tenant_id=target,
        user=user,
        role=role,
        permission_id="org:write",
        allowed=True,
        reason="owner/admin",
    )
    return target


@router.get("/api/org/tenants")
async def list_org_tenants(
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> Any:
    uid = int(user["id"]) if user else 0
    return {"tenants": await db.list_user_tenants(uid)}


@router.get("/api/org/capabilities")
async def get_capabilities(
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> Any:
    """当前用户在当前工作租户里拥有的权限点（切片 7a）。

    前端按这个隐藏写操作入口，避免"按钮能点、点了 403"。
    权限点来自字典（`authz.role_permissions`），与后端判定同源。
    """
    uid = int((user or {}).get("id") or 0)
    if uid <= 0:
        # 本机无账号模式 / 共享口令：实例所有者
        return {
            "tenant_id": 0,
            "role": authz.LOCAL_ROLE,
            "permissions": sorted(authz.role_permissions(authz.LOCAL_ROLE)),
        }
    active = await db.get_active_tenant(uid)
    tenant_id = active if active is not None else await db.resolve_tenant_id(uid)
    role = await db.org_role(tenant_id, uid)
    return {
        "tenant_id": tenant_id,
        "role": role or "",
        "permissions": sorted(authz.role_permissions(role)),
    }


@router.get("/api/org/active-tenant")
async def get_active_tenant(
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> Any:
    """当前正在工作的租户（切片 7b 全局切换）。

    只影响企业域（组织/总账/报销/付款/对账）；
    个人流水（记账/总览/持仓）仍按登录用户归属，不随切换改变。
    """
    uid = int(user["id"]) if user else 0
    if uid <= 0:
        tenant = await db.get_tenant(0)
        return {
            "active_tenant_id": 0,
            "tenant": tenant,
            "scope_note": "本机单用户模式：只有一个账本",
        }
    active = await db.get_active_tenant(uid)
    resolved = active if active is not None else await db.resolve_tenant_id(uid)
    return {
        "active_tenant_id": resolved,
        "explicit": active is not None,
        "tenant": await db.get_tenant(resolved),
        "scope_note": "切换只作用于企业域；个人流水仍按登录用户归属",
    }


@router.post("/api/org/active-tenant")
async def switch_active_tenant(
    payload: dict[str, Any],
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> Any:
    """切换当前工作的租户。

    必须是本人有效成员资格；tenant_id <= 0 表示取消显式选择（回到默认）。
    """
    uid = int((user or {}).get("id") or 0)
    if uid <= 0:
        return _bad("本机模式没有可切换的账号", 403)
    target = _ints(payload or {}, "tenant_id")
    try:
        active = await db.set_active_tenant(uid, target or 0)
    except ValueError as exc:
        return _bad(str(exc))
    return {
        "ok": True,
        "active_tenant_id": active,
        "tenant": await db.get_tenant(active) if active else None,
        "tenants": await db.list_user_tenants(uid),
    }


@router.get("/api/org/overview")
async def get_org_overview(
    scope: int = Depends(org_read_scope),
) -> Any:
    """目标租户的组织总览（租户、部门、岗位、成员）。"""
    data = await db.org_overview(scope)
    if not data.get("tenant"):
        return _bad("当前租户不存在", 404)
    return data


# ---------------------------------------------------------------------------
# 部门
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 岗位
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 成员
# ---------------------------------------------------------------------------


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

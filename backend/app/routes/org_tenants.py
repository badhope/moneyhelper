"""租户域路由：租户列表、权限点、活动租户切换、组织总览。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from .. import auth, authz, db
from ._responses import bad as _bad
from .org_scope import _ints, org_read_scope

router = APIRouter()


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

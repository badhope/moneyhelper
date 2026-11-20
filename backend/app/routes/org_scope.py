"""组织路由的租户作用域：读域放行规则与写域 owner/admin 校验。

所有查询都带 tenant_id，拒绝跨租户引用；`?tenant_id=` 只能切到本人有效成员租户。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import auth, authz, authz_guard, db
from ..db.tenant import current_tenant_id

router = APIRouter()


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

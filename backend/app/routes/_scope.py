"""租户上下文 + 权限点校验（报销/银行/采购路由共用）。

原先报销与银行各有一份逐行相同的 `_scope`，采购再抄第三份没有意义。
这里保留一份，调用方只需给出权限点与拒绝文案；影子判定照常记录。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .. import authz, authz_guard
from ..db.tenant import current_tenant_id


async def tenant_permission_scope(
    tenant_id: int | None,
    user: dict[str, Any] | None,
    permission_id: str,
    *,
    denied_detail: str = "需要该租户的财务写权限",
) -> int:
    """校验目标租户的有效成员 + 权限点，返回租户 id。

    - 本机无账号 / 共享口令：只允许当前租户，角色记为 local；
    - 普通账号：必须是目标租户成员，且角色拥有该权限点；
    - 无论放行与否都写一条影子判定，供 Casbin 切换前核对。
    """
    current = current_tenant_id()
    target = current if tenant_id is None else int(tenant_id)
    uid = int((user or {}).get("id") or 0)
    if user is None:
        if target != current:
            await authz_guard.record(
                tenant_id=target,
                user=user,
                role=authz_guard.LOCAL_ROLE,
                permission_id=permission_id,
                allowed=False,
                reason="不能切换到其他租户",
            )
            raise HTTPException(status_code=403, detail="不能切换到其他租户")
        await authz_guard.record(
            tenant_id=target,
            user=user,
            role=authz_guard.LOCAL_ROLE,
            permission_id=permission_id,
            allowed=True,
            reason="本机无账号模式",
        )
        return target
    if uid == 0:
        if target != current:
            await authz_guard.record(
                tenant_id=target,
                user=user,
                role=authz_guard.LOCAL_ROLE,
                permission_id=permission_id,
                allowed=False,
                reason="共享口令不能切换到其他租户",
            )
            raise HTTPException(status_code=403, detail="共享口令不能切换到其他租户")
        await authz_guard.record(
            tenant_id=target,
            user=user,
            role=authz_guard.LOCAL_ROLE,
            permission_id=permission_id,
            allowed=True,
            reason="共享口令",
        )
        return target
    from ..db.org import org_role

    role = await org_role(target, uid)
    if role is None:
        await authz_guard.record(
            tenant_id=target,
            user=user,
            role=None,
            permission_id=permission_id,
            allowed=False,
            reason="非该租户成员",
        )
        raise HTTPException(status_code=403, detail="无权访问该租户")
    if not authz.allows(role, permission_id):
        await authz_guard.record(
            tenant_id=target,
            user=user,
            role=role,
            permission_id=permission_id,
            allowed=False,
            reason=f"角色 {role} 无 {permission_id}",
        )
        raise HTTPException(status_code=403, detail=denied_detail)
    await authz_guard.record(
        tenant_id=target,
        user=user,
        role=role,
        permission_id=permission_id,
        allowed=True,
        reason=f"角色 {role}",
    )
    return target

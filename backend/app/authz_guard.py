"""权限闸助手：把「判定 + 影子记录」收敛到一处。

为什么单独抽一层：
5 个业务域（组织/总账/报销/付款/对账）的权限闸长得都不一样——有的查成员资格、
有的查角色表、有的允许本机无账号模式。但影子模式需要它们在**同一个位置**
汇报"判了什么、放没放行"；漏记一处，就等于那个权限点没有覆盖，
汇总出来的"全绿"是假的。

约定：
- 本模块只做两件事：取角色、记录判定；
- 记录**永远不参与放行**：判定结果由调用方自己决定，本模块只旁路留痕；
- 记录失败一律吞掉（由 authz_engine 负责），业务路径不受影响。
"""

from __future__ import annotations

from typing import Any

from . import authz
from .authz_engine import record_decision

# 便于调用方 `authz_guard.LOCAL_ROLE`，不必再单独 import authz
LOCAL_ROLE = authz.LOCAL_ROLE


async def tenant_role(tenant_id: int, user_id: int) -> str | None:
    """取用户在目标租户里的角色。

    - 本机无账号模式 / 共享口令：视为实例所有者（local 角色）；
    - 普通用户：查有效成员资格，查不到返回 None（= 无权）。
    """
    uid = int(user_id or 0)
    if uid <= 0:
        return authz.LOCAL_ROLE
    from .db.org import org_role

    return await org_role(int(tenant_id), uid)


async def record(
    *,
    tenant_id: int,
    user: dict[str, Any] | None,
    role: str | None,
    permission_id: str,
    allowed: bool,
    reason: str = "",
) -> None:
    """记录一次权限判定（只记录不拦截）。"""
    uid = int((user or {}).get("id") or 0)
    await record_decision(
        tenant_id=int(tenant_id),
        user_id=uid if uid > 0 else None,
        role=role or "",
        permission_id=permission_id,
        allowed=bool(allowed),
        reason=reason,
    )

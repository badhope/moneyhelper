"""权限字典与影子决策 API（切片 7a）。

面向"从影子模式切到 Casbin 拦截"这条路径：
- `GET /api/authz/permissions`：权限点字典（角色 → 权限点），是策略的唯一事实来源；
- `GET /api/authz/shadow`：最近的影子决策（字典判定 vs 代码实际放行）；
- `GET /api/authz/shadow/summary`：不一致（mismatch）汇总——切拦截前的必看清单；
- `DELETE /api/authz/shadow`：清空影子数据（只动影子表，不碰审计链）。

读接口对实例管理员开放；普通成员看不到全局策略与他人判定记录。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from .. import auth, db
from ..authz import describe as describe_dictionary
from ..authz_engine import status as engine_status

router = APIRouter()


def _ints(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@router.get("/api/authz/permissions")
async def get_permissions(
    _admin: dict = Depends(auth.require_instance_admin),
) -> Any:
    """权限点字典快照（角色 → 权限点）。"""
    return {
        "dictionary": describe_dictionary(),
        "engine": engine_status(),
    }


@router.get("/api/authz/shadow")
async def list_shadow(
    tenant_id: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    only_mismatch: bool = Query(default=False),
    _admin: dict = Depends(auth.require_instance_admin),
) -> Any:
    """最近的影子决策（新→旧）。"""
    rows = await db.list_shadow_decisions(
        tenant_id=_ints(tenant_id),
        limit=limit,
        only_mismatch=only_mismatch,
    )
    return {"decisions": rows, "engine": engine_status()}


@router.get("/api/authz/shadow/summary")
async def shadow_summary(
    tenant_id: int | None = Query(default=None),
    _admin: dict = Depends(auth.require_instance_admin),
) -> Any:
    """影子决策汇总：总量、allow/deny、不一致数与不一致样本。"""
    data = await db.shadow_summary(tenant_id=_ints(tenant_id))
    return {**data, "engine": engine_status()}


@router.delete("/api/authz/shadow")
async def clear_shadow(
    tenant_id: int | None = Query(default=None),
    _admin: dict = Depends(auth.require_instance_admin),
) -> Any:
    """清空影子决策（仅影子表；审计链不受影响）。"""
    result = await db.clear_shadow_decisions(tenant_id=_ints(tenant_id))
    return {**result}


@router.get("/api/authz/status")
async def authz_status(
    _admin: dict = Depends(auth.require_instance_admin),
) -> Any:
    """影子引擎状态（casbin 是否可用、开关状态、覆盖的权限点数量）。"""
    return engine_status()

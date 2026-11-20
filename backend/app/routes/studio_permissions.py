"""Studio 权限：读取/写入权限模式与核心守卫。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import auth
from ..logging_utils import get_logger
from ..studio import (
    store,
)
from ._responses import fail as _err
from .studio import _audit

log = get_logger(__name__)

router = APIRouter()

@router.get("/api/studio/permissions")
async def studio_permissions() -> dict:
    cfg = await store.get_config()
    return {
        "ok": True,
        "permissions": store.permissions(cfg),
        "locked": list(store.CORE_LOCKED),
        "modes": {
            "open": "全面放开：可改大部分设置（含对话/CLI 管理），核心安全项仍锁定",
            "standard": "标准：只能在设置页手动改，对话与 CLI 不能改配置",
            "strict": "严格：只读 Studio 配置，适合多用户/受管环境",
        },
    }


@router.put("/api/studio/permissions")
async def studio_set_permissions(
    payload: dict,
    _admin: dict = Depends(auth.require_instance_admin),
) -> dict:
    """权限变更必须留痕：谁在什么时候把权限从 X 改成了 Y。

    必须实例管理员：这是「程序能不能改自己」的总闸，普通租户不能自行升到
    open 再借市场安装写全局 mcp.json（历史漏洞 M-1）。
    """
    perms, errors = store.validate_permissions(payload or {})
    if errors:
        return _err("; ".join(errors))
    before = store.permissions(await store.get_config())
    updated = await store.update_permissions(perms)
    await _audit("studio.permissions_changed", "permissions", before, updated)
    return {"ok": True, "permissions": updated}


@router.post("/api/studio/core-guard")
async def studio_core_guard(payload: dict) -> dict:
    """核心项变更请求：一律拒绝并说明原因（前端据此把控件显示为锁定）。"""
    key = str((payload or {}).get("key") or "")
    if key not in store.CORE_LOCKED:
        return {"ok": True, "allowed": True}
    await _audit("studio.core_guard_blocked", "core_guard", {"key": key}, None)
    return {
        "ok": False,
        "allowed": False,
        "error": f"「{key}」属于核心安全项，全面放开模式下也不可修改",
        "reasons": {
            "approval_threshold": f"大额审批阈值下限为 {store.APPROVAL_FLOOR:g} 元，防止关闭写操作保护",
            "ai_api_key": "密钥只能由本人重新填写，不接受程序化改写",
            "api_token": "访问口令属于部署层配置，只能通过环境变量设置",
            "internal_tools_visibility": "内置工具仅内部可见，不对外暴露",
            "destructive_confirm": "删除/覆盖类操作必须保留确认步骤",
        },
    }



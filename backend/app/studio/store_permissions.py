"""Studio 权限：模式、白名单判断与入参校验。"""

from __future__ import annotations

from typing import Any

from ..logging_utils import get_logger
from .store_core import PERMISSION_MODES, _read, _studio_lock, _write

log = get_logger(__name__)

async def update_permissions(patch: dict[str, Any]) -> dict[str, Any]:
    """权限更新走锁：与其它配置写入共用同一份快照，避免并发覆盖。"""
    async with _studio_lock():
        cfg = await _read()
        cfg["permissions"] = {**permissions(cfg), **patch}
        await _write(cfg)
        return cfg["permissions"]

def permissions(cfg: dict[str, Any]) -> dict[str, Any]:
    return dict(cfg.get("permissions") or {})

async def permission_mode() -> str:
    cfg = await _read()
    return str((cfg.get("permissions") or {}).get("mode") or "standard")

async def chat_admin_allowed() -> bool:
    cfg = await _read()
    perms = permissions(cfg)
    return perms.get("mode") == "open" and bool(perms.get("allow_chat_admin", True))

async def cli_admin_allowed() -> bool:
    cfg = await _read()
    perms = permissions(cfg)
    return perms.get("mode") == "open" and bool(perms.get("allow_cli_admin", True))

def validate_permissions(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    out = dict(payload or {})
    # 只有显式传 mode 才校验/写回。缺失 mode 时不能补成 "open"：
    # 只改一个布尔开关不应该顺手把整体权限放开（历史漏洞 M-1/B2）。
    if "mode" in out:
        mode = str(out.get("mode") or "")
        if mode not in PERMISSION_MODES:
            errors.append(f"权限模式只能是 {'/'.join(PERMISSION_MODES)}")
        elif mode != "open":
            # 非全面放开 = 不允许任何程序化写入：对话、CLI、URL 安装一律关闭。
            # 之前只关前两个，URL 安装仍开着，等于留了一个绕过权限的后门。
            out["allow_chat_admin"] = False
            out["allow_cli_admin"] = False
            out["allow_remote_install"] = False
    for key in ("allow_chat_admin", "allow_cli_admin", "allow_remote_install"):
        if key in out and not isinstance(out[key], bool):
            errors.append(f"{key} 必须是布尔值")
    # 单独把 allow_chat_admin 打开、但当前模式不是 open 的请求必须拒绝：
    # 否则标准模式下只要 POST 一个 true 就恢复对话改配置能力。
    if out.get("allow_chat_admin") is True and "mode" not in out:
        errors.append("开启对话管理权限必须同时显式提交 mode=open")
    return out, errors

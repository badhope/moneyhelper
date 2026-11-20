"""Studio 其它设置：主角色、看门狗与内置工具开关。"""

from __future__ import annotations

from typing import Any

from ..logging_utils import get_logger
from .store_core import _read, _studio_lock, _write
from .store_core import mutate_config as _mutate

log = get_logger(__name__)

async def _primary_role(cfg: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    name = str(cfg.get("primary_role") or "supervisor")
    from .. import agent_config

    acfg = await agent_config.get_config()
    role = (acfg.get("agents") or {}).get(name)
    if not isinstance(role, dict) or not role.get("enabled", True):
        return "supervisor", None
    return name, role

async def primary_role() -> dict[str, Any]:
    cfg = await _read()
    name, role = await _primary_role(cfg)
    return {"id": name, "role": role}

async def set_primary_role(role_id: str) -> dict[str, Any]:
    from .. import agent_config

    acfg = await agent_config.get_config()
    if role_id not in (acfg.get("agents") or {}):
        raise ValueError(f"角色不存在：{role_id}")
    await _mutate(lambda cfg: cfg.__setitem__("primary_role", role_id))
    return {"primary_role": role_id}

async def watchdog_settings() -> dict[str, Any]:
    cfg = await _read()
    return dict(cfg.get("watchdog") or {"enabled": True, "interval_minutes": 15})

async def set_watchdog(enabled: bool | None = None, interval_minutes: int | None = None) -> dict[str, Any]:
    async with _studio_lock():
        cfg = await _read()
        wd = cfg.setdefault("watchdog", {"enabled": True, "interval_minutes": 15})
        if enabled is not None:
            wd["enabled"] = bool(enabled)
        if interval_minutes is not None:
            wd["interval_minutes"] = max(1, min(1440, int(interval_minutes)))
        await _write(cfg)
        return dict(wd)

async def internal_tools_enabled() -> dict[str, bool]:
    cfg = await _read()
    tools = cfg.get("internal_tools") or {}
    if not tools.get("enabled", True):
        return {}
    return {
        k: bool(v.get("enabled", True))
        for k, v in (tools.get("tools") or {}).items()
        if isinstance(v, dict) and v.get("enabled", True)
    }

async def set_internal_tool(tool_id: str, enabled: bool) -> dict[str, Any] | None:
    async with _studio_lock():
        cfg = await _read()
        tools = cfg.setdefault("internal_tools", {"enabled": True, "tools": {}})
        entry = (tools.get("tools") or {}).get(tool_id)
        if entry is None:
            return None
        entry["enabled"] = bool(enabled)
        await _write(cfg)
        return {"id": tool_id, **entry}

async def set_internal_tools_enabled(enabled: bool) -> dict[str, Any]:
    async with _studio_lock():
        cfg = await _read()
        tools = cfg.setdefault("internal_tools", {"enabled": True, "tools": {}})
        tools["enabled"] = bool(enabled)
        await _write(cfg)
        return {"enabled": tools["enabled"]}

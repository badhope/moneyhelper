"""Studio 配置的持久化：默认配置、读写、加锁与变更入口。"""

from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime
from typing import Any

from .. import db
from ..logging_utils import get_logger

log = get_logger(__name__)

SETTINGS_KEY = "studio_config"

ASSET_KINDS = ("prompts", "rules", "hooks", "roles", "skills")

PERMISSION_MODES = ("open", "standard", "strict")

HOOK_EVENTS = ("pre_tool", "pre_prompt", "post_answer")

HOOK_ACTIONS = ("block", "warn", "log", "inject")

SEVERITIES = ("must", "should", "may")

APPROVAL_FLOOR = 100.0

CORE_LOCKED = (
    "approval_threshold",
    "ai_api_key",
    "api_token",
    "internal_tools_visibility",
    "destructive_confirm",
)

BUILTIN_PROTECTED_HOOKS = (
    "block_shell_tools",
    "block_file_write_tools",
    "audit_write_tools",
)

DEFAULT_STUDIO: dict[str, Any] = {
    "version": "1.0",
    "permissions": {
        "mode": "open",
        "allow_chat_admin": True,
        "allow_cli_admin": True,
        "allow_remote_install": True,
    },
    "prompts": {},
    "rules": {},
    "hooks": {},
    "internal_tools": {"enabled": True, "tools": {}},
    "marketplace": {"installed": {}},
    "primary_role": "supervisor",
    "watchdog": {"enabled": True, "interval_minutes": 15},
}

_DEFAULT_FILE = None

def _default_file():
    global _DEFAULT_FILE
    if _DEFAULT_FILE is None:
        import pathlib

        _DEFAULT_FILE = pathlib.Path(__file__).resolve().parent / "default_studio.json"
    return _DEFAULT_FILE

def load_default() -> dict[str, Any]:
    try:
        raw = json.loads(_default_file().read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — 默认包损坏时用空壳，保证服务可启动
        log.warning("studio.default_pack_broken: %s", exc)
        return copy.deepcopy(DEFAULT_STUDIO)
    return raw

def _merge_defaults(cfg: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    default = load_default()
    out = copy.deepcopy(cfg or {})
    changed = False
    for key, value in DEFAULT_STUDIO.items():
        if key not in out:
            out[key] = copy.deepcopy(value)
            changed = True
    perms = out.setdefault("permissions", {})
    for k, v in (default.get("permissions") or {}).items():
        if k not in perms:
            perms[k] = v
            changed = True
    if perms.get("mode") not in PERMISSION_MODES:
        # fail-closed：非法/缺失的权限模式回落到「标准」，绝不静默升到「全面放开」。
        # 旧实现回落 open，等于配置损坏时自动放宽权限。
        perms["mode"] = "standard"
        changed = True
    removed = out.setdefault("removed", {})
    for kind in ("prompts", "rules", "hooks", "roles", "skills"):
        removed.setdefault(kind, [])
    for kind in ("prompts", "rules", "hooks"):
        bucket = out.setdefault(kind, {})
        gone = set(removed.get(kind) or [])
        for aid, asset in (default.get(kind) or {}).items():
            if aid in bucket or aid in gone:
                continue
            bucket[aid] = copy.deepcopy(asset)
            changed = True
    tools = out.setdefault("internal_tools", {"enabled": True, "tools": {}})
    if "enabled" not in tools:
        tools["enabled"] = True
        changed = True
    tools.setdefault("tools", {})
    for tid, tool in ((default.get("internal_tools") or {}).get("tools") or {}).items():
        if tid not in tools["tools"]:
            tools["tools"][tid] = copy.deepcopy(tool)
            changed = True
    out.setdefault("marketplace", {"installed": {}})
    out["marketplace"].setdefault("installed", {})
    out.setdefault("primary_role", "supervisor")
    wd = out.setdefault("watchdog", {"enabled": True, "interval_minutes": 15})
    for k, v in {"enabled": True, "interval_minutes": 15}.items():
        if k not in wd:
            wd[k] = v
            changed = True
    return out, changed

def _studio_lock():
    """Studio 配置的读-改-写串行锁。

    每次 save 都是「读整份 JSON → 改一个键 → 写回整份」；两个并发请求各自读到同一份
    快照时，后写的那份会把先写的改动整段丢掉（实测 8 个并发只存下 3 个）。
    复用 db 层按事件循环持有的写锁，与批量入账/导入导入共用同一排他语义。
    """
    from ..db._core import get_write_lock

    return get_write_lock()

async def _read() -> dict[str, Any]:
    raw = (await db.get_settings()).get(SETTINGS_KEY)
    cfg: dict[str, Any] = {}
    if raw:
        try:
            cfg = json.loads(raw)
        except Exception:  # noqa: BLE001 — 配置损坏时回落默认包，损坏内容留在日志
            log.warning("studio.config_parse_failed, falling back to defaults")
            cfg = {}
    merged, changed = _merge_defaults(cfg)
    if changed:
        await _write(merged)
    return merged

async def _write(cfg: dict[str, Any]) -> None:
    await db.set_setting(SETTINGS_KEY, json.dumps(cfg, ensure_ascii=False))

async def mutate_config(mutator) -> dict[str, Any]:
    """加锁的读-改-写：mutator(cfg) 就地修改配置，函数负责写回。

    对外公开（安装器也要用）：任何「读整份 → 改一个键 → 写回」的路径都必须走这里，
    否则并发保存会互相覆盖（实测 8 并发丢 5 个）。
    """
    async with _studio_lock():
        cfg = await _read()
        result = mutator(cfg)
        await _write(cfg)
        return result

async def get_config() -> dict[str, Any]:
    return await _read()

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"

def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")

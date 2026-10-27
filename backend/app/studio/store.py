"""Studio 配置存储：提示词 / 约束 / Hook / 权限 / 内置科研工具 / 市场安装记录。

与 agent_config.py 的分工：角色与技能（agents/skills）仍由 agent_config 持有，
Studio 负责其余资产并提供统一的导入/生成/校验入口。所有资产都存在 settings 表
`studio_config` 键下，随备份导出、随租户隔离。
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from datetime import datetime
from typing import Any

from .. import db, logging_utils

log = logging_utils.get_logger(__name__)

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
        perms["mode"] = "open"
        changed = True
    for kind in ("prompts", "rules", "hooks"):
        bucket = out.setdefault(kind, {})
        for aid, asset in (default.get(kind) or {}).items():
            if aid not in bucket:
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


async def get_config() -> dict[str, Any]:
    return await _read()


async def save_config(cfg: dict[str, Any]) -> dict[str, Any]:
    merged, _ = _merge_defaults(cfg)
    await _write(merged)
    return merged


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
    mode = str(out.get("mode") or "open")
    if mode not in PERMISSION_MODES:
        errors.append(f"权限模式只能是 {'/'.join(PERMISSION_MODES)}")
    for key in ("allow_chat_admin", "allow_cli_admin", "allow_remote_install"):
        if key in out and not isinstance(out[key], bool):
            errors.append(f"{key} 必须是布尔值")
    if mode != "open":
        out["allow_chat_admin"] = False
        out["allow_cli_admin"] = False
    return out, errors


def normalize_asset(kind: str, asset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("资产内容必须是 JSON 对象")
    aid = str(asset_id or payload.get("id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", aid or ""):
        raise ValueError("资产 id 只能包含字母、数字、下划线、点与连字符（最长 64）")
    name = str(payload.get("name") or aid).strip()[:60]
    if not name:
        raise ValueError("资产名称不能为空")
    description = str(payload.get("description") or "").strip()[:300]
    enabled = payload.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("enabled 必须是布尔值")
    base = {
        "name": name,
        "description": description,
        "enabled": enabled,
        "builtin": bool(payload.get("builtin", False)),
    }
    if kind == "prompts":
        content = str(payload.get("content") or "").strip()
        if not content:
            raise ValueError("提示词内容不能为空")
        if len(content) > 8000:
            raise ValueError("提示词内容最多 8000 字")
        base.update(
            {
                "content": content,
                "category": str(payload.get("category") or "custom")[:24],
                "priority": max(0, min(1000, int(payload.get("priority") or 50))),
            }
        )
    elif kind == "rules":
        content = str(payload.get("content") or "").strip()
        if not content:
            raise ValueError("约束内容不能为空")
        if len(content) > 4000:
            raise ValueError("约束内容最多 4000 字")
        severity = str(payload.get("severity") or "should")
        if severity not in SEVERITIES:
            raise ValueError(f"severity 只能是 {'/'.join(SEVERITIES)}")
        scope = str(payload.get("scope") or "all")
        if scope not in ("all", "finance", "research"):
            raise ValueError("scope 只能是 all/finance/research")
        base.update({"content": content, "severity": severity, "scope": scope})
    elif kind == "hooks":
        event = str(payload.get("event") or "pre_tool")
        if event not in HOOK_EVENTS:
            raise ValueError(f"event 只能是 {'/'.join(HOOK_EVENTS)}")
        action = str(payload.get("action") or "log")
        if action not in HOOK_ACTIONS:
            raise ValueError(f"action 只能是 {'/'.join(HOOK_ACTIONS)}")
        match = str(payload.get("match") or "").strip()
        if len(match) > 200:
            raise ValueError("匹配表达式最多 200 字符")
        if match:
            try:
                re.compile(match)
            except re.error as exc:
                raise ValueError(f"匹配表达式不是合法正则：{exc}") from exc
        payload_text = str(payload.get("payload") or "").strip()
        if action == "inject" and not payload_text:
            raise ValueError("inject 动作必须提供注入内容")
        base.update(
            {
                "event": event,
                "action": action,
                "match": match,
                "payload": payload_text[:2000],
                "priority": max(0, min(1000, int(payload.get("priority") or 50))),
            }
        )
    elif kind == "roles":
        base.update(
            {
                "instructions": str(payload.get("instructions") or payload.get("content") or "").strip()[:8000],
                "tools": payload.get("tools") or "all",
                "temperature": float(payload.get("temperature") or 0.2),
            }
        )
    elif kind == "skills":
        base.update(
            {
                "content": str(payload.get("content") or payload.get("description") or "").strip()[:4000],
                "action": payload.get("action"),
            }
        )
    else:
        raise ValueError(f"未知资产类型：{kind}")
    return base


async def list_assets(kind: str) -> list[dict[str, Any]]:
    if kind not in ASSET_KINDS:
        raise ValueError(f"未知资产类型：{kind}")
    cfg = await _read()
    if kind in ("roles", "skills"):
        from .. import agent_config

        acfg = await agent_config.get_config()
        source = acfg.get("agents" if kind == "roles" else "skills") or {}
        return [{"id": k, **v, "builtin": bool(v.get("builtin", False))} for k, v in source.items()]
    return [{"id": k, **v} for k, v in (cfg.get(kind) or {}).items()]


async def _sync_skill_schedule() -> None:
    """技能写操作后同步定时任务（失败只告警：下次保存/重启会重试）。"""
    try:
        from .. import scheduler

        await scheduler.sync_skill_jobs()
    except Exception as exc:  # noqa: BLE001
        log.warning("studio.skill_schedule_sync_failed: %s", exc)


async def upsert_asset(kind: str, asset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    asset = normalize_asset(kind, asset_id, payload)
    if kind in ("roles", "skills"):
        from .. import agent_config

        cfg = await agent_config.get_config()
        bucket = cfg.setdefault("agents" if kind == "roles" else "skills", {})
        if kind == "roles" and asset_id in bucket:
            bucket[asset_id] = {**bucket[asset_id], **asset}
        else:
            bucket[asset_id] = asset
        await agent_config.update_config(cfg)
        if kind == "skills":
            await _sync_skill_schedule()
        return {"id": asset_id, **bucket[asset_id]}
    cfg = await _read()
    bucket = cfg.setdefault(kind, {})
    bucket[asset_id] = asset
    await _write(cfg)
    return {"id": asset_id, **asset}


async def delete_asset(kind: str, asset_id: str, *, force: bool = False) -> bool:
    if kind in ("roles", "skills"):
        from .. import agent_config

        cfg = await agent_config.get_config()
        bucket = cfg.get("agents" if kind == "roles" else "skills") or {}
        if asset_id not in bucket:
            return False
        if bucket[asset_id].get("builtin") and not force:
            raise ValueError("内置角色/技能不可删除；可关闭或使用 force=true 强制删除")
        bucket.pop(asset_id, None)
        await agent_config.update_config(cfg)
        if kind == "skills":
            await _sync_skill_schedule()
        return True
    cfg = await _read()
    bucket = cfg.get(kind) or {}
    if asset_id not in bucket:
        return False
    if bucket[asset_id].get("builtin") and not force:
        raise ValueError("内置资产不可删除；可关闭或使用 force=true 强制删除")
    bucket.pop(asset_id, None)
    await _write(cfg)
    return True


async def set_enabled(kind: str, asset_id: str, enabled: bool) -> dict[str, Any] | None:
    if kind in ("roles", "skills"):
        from .. import agent_config

        cfg = await agent_config.get_config()
        bucket = cfg.setdefault("agents" if kind == "roles" else "skills", {})
        if asset_id not in bucket:
            return None
        bucket[asset_id]["enabled"] = bool(enabled)
        await agent_config.update_config(cfg)
        if kind == "skills":
            await _sync_skill_schedule()
        return {"id": asset_id, **bucket[asset_id]}
    cfg = await _read()
    bucket = cfg.setdefault(kind, {})
    if asset_id not in bucket:
        return None
    bucket[asset_id]["enabled"] = bool(enabled)
    await _write(cfg)
    return {"id": asset_id, **bucket[asset_id]}


def _active(assets: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (k, v)
        for k, v in (assets or {}).items()
        if isinstance(v, dict) and v.get("enabled", True)
    ]


def _run_hook_match(event: str, text: str, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for hid, hook in _active(cfg.get("hooks") or {}):
        if hook.get("event") != event:
            continue
        pattern = str(hook.get("match") or "")
        if pattern:
            try:
                if not re.search(pattern, text):
                    continue
            except re.error:
                continue
        hits.append({"id": hid, **hook})
    hits.sort(key=lambda h: -int(h.get("priority") or 0))
    return hits


async def run_pre_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    cfg = await _read()
    text = f"{name} {json.dumps(args or {}, ensure_ascii=False, default=str)[:2000]}"
    blocked = False
    reasons: list[str] = []
    events: list[dict[str, Any]] = []
    for hook in _run_hook_match("pre_tool", text, cfg):
        action = hook.get("action")
        if action == "block":
            blocked = True
            reasons.append(str(hook.get("payload") or hook.get("name") or "被 Hook 拦截"))
        events.append({"hook": hook.get("id"), "name": hook.get("name"), "action": action})
        if action in ("warn", "block"):
            log.warning("studio.hook pre_tool=%s tool=%s action=%s", hook.get("id"), name, action)
    return {"blocked": blocked, "reason": "；".join(reasons), "events": events}


async def run_post_answer(answer: str) -> list[dict[str, Any]]:
    cfg = await _read()
    events: list[dict[str, Any]] = []
    for hook in _run_hook_match("post_answer", answer or "", cfg):
        action = hook.get("action")
        if action in ("warn", "log"):
            log.warning("studio.hook post_answer=%s action=%s", hook.get("id"), action)
        events.append({"hook": hook.get("id"), "name": hook.get("name"), "action": action})
    return events


def _prompt_blocks(cfg: dict[str, Any], scope: str = "all") -> str:
    parts: list[str] = []
    prompts = sorted(
        _active(cfg.get("prompts") or {}), key=lambda kv: -int(kv[1].get("priority") or 0)
    )
    if prompts:
        parts.append(
            "## 提示词工程（用户配置，按优先级叠加）\n"
            + "\n".join(f"- {v.get('name')}：{v.get('content')}" for _, v in prompts)
        )
    rules = [
        v
        for _, v in _active(cfg.get("rules") or {})
        if v.get("scope") in ("all", scope) or scope == "all"
    ]
    if rules:
        lines = []
        for rule in rules:
            label = {"must": "必须", "should": "应当", "may": "可选"}.get(
                str(rule.get("severity") or "should"), "应当"
            )
            lines.append(f"- [{label}] {rule.get('name')}：{rule.get('content')}")
        parts.append("## 约束工程（违反 must 级约束的回答不合格）\n" + "\n".join(lines))
    injections = [
        str(v.get("payload") or "")
        for _, v in _active(cfg.get("hooks") or {})
        if v.get("event") == "pre_prompt" and v.get("action") == "inject"
    ]
    if injections:
        parts.append("## 运行时注入\n" + "\n".join(injections))
    return "\n\n".join(parts)


def _render_injections(text: str) -> str:
    return text.replace("{date}", datetime.now().strftime("%Y-%m-%d"))


async def build_system_prompt(base: str, scope: str = "finance") -> str:
    cfg = await _read()
    role_name, role = await _primary_role(cfg)
    role_block = ""
    if role is not None:
        instructions = str(role.get("instructions") or "").strip()
        if instructions:
            role_block = f"## 当前角色：{role.get('name') or role_name}\n{instructions}"
    blocks = _render_injections(_prompt_blocks(cfg, scope))
    parts = [x for x in (base.strip(), role_block.strip(), blocks.strip()) if x]
    return "\n\n".join(parts)


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
    cfg = await _read()
    cfg["primary_role"] = role_id
    await _write(cfg)
    return {"primary_role": role_id}


async def watchdog_settings() -> dict[str, Any]:
    cfg = await _read()
    return dict(cfg.get("watchdog") or {"enabled": True, "interval_minutes": 15})


async def set_watchdog(enabled: bool | None = None, interval_minutes: int | None = None) -> dict[str, Any]:
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
    cfg = await _read()
    tools = cfg.setdefault("internal_tools", {"enabled": True, "tools": {}})
    entry = (tools.get("tools") or {}).get(tool_id)
    if entry is None:
        return None
    entry["enabled"] = bool(enabled)
    await _write(cfg)
    return {"id": tool_id, **entry}


async def set_internal_tools_enabled(enabled: bool) -> dict[str, Any]:
    cfg = await _read()
    tools = cfg.setdefault("internal_tools", {"enabled": True, "tools": {}})
    tools["enabled"] = bool(enabled)
    await _write(cfg)
    return {"enabled": tools["enabled"]}


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")

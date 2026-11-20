"""Studio 资产 CRUD：规范化、列表、增删改、启用开关与墓碑。"""

from __future__ import annotations

import re
from typing import Any

from ..logging_utils import get_logger
from .store_core import (
    ASSET_KINDS,
    BUILTIN_PROTECTED_HOOKS,
    HOOK_ACTIONS,
    HOOK_EVENTS,
    SEVERITIES,
    _read,
    _studio_lock,
    _write,
)

log = get_logger(__name__)

def _normalize_action(raw: Any) -> dict[str, Any] | None:
    """定时动作校验：与 agent_config.normalize_skill_action 同一实现（不复制规则）。"""
    from .. import agent_config

    return agent_config.normalize_skill_action(raw)

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
        content = str(payload.get("content") or payload.get("description") or "").strip()[:4000]
        raw_action = payload.get("action")
        action = None
        if raw_action not in (None, {}, ""):
            action = _normalize_action(raw_action)
            if action is None:
                raise ValueError(
                    "定时动作格式不合法：需 prompt（1-200 字）+ time（HH:MM）+ weekdays（0-6 整数数组）"
                )
            if not content:
                content = str(action.get("prompt") or "")
        base.update({"content": content, "action": action})
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
    # 整段读-改-写必须持同一把锁。历史缺陷：这里原先在锁外先调 _clear_tombstone
    # （自己读一次、写一次），再调 _mutate（再读一次、写一次）——两次读之间
    # 别的并发写会插进来，于是「清墓碑」那次写回会把对方刚写入的资产整段覆盖。
    # 表现为 12 并发时随机丢 1 条且 gather 无异常（写成功了、随后被覆盖）。
    async with _studio_lock():
        return await _upsert_asset_locked(kind, asset_id, asset, payload)

async def _upsert_asset_locked(
    kind: str, asset_id: str, asset: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
    # builtin 是「随包分发的内置资产」标记，由默认包决定，不能被编辑表单抹掉：
    # normalize_asset 只收可编辑字段，这里把既有标记补回来（否则编辑一次内置项就变成可删）。
    if kind in ("prompts", "rules", "hooks"):
        existing_cfg = await _read()
        existing = (existing_cfg.get(kind) or {}).get(asset_id)
        if isinstance(existing, dict) and existing.get("builtin"):
            asset["builtin"] = True
    await _clear_tombstone(kind, asset_id)
    if kind in ("roles", "skills"):
        # 同一把锁内完成 agent_config 的读改写：它写的是另一个 settings 键，
        # 但同样是「读整份 → 改一个键 → 写回」，锁外执行会与并发的技能/角色
        # 保存互相覆盖（与上面 _clear_tombstone 是同一类缺陷）。
        from .. import agent_config

        cfg = await agent_config.get_config()
        bucket = cfg.setdefault("agents" if kind == "roles" else "skills", {})
        if kind == "roles" and asset_id in bucket:
            bucket[asset_id] = {**bucket[asset_id], **asset}
        else:
            bucket[asset_id] = asset
        agent_config.unmark_removed(cfg, "agents" if kind == "roles" else "skills", asset_id)
        await agent_config.update_config(cfg)
        if kind == "skills":
            await _sync_skill_schedule()
        return {"id": asset_id, **bucket[asset_id]}
    cfg = await _read()
    cfg.setdefault(kind, {})[asset_id] = asset
    await _write(cfg)
    return {"id": asset_id, **asset}

def _add_tombstone(cfg: dict[str, Any], kind: str, asset_id: str) -> None:
    """在内存配置里记一条删除墓碑（调用方负责一次性写回）。

    必须与删除动作在同一次写回里完成：`_read()` 会补齐默认包，先写删除再读一次
    记墓碑会让刚删的内置项在中间那次读取里复活。
    """
    removed = cfg.setdefault("removed", {})
    ids = removed.setdefault(kind, [])
    if asset_id not in ids:
        ids.append(asset_id)

async def _clear_tombstone(kind: str, asset_id: str) -> None:
    cfg = await _read()
    removed = cfg.setdefault("removed", {})
    ids = removed.setdefault(kind, [])
    if asset_id in ids:
        ids.remove(asset_id)
        await _write(cfg)

async def delete_asset(kind: str, asset_id: str, *, force: bool = False) -> bool:
    # 整个函数持锁：roles/skills 要同时改 agent_config 与 studio 配置两处，
    # 锁外执行会与并发的 upsert/set_enabled 互相覆盖（与 upsert_asset 同类缺陷）。
    async with _studio_lock():
        return await _delete_asset_locked(kind, asset_id, force=force)

async def _delete_asset_locked(kind: str, asset_id: str, *, force: bool) -> bool:
    if kind in ("roles", "skills"):
        from .. import agent_config

        cfg = await agent_config.get_config()
        bucket = cfg.get("agents" if kind == "roles" else "skills") or {}
        if asset_id not in bucket:
            return False
        if bucket[asset_id].get("builtin") and not force:
            raise ValueError("内置角色/技能不可删除；可关闭或使用 force=true 强制删除")
        bucket.pop(asset_id, None)
        # 同时在 agent_config 记录墓碑：它的 _merge_defaults 也会补齐内置项
        agent_config.mark_removed(cfg, "agents" if kind == "roles" else "skills", asset_id)
        await agent_config.update_config(cfg)
        scfg = await _read()
        _add_tombstone(scfg, kind, asset_id)
        await _write(scfg)
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
    _add_tombstone(cfg, kind, asset_id)
    await _write(cfg)
    return True

async def set_enabled(kind: str, asset_id: str, enabled: bool) -> dict[str, Any] | None:
    async with _studio_lock():
        return await _set_enabled_locked(kind, asset_id, enabled)

async def _set_enabled_locked(
    kind: str, asset_id: str, enabled: bool
) -> dict[str, Any] | None:
    if kind in ("roles", "skills"):
        from .. import agent_config

        cfg = await agent_config.get_config()
        bucket = cfg.setdefault("agents" if kind == "roles" else "skills", {})
        if asset_id not in bucket:
            return None
        bucket[asset_id]["enabled"] = bool(enabled)
        agent_config.unmark_removed(cfg, "agents" if kind == "roles" else "skills", asset_id)
        await agent_config.update_config(cfg)
        if kind == "skills":
            await _sync_skill_schedule()
        return {"id": asset_id, **bucket[asset_id]}
    cfg = await _read()
    bucket = cfg.setdefault(kind, {})
    if asset_id not in bucket:
        return None
    # 内置安全 Hook 不允许停用：否则一句「停用 Hook」就能关掉命令执行拦截。
    if kind == "hooks" and not enabled and asset_id in BUILTIN_PROTECTED_HOOKS:
        raise PermissionError("内置安全 Hook 不可停用（命令执行/文件写入拦截是安全底线）")
    bucket[asset_id]["enabled"] = bool(enabled)
    await _write(cfg)
    return {"id": asset_id, **bucket[asset_id]}

def _active(assets: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (k, v)
        for k, v in (assets or {}).items()
        if isinstance(v, dict) and v.get("enabled", True)
    ]

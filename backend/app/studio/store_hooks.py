"""Studio Hook 与提示词拼装：pre_tool / post_answer、注入块与系统提示。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from ..logging_utils import get_logger
from .store_assets import _active
from .store_core import _read
from .store_extras import _primary_role

log = get_logger(__name__)

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

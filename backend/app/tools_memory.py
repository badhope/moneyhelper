"""长期记忆与经验库工具（从 tools.py 拆出）：读记忆、查踩坑、记一条。

读取时会刷新 last_used，作为「主动遗忘」的依据。
"""

from __future__ import annotations

import json
from typing import Any

from . import db


async def tool_get_user_memory(args: dict[str, Any]) -> str:
    """查用户长期记忆：用户主动告知的长期信息（偏好、家庭、计划等）。
    可选 kind 过滤（fact / preference / goal_related）；可选 query 做 BM25 关键词检索
    （无 embedding Key 的确定性语义检索降级）；每次读取刷新 last_used（主动遗忘依据）。"""
    rows = await db.list_memory()
    kind = str((args or {}).get("kind") or "").strip()
    query = str((args or {}).get("query") or "").strip()
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    if query:
        rows = db.memory_retrieve(query, rows, top_k=5)
    if not rows:
        return json.dumps({"empty": True, "hint": "暂无长期记忆"}, ensure_ascii=False)
    # 刷新被使用的记忆时间戳（主动遗忘：久未使用的记忆才建议清理）
    try:
        for r in rows:
            await db.touch_memory(r["id"])
    except Exception:  # noqa: BLE001 — 时间戳刷新失败不影响返回
        pass
    return json.dumps(
        [{"content": r["content"], "kind": r["kind"]} for r in rows],
        ensure_ascii=False,
    )
async def tool_get_lessons(_args: dict[str, Any]) -> str:
    """查经验库：之前工具调用的踩坑记录（供反思复用，避免重复犯错）。无参数。"""
    rows = await db.list_reflections(limit=10)
    if not rows:
        return json.dumps({"empty": True, "hint": "暂无踩坑经验"}, ensure_ascii=False)
    return json.dumps(
        [{"tool": r["tool"], "lesson": r["lesson"], "created_at": r["created_at"]} for r in rows],
        ensure_ascii=False,
    )
async def tool_save_user_memory(args: dict[str, Any]) -> str:
    """记住一条用户长期信息（如「明年计划买房」「每月收入 2 万」）。参数：content（要记住的内容）。"""
    content = str(args.get("content") or "").strip()
    if not content:
        return "缺少 content 参数"
    out = await db.add_memory(content)
    return json.dumps({"ok": True, "deduped": out.get("deduped", False)}, ensure_ascii=False)

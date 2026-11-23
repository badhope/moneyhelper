"""会话级项目资料：固定文件、项目指令、项目记忆。

只服务当前会话，不写全局长期记忆，也不跨 thread 泄露；存储按 user_id 隔离。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ._core import _conn, get_write_lock
from .audit import get_attachment
from .tenant import current_user_id

MAX_INSTRUCTIONS = 2000
MAX_MEMORIES = 10
MAX_MEMORY_CHARS = 200
MAX_ATTACHMENTS = 10


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _clean_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _normalize_memories(raw: Any) -> list[dict[str, Any]]:
    """项目记忆统一成 [{id,text}]；id 在本次保存内稳定且从 1 递增。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw[:MAX_MEMORIES]:
        text = _clean_text(item.get("text") if isinstance(item, dict) else item, MAX_MEMORY_CHARS)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append({"id": len(out) + 1, "text": text})
    return out


async def get_thread_context(thread_id: str) -> dict[str, Any]:
    """读取当前用户的会话项目卡；没有记录时返回空结构。"""
    tid = _clean_text(thread_id, 128)
    if not tid:
        return {"thread_id": "", "instructions": "", "attachments": [], "memories": []}
    conn = await _conn()
    cur = await conn.execute(
        "SELECT thread_id,instructions,attachments_json,memories_json,updated_at"
        " FROM thread_projects WHERE user_id=? AND thread_id=?",
        (current_user_id(), tid),
    )
    row = await cur.fetchone()
    if not row:
        return {"thread_id": tid, "instructions": "", "attachments": [], "memories": [], "updated_at": ""}
    try:
        attachments = json.loads(row["attachments_json"] or "[]")
    except Exception:  # noqa: BLE001 — 旧数据损坏时按空处理，不拖垮会话
        attachments = []
    try:
        memories = json.loads(row["memories_json"] or "[]")
    except Exception:  # noqa: BLE001
        memories = []
    return {
        "thread_id": row["thread_id"],
        "instructions": row["instructions"] or "",
        "attachments": attachments if isinstance(attachments, list) else [],
        "memories": memories if isinstance(memories, list) else [],
        "updated_at": row["updated_at"] or "",
    }


async def save_thread_context(
    thread_id: str,
    *,
    instructions: Any = None,
    attachment_ids: Any = None,
    memories: Any = None,
) -> dict[str, Any]:
    """整卡保存：只允许当前用户自己的附件，最多 10 个。"""
    tid = _clean_text(thread_id, 128)
    if not tid:
        raise ValueError("thread_id required")
    current = await get_thread_context(tid)
    text = _clean_text(instructions, MAX_INSTRUCTIONS) if instructions is not None else current["instructions"]
    mems = _normalize_memories(memories) if memories is not None else current["memories"]
    atts: list[dict[str, Any]] = []
    raw_ids = attachment_ids if attachment_ids is not None else [a.get("id") for a in current["attachments"]]
    if isinstance(raw_ids, list):
        seen: set[int] = set()
        for raw in raw_ids[:MAX_ATTACHMENTS]:
            try:
                aid = int(raw)
            except (TypeError, ValueError):
                continue
            if aid <= 0 or aid in seen:
                continue
            att = await get_attachment(aid)
            if not att:
                continue
            seen.add(aid)
            atts.append(
                {
                    "id": aid,
                    "filename": str(att.get("filename") or "")[:255],
                    "kind": str(att.get("kind") or "text")[:20],
                }
            )
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO thread_projects(user_id,thread_id,instructions,attachments_json,memories_json,updated_at)"
            " VALUES(?,?,?,?,?,?)"
            " ON CONFLICT(user_id,thread_id) DO UPDATE SET"
            " instructions=excluded.instructions,attachments_json=excluded.attachments_json,"
            " memories_json=excluded.memories_json,updated_at=excluded.updated_at",
            (
                current_user_id(),
                tid,
                text,
                json.dumps(atts, ensure_ascii=False),
                json.dumps(mems, ensure_ascii=False),
                _now(),
            ),
        )
        await conn.commit()
    return await get_thread_context(tid)

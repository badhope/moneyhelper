"""会话项目资料：固定文件、项目指令、项目记忆。

两种作用域：
- 仅本会话：数据直接挂在 thread_projects，按 user_id + thread_id 隔离；
- 跨会话项目：chat_projects 存一份，thread_projects.project_id 指向它。
  同一项目的会话共享指令/固定文件/记忆，但各自的历史消息仍按 thread 隔离。
"""

from __future__ import annotations

import json
from typing import Any

from ..timeutil import now_iso
from ._core import _conn, get_write_lock
from .audit import get_attachment
from .tenant import current_user_id

MAX_INSTRUCTIONS = 2000
MAX_MEMORIES = 10
MAX_MEMORY_CHARS = 200
MAX_ATTACHMENTS = 10
MAX_PROJECT_NAME = 60
_KEEP = object()


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


async def _attachment_snapshot(raw_ids: Any) -> list[dict[str, Any]]:
    """只接受当前用户自己的附件，最多 10 个；保留文件名与类型供展示。"""
    atts: list[dict[str, Any]] = []
    if not isinstance(raw_ids, list):
        return atts
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
    return atts


def _decode_list(raw: Any) -> list[Any]:
    try:
        value = json.loads(raw or "[]")
    except Exception:  # noqa: BLE001 — 旧数据损坏时按空处理，不拖垮会话
        return []
    return value if isinstance(value, list) else []


async def _row_context(row: Any, *, thread_id: str) -> dict[str, Any]:
    return {
        "thread_id": thread_id,
        "project_id": int(row["project_id"]) if row["project_id"] else None,
        "project_name": "",
        "instructions": row["instructions"] or "",
        "attachments": _decode_list(row["attachments_json"]),
        "memories": _decode_list(row["memories_json"]),
        "updated_at": row["updated_at"] or "",
    }


async def get_thread_context(thread_id: str) -> dict[str, Any]:
    """读取当前会话有效项目资料；跨会话项目存在时返回项目最新内容。"""
    tid = _clean_text(thread_id, 128)
    if not tid:
        return {
            "thread_id": "",
            "project_id": None,
            "project_name": "",
            "instructions": "",
            "attachments": [],
            "memories": [],
        }
    conn = await _conn()
    cur = await conn.execute(
        "SELECT thread_id,project_id,instructions,attachments_json,memories_json,updated_at"
        " FROM thread_projects WHERE user_id=? AND thread_id=?",
        (current_user_id(), tid),
    )
    row = await cur.fetchone()
    if not row:
        return {
            "thread_id": tid,
            "project_id": None,
            "project_name": "",
            "instructions": "",
            "attachments": [],
            "memories": [],
            "updated_at": "",
        }
    ctx = await _row_context(row, thread_id=tid)
    if ctx["project_id"]:
        project = await get_chat_project(ctx["project_id"])
        if project:
            ctx.update(
                {
                    "project_name": project["name"],
                    "instructions": project["instructions"],
                    "attachments": project["attachments"],
                    "memories": project["memories"],
                    "updated_at": project["updated_at"],
                }
            )
    return ctx


async def list_chat_projects() -> list[dict[str, Any]]:
    """当前用户的项目库；只返摘要，避免把全部附件正文带到导航。"""
    conn = await _conn()
    cur = await conn.execute(
        "SELECT id,name,instructions,attachments_json,memories_json,updated_at"
        " FROM chat_projects WHERE user_id=? ORDER BY updated_at DESC,id DESC",
        (current_user_id(),),
    )
    rows = await cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        atts = _decode_list(row["attachments_json"])
        mems = _decode_list(row["memories_json"])
        out.append(
            {
                "id": row["id"],
                "name": row["name"],
                "instructions": row["instructions"] or "",
                "attachment_count": len(atts),
                "memory_count": len(mems),
                "updated_at": row["updated_at"] or "",
            }
        )
    return out


async def get_chat_project(project_id: int) -> dict[str, Any] | None:
    conn = await _conn()
    cur = await conn.execute(
        "SELECT id,name,instructions,attachments_json,memories_json,updated_at"
        " FROM chat_projects WHERE user_id=? AND id=?",
        (current_user_id(), int(project_id)),
    )
    row = await cur.fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "instructions": row["instructions"] or "",
        "attachments": _decode_list(row["attachments_json"]),
        "memories": _decode_list(row["memories_json"]),
        "updated_at": row["updated_at"] or "",
    }


async def _write_project(
    project_id: int | None,
    *,
    name: str,
    instructions: str,
    attachments: list[dict[str, Any]],
    memories: list[dict[str, Any]],
) -> dict[str, Any]:
    conn = await _conn()
    async with get_write_lock():
        if project_id is None:
            cur = await conn.execute(
                "INSERT INTO chat_projects(user_id,name,instructions,attachments_json,memories_json,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (
                    current_user_id(),
                    name,
                    instructions,
                    json.dumps(attachments, ensure_ascii=False),
                    json.dumps(memories, ensure_ascii=False),
                    now_iso(),
                    now_iso(),
                ),
            )
            project_id = int(cur.lastrowid)
        else:
            await conn.execute(
                "UPDATE chat_projects SET name=?,instructions=?,attachments_json=?,memories_json=?,updated_at=?"
                " WHERE user_id=? AND id=?",
                (
                    name,
                    instructions,
                    json.dumps(attachments, ensure_ascii=False),
                    json.dumps(memories, ensure_ascii=False),
                    now_iso(),
                    current_user_id(),
                    int(project_id),
                ),
            )
        # 线程行保留一份副本：项目被删后仍能继续使用原资料，而不是突然清空。
        await conn.execute(
            "UPDATE thread_projects SET instructions=?,attachments_json=?,memories_json=?,updated_at=?"
            " WHERE user_id=? AND project_id=?",
            (
                instructions,
                json.dumps(attachments, ensure_ascii=False),
                json.dumps(memories, ensure_ascii=False),
                now_iso(),
                current_user_id(),
                int(project_id),
            ),
        )
        await conn.commit()
    project = await get_chat_project(int(project_id))
    if not project:
        raise ValueError("项目不存在")
    return project


async def save_chat_project(
    *,
    project_id: int | None = None,
    name: Any,
    instructions: Any = None,
    attachment_ids: Any = None,
    memories: Any = None,
) -> dict[str, Any]:
    clean_name = _clean_text(name, MAX_PROJECT_NAME)
    if not clean_name:
        raise ValueError("项目名称不能为空")
    current = await get_chat_project(project_id) if project_id else None
    if project_id and not current:
        raise ValueError("项目不存在")
    text = _clean_text(instructions, MAX_INSTRUCTIONS) if instructions is not None else (current or {}).get("instructions", "")
    mems = _normalize_memories(memories) if memories is not None else (current or {}).get("memories", [])
    atts = (
        await _attachment_snapshot(attachment_ids)
        if attachment_ids is not None
        else (current or {}).get("attachments", [])
    )
    return await _write_project(
        int(project_id) if project_id else None,
        name=clean_name,
        instructions=text,
        attachments=atts,
        memories=mems,
    )


async def delete_chat_project(project_id: int) -> dict[str, Any]:
    conn = await _conn()
    async with get_write_lock():
        cur = await conn.execute(
            "DELETE FROM chat_projects WHERE user_id=? AND id=?",
            (current_user_id(), int(project_id)),
        )
        if cur.rowcount:
            await conn.execute(
                "UPDATE thread_projects SET project_id=NULL WHERE user_id=? AND project_id=?",
                (current_user_id(), int(project_id)),
            )
        await conn.commit()
    return {"ok": True, "deleted": bool(cur.rowcount)}


async def save_thread_context(
    thread_id: str,
    *,
    instructions: Any = None,
    attachment_ids: Any = None,
    memories: Any = None,
    project_id: Any = _KEEP,
) -> dict[str, Any]:
    """整卡保存；project_id 明确传入 null 时退回仅本会话。"""
    tid = _clean_text(thread_id, 128)
    if not tid:
        raise ValueError("thread_id required")
    current = await get_thread_context(tid)
    linked = current.get("project_id") if project_id is _KEEP else project_id
    if linked:
        try:
            pid = int(linked)
        except (TypeError, ValueError):
            raise ValueError("project_id invalid") from None
        project = await get_chat_project(pid)
        if not project:
            raise ValueError("项目不存在")
        text = _clean_text(instructions, MAX_INSTRUCTIONS) if instructions is not None else project["instructions"]
        mems = _normalize_memories(memories) if memories is not None else project["memories"]
        atts = (
            await _attachment_snapshot(attachment_ids)
            if attachment_ids is not None
            else project["attachments"]
        )
        project = await _write_project(
            pid, name=project["name"], instructions=text, attachments=atts, memories=mems
        )
        project_link = pid
        project_name = project["name"]
    else:
        text = _clean_text(instructions, MAX_INSTRUCTIONS) if instructions is not None else current["instructions"]
        mems = _normalize_memories(memories) if memories is not None else current["memories"]
        atts = (
            await _attachment_snapshot(attachment_ids)
            if attachment_ids is not None
            else current["attachments"]
        )
        project_link = None
        project_name = ""

    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO thread_projects(user_id,thread_id,project_id,instructions,attachments_json,memories_json,updated_at)"
            " VALUES(?,?,?,?,?,?,?)"
            " ON CONFLICT(user_id,thread_id) DO UPDATE SET"
            " project_id=excluded.project_id,instructions=excluded.instructions,"
            " attachments_json=excluded.attachments_json,memories_json=excluded.memories_json,updated_at=excluded.updated_at",
            (
                current_user_id(),
                tid,
                project_link,
                text,
                json.dumps(atts, ensure_ascii=False),
                json.dumps(mems, ensure_ascii=False),
                now_iso(),
            ),
        )
        await conn.commit()
    ctx = await get_thread_context(tid)
    ctx["project_name"] = project_name or ctx.get("project_name", "")
    return ctx

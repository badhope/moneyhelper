"""会话管理：thread 新建/重命名/删除/迁移/线程归属。

从 history.py 拆出；连接与助手仍走 _core，租户口径走 tenant。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ._core import (
    _conn,
    fetch_all,
    uuid_hex,
)
from .tenant import current_user_id


def is_system_thread(thread_id: str) -> bool:
    """系统归档线程（不属于「问AI」会话列表）：cron 晨报 / skill:<id> 技能定时触发。"""
    return thread_id == "cron" or thread_id.startswith("skill:")

async def upsert_session(thread_id: str, title: str) -> dict[str, Any]:
    """问答落库时同步会话表：标题仍为默认'新会话'时用首个问题覆盖，否则保留自定义；刷新 updated_at。

    系统归档线程直接拒绝（第三道防线：调用方应传 skip_session，读侧与启动迁移也各自排除）。
    """
    if is_system_thread(thread_id):
        return {"ok": True, "thread_id": thread_id, "skipped": "system_thread"}
    conn = await _conn()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    await conn.execute(
        "INSERT INTO sessions(user_id,thread_id,title,created_at,updated_at)"
        " VALUES(?,?,?,?,?)"
        " ON CONFLICT(user_id,thread_id) DO UPDATE SET"
        " title=CASE WHEN sessions.title='新会话' THEN excluded.title ELSE sessions.title END,"
        " updated_at=excluded.updated_at",
        (current_user_id(), thread_id, title[:40] or "新会话", now, now),
    )
    await conn.commit()
    return {"ok": True, "thread_id": thread_id}

async def create_session(
    thread_id: str | None = None, title: str = "新会话"
) -> dict[str, Any]:
    conn = await _conn()
    tid = thread_id or uuid_hex()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    cur = await conn.execute(
        "INSERT INTO sessions(user_id,thread_id,title,created_at,updated_at)"
        " VALUES(?,?,?,?,?)",
        (current_user_id(), tid, title[:40] or "新会话", now, now),
    )
    await conn.commit()
    return {"ok": True, "id": cur.lastrowid, "thread_id": tid}

async def list_sessions() -> list[dict[str, Any]]:
    # 读侧同样排除系统归档线程（cron 晨报 / skill:<id> 技能触发）：即使旧库已被
    # 误建，界面也不会把它们当会话展示；启动迁移会做彻底清理。
    rows = await fetch_all(
        "SELECT id, thread_id, title, pinned, archived, created_at, updated_at"
        " FROM sessions WHERE user_id=? AND thread_id <> 'cron' AND thread_id NOT LIKE 'skill:%'"
        " ORDER BY pinned DESC, updated_at DESC",
        (current_user_id(),),
    )
    return rows

async def rename_session(session_id: int, title: str) -> dict[str, Any]:
    conn = await _conn()
    await conn.execute(
        "UPDATE sessions SET title=?, updated_at=? WHERE user_id=? AND id=?",
        (
            str(title).strip()[:40] or "新会话",
            datetime.now().astimezone().isoformat(timespec="seconds"),
            current_user_id(),
            int(session_id),
        ),
    )
    await conn.commit()
    return {"ok": True}

async def update_session_flags(
    session_id: int,
    *,
    pinned: bool | None = None,
    archived: bool | None = None,
) -> dict[str, Any]:
    """置顶/归档会话；两个字段独立更新，未传的保持原值。"""
    conn = await _conn()
    sets: list[str] = []
    args: list[Any] = []
    if pinned is not None:
        sets.append("pinned=?")
        args.append(1 if pinned else 0)
    if archived is not None:
        sets.append("archived=?")
        args.append(1 if archived else 0)
    if not sets:
        return {"ok": True}
    args.extend([current_user_id(), int(session_id)])
    await conn.execute(
        f"UPDATE sessions SET {', '.join(sets)} WHERE user_id=? AND id=?",
        tuple(args),
    )
    await conn.commit()
    return {"ok": True}


async def delete_session(session_id: int) -> dict[str, Any]:
    """删除会话及其全部问答记录（含长会话摘要）。"""
    from ._core import write_txn

    conn = await _conn()
    row = await (
        await conn.execute(
            "SELECT thread_id FROM sessions WHERE user_id=? AND id=?",
            (current_user_id(), int(session_id)),
        )
    ).fetchone()
    # 三张表一起删必须成组：autocommit 下裸 commit 是空操作，
    # 中途失败会留下"会话已删、runs 还挂在 thread 上"的孤儿数据。
    async with write_txn() as conn:
        await conn.execute(
            "DELETE FROM sessions WHERE user_id=? AND id=?",
            (current_user_id(), int(session_id)),
        )
        if row:
            await conn.execute(
                "DELETE FROM runs WHERE user_id=? AND thread_id=?",
                (current_user_id(), row["thread_id"]),
            )
            await conn.execute(
                "DELETE FROM conversation_summary WHERE user_id=? AND thread_id=?",
                (current_user_id(), row["thread_id"]),
            )
    return {"ok": True, "deleted": True}

async def session_thread_id(session_id: int) -> str | None:
    """会话对应的 thread_id；不存在返回 None。"""
    conn = await _conn()
    row = await (
        await conn.execute(
            "SELECT thread_id FROM sessions WHERE user_id=? AND id=?",
            (current_user_id(), int(session_id)),
        )
    ).fetchone()
    return row["thread_id"] if row else None

async def move_runs(from_tid: str, to_tid: str) -> int:
    """把 from 线程下的 runs 迁到 to 线程（乐观新建会话窗口内的提问归位）。返回迁移条数。"""
    if not from_tid or from_tid == to_tid:
        return 0
    conn = await _conn()
    cur = await conn.execute(
        "UPDATE runs SET thread_id=? WHERE user_id=? AND thread_id=?",
        (to_tid, current_user_id(), from_tid),
    )
    await conn.commit()
    return cur.rowcount or 0

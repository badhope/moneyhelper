"""审计写入缓冲：内存环形队列 + 异步落库（SAVEPOINT 隔离主事务）。"""

from __future__ import annotations

import asyncio
import json
from collections import deque

from .provenance_model import ProvenanceEntry

_RING_CAPACITY = 10_000
_ring_buffer: deque[ProvenanceEntry] = deque(maxlen=_RING_CAPACITY)
_ring_lock = asyncio.Lock()

# 挂起的异步写入任务引用（供 flush_writes 等待）
_pending_tasks: set[asyncio.Task] = set()


# ---------------------------------------------------------------------------
# 内部写入函数
# ---------------------------------------------------------------------------


async def _persist_entry(entry: ProvenanceEntry) -> None:
    """把单条审计写入 SQLite（**独立连接**，不干扰主业务事务）。

    历史缺陷：这里原先走 db.execute()，也就是复用全局唯一写连接并 commit。
    当同一进程里有别的协程正在进行多语句事务时，这次 commit 会把对方
    未完成的事务一并提交，破坏原子性（并行测试下表现为偶发约束冲突）。
    审计是旁路数据，必须与业务事务彻底隔离。
    """
    from . import db

    try:
        # 用 SAVEPOINT 而不是独立连接：
        # - 独立连接在 Windows/aiosqlite 下会与主连接的写事务互相等待（实测超时）；
        # - 直接 db.execute() 会 commit 掉别人的半截事务（历史缺陷）；
        # - SAVEPOINT 只影响本层，出错可回滚到保存点，外层事务不受影响。
        conn = await db._conn()  # noqa: SLF001 — 必须拿连接本身，execute() 会 commit
        await conn.execute("SAVEPOINT provenance_write")
        try:
            await conn.execute(
                """INSERT INTO provenance_log
                   (id, timestamp, action, entity_type, entity_id,
                    before_json, after_json, source, username, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.id,
                    entry.timestamp,
                    entry.action,
                    entry.entity_type,
                    entry.entity_id,
                    json.dumps(entry.before, ensure_ascii=False)
                    if entry.before is not None
                    else None,
                    json.dumps(entry.after, ensure_ascii=False)
                    if entry.after is not None
                    else None,
                    entry.source,
                    entry.username,
                    json.dumps(entry.metadata, ensure_ascii=False)
                    if entry.metadata
                    else "{}",
                ),
            )
            await conn.execute("RELEASE provenance_write")
        except Exception:
            try:
                await conn.execute("ROLLBACK TO provenance_write")
                await conn.execute("RELEASE provenance_write")
            except Exception:  # noqa: BLE001 — 回滚失败也不影响主业务
                pass
            raise
    except Exception:
        # 审计写入失败不抛异常，以免影响主业务
        pass


def _schedule_persist(entry: ProvenanceEntry) -> None:
    """调度一条异步写入（fire-and-forget，不阻塞业务）。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # 无事件循环则跳过（审计非关键路径）
    task = loop.create_task(_persist_entry(entry))
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


def ring_size() -> int:
    """当前内存缓冲区中的记录数（供测试用）。"""
    return len(_ring_buffer)


def ring_capacity() -> int:
    """缓冲区容量上限。"""
    return _RING_CAPACITY


async def flush_writes() -> None:
    """等待挂起的异步写入全部完成（供测试用）。"""
    while _pending_tasks:
        await asyncio.wait(list(_pending_tasks), timeout=2.0)
        # _pending_tasks 在 task.add_done_callback 中自动清理

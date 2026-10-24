"""审计追踪：每个金额变动操作的完整来龙去脉。

记录：时间戳、操作类型、操作前快照、操作后快照、触发来源（API/MCP/Agent/Scheduler）、用户标识。

存储层：
- 内存环形缓冲区（deque，最新 10000 条）—— 快速查询最近审计
- SQLite provenance_log 表 —— 持久化，支持按实体/时间范围查询

写入策略：business-critical 操作调用 record_provenance，
通过 asyncio.create_task 异步写入，不阻塞主业务。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import deque
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class ProvenanceEntry:
    """一条审计记录：完整描述一次金额变动操作的来龙去脉。"""

    id: str  # UUID
    timestamp: str  # UTC ISO8601 时间戳
    action: str  # action 类型 (add_transaction/delete_position/etc.)
    entity_type: str  # 影响的实体类型 (transaction/position/budget/goal/etc.)
    entity_id: str  # 实体 ID
    before: dict | None  # 操作前状态摘要
    after: dict | None  # 操作后状态摘要
    source: str  # 触发来源 (api/mcp/agent/scheduler/undo)
    username: str  # 操作用户
    metadata: dict  # 额外上下文（chat thread id 等）

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "before": self.before,
            "after": self.after,
            "source": self.source,
            "username": self.username,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# 内存环形缓冲区
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

_current_actor: ContextVar[str] = ContextVar("prov_actor", default="system")


def set_request_actor(username: str) -> None:
    """请求中间件在鉴权后调用：本请求内所有审计记录默认归属该用户。"""
    _current_actor.set(username or "system")


async def record_provenance(
    action: str,
    entity_type: str,
    entity_id: str = "",
    before: dict | None = None,
    after: dict | None = None,
    source: str = "api",
    username: str = "",
    metadata: dict | None = None,
) -> ProvenanceEntry:
    """记录一条审计追踪记录。

    非阻塞：先入内存环形缓冲区，再异步入 SQLite。
    若队列满则丢弃最旧的消息（审计不应压垮业务）。

    Args:
        action:       操作类型 (如 add_position / delete_transaction)
        entity_type:  实体类型 (position/transaction/budget/goal/debt/subscription)
        entity_id:    实体 ID (如 600519 / goal_name 等)
        before:       操作前的状态摘要
        after:        操作后的状态摘要
        source:       触发来源 (api/mcp/agent/scheduler/undo)
        username:     操作用户
        metadata:     额外上下文 (如 chat_thread_id, request_id 等)

    Returns:
        生成的 ProvenanceEntry
    """
    username = username or _current_actor.get()

    entry = ProvenanceEntry(
        id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        before=_truncate_snapshot(before),
        after=_truncate_snapshot(after),
        source=source,
        username=username,
        metadata=metadata or {},
    )

    # 1. 入内存环形缓冲区
    async with _ring_lock:
        _ring_buffer.append(entry)

    # 2. 调度异步持久化（fire-and-forget，不阻塞业务）
    _schedule_persist(entry)

    return entry


async def get_provenances(
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 50,
    date_from: str = "",
    date_to: str = "",
) -> list[dict[str, Any]]:
    """查询审计记录。

    优先从内存缓冲区查（最近 10000 条），
    若条件需要更多或缓冲区未命中，则回退到 SQLite。

    Args:
        entity_type: 按实体类型过滤（可选）
        entity_id:   按实体 ID 过滤（可选）
        limit:       返回条数上限（默认 50）
        date_from:   起始时间（ISO 前缀比较，含）
        date_to:     截止时间（ISO 前缀比较，含）

    Returns:
        审计记录字典列表（最新在前）
    """
    # 简单过滤先从内存缓冲区查足量结果
    async with _ring_lock:
        entries = list(_ring_buffer)

    # 倒序（最新在前）
    entries.reverse()

    if entity_type:
        entries = [e for e in entries if e.entity_type == entity_type]
    if entity_id:
        entries = [e for e in entries if e.entity_id == entity_id]
    if date_from:
        entries = [e for e in entries if e.timestamp >= date_from]
    if date_to:
        # 只给日期（YYYY-MM-DD）时按"当天结束"处理，避免用户以为能查到当天却查不到
        upper = date_to if len(date_to) > 10 else date_to + "T23:59:59.999999+99:99"
        entries = [e for e in entries if e.timestamp <= upper]

    # 内存中已有满足条件的记录，直接返回（包含尚未持久化的最新数据）
    if entries:
        return [e.to_dict() for e in entries[:limit]]

    # 内存中无命中：从 SQLite 查询历史
    return await _query_sqlite(entity_type, entity_id, limit, date_from, date_to)


async def get_provenance_by_id(entry_id: str) -> dict[str, Any] | None:
    """按 ID 查询单条审计记录。先查内存，再查 SQLite。"""
    async with _ring_lock:
        for e in _ring_buffer:
            if e.id == entry_id:
                return e.to_dict()

    from . import db

    row = await db.fetch_one("SELECT * FROM provenance_log WHERE id = ?", (entry_id,))
    if row is None:
        return None
    return _row_to_dict(row)


async def _query_sqlite(
    entity_type: str | None,
    entity_id: str | None,
    limit: int,
    date_from: str = "",
    date_to: str = "",
) -> list[dict[str, Any]]:
    """从 SQLite 查询审计记录。"""
    from . import db

    conditions: list[str] = []
    params: list[Any] = []

    if entity_type:
        conditions.append("entity_type = ?")
        params.append(entity_type)
    if entity_id:
        conditions.append("entity_id = ?")
        params.append(entity_id)
    if date_from:
        conditions.append("timestamp >= ?")
        params.append(date_from)
    if date_to:
        upper = date_to if len(date_to) > 10 else date_to + "T23:59:59.999999+99:99"
        conditions.append("timestamp <= ?")
        params.append(upper)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    rows = await db.fetch_all(
        f"SELECT * FROM provenance_log {where} ORDER BY timestamp DESC LIMIT ?",
        tuple(params),
    )
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row: Any) -> dict[str, Any]:
    """把数据库行转为字典。"""

    def _safe_parse(val: str | None) -> dict | None:
        if not val:
            return None
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return None

    return {
        "id": row["id"],
        "timestamp": row["timestamp"],
        "action": row["action"],
        "entity_type": row["entity_type"],
        "entity_id": row["entity_id"],
        "before": _safe_parse(row["before_json"]),
        "after": _safe_parse(row["after_json"]),
        "source": row["source"],
        "username": row["username"],
        "metadata": _safe_parse(row["metadata_json"]) or {},
    }


def _truncate_snapshot(
    snapshot: dict | None, max_keys: int = 20, max_val_len: int = 200
) -> dict | None:
    """裁剪快照，防止单个审计记录过大。"""
    if snapshot is None:
        return None
    if not isinstance(snapshot, dict):
        # 防御：调用方误传非 dict 时不该把审计异常抛给主业务（调用点已改 await）
        return {"value": str(snapshot)[:max_val_len]}
    result = {}
    for i, (k, v) in enumerate(snapshot.items()):
        if i >= max_keys:
            break
        if isinstance(v, str) and len(v) > max_val_len:
            v = v[:max_val_len] + "…"
        result[k] = v
    return result


# ---------------------------------------------------------------------------
# 测试/维护辅助
# ---------------------------------------------------------------------------


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

"""审计写入口：记录归属当前请求用户，先入环形再异步落库。"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

from .provenance_model import ProvenanceEntry, _truncate_snapshot
from .provenance_ring import _ring_buffer, _ring_lock, _schedule_persist

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

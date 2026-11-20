"""审计查询：内存缓冲优先，未命中回退 SQLite 历史。"""

from __future__ import annotations

import json
from typing import Any

from .provenance_ring import _ring_buffer, _ring_lock


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

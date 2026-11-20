"""审计记录模型：一条记录描述一次金额变动的来龙去脉，快照做裁剪。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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

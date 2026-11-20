"""审计追踪门面：模型 / 环形缓冲与落库 / 写入 / 查询。

审计是旁路数据：写失败不抛、缓冲区满丢最旧，绝不影响主业务事务。
"""

from __future__ import annotations

__all__ = [
    "ProvenanceEntry",
    "flush_writes",
    "get_provenance_by_id",
    "get_provenances",
    "record_provenance",
    "ring_capacity",
    "ring_size",
    "set_request_actor",
]

from .provenance_model import ProvenanceEntry, _truncate_snapshot  # noqa: F401,E402
from .provenance_read import (  # noqa: F401,E402
    _query_sqlite,
    _row_to_dict,
    get_provenance_by_id,
    get_provenances,
)
from .provenance_ring import (  # noqa: F401,E402
    _RING_CAPACITY,
    _pending_tasks,
    _persist_entry,
    _ring_buffer,
    _ring_lock,
    _schedule_persist,
    flush_writes,
    ring_capacity,
    ring_size,
)
from .provenance_write import (  # noqa: F401,E402
    _current_actor,
    record_provenance,
    set_request_actor,
)

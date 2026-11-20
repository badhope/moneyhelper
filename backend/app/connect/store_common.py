"""连接中心持久化公共层：状态枚举、配额常量与 JSON 助手。"""

from __future__ import annotations

import json
from typing import Any

from ..logging_utils import get_logger

log = get_logger(__name__)

CONNECTION_STATUSES = ("unconfigured", "connected", "expiring", "error", "disabled")
INTENT_STATUSES = ("draft", "awaiting_confirm", "executed", "rejected", "expired")
JOB_STATUSES = ("queued", "running", "done", "failed")

PAIRING_TTL_MINUTES = 10
MAX_CONNECTIONS = 60
MAX_INTENTS = 500






def _dumps(v: Any) -> str:
    return json.dumps(v or {}, ensure_ascii=False, default=str)


def _loads(raw: Any) -> dict[str, Any]:
    try:
        val = json.loads(raw or "{}")
        return val if isinstance(val, dict) else {}
    except (TypeError, ValueError):
        return {}

"""老库迁移门面：补列 / 多租户 / 表重建 / 安全网。

从 _core.py 拆出。这些函数共享单写连接（`_core._db`），因此不持有自己的连接状态：
一律通过 `_core` 读取当前连接，测试夹具替换连接/路径后立即生效。
"""

from __future__ import annotations

from ..logging_utils import get_logger

log = get_logger(__name__)

__all__ = [
    "_migrate_add_columns",
    "_migrate_multitenant",
]

from .migrate_columns import _migrate_add_columns  # noqa: F401,E402 — 对外同名导出
from .migrate_rebuild import (  # noqa: F401,E402 — 对外同名导出
    _ensure_unique_by_tenant,
    _rebuild_composite,
    _rebuild_unique_as_composite,
    _rebuild_with_user_id,
)
from .migrate_safety import (  # noqa: F401,E402 — 对外同名导出
    _backup_db_consistent,
    _recover_stale_temp_tables,
)
from .migrate_tenant import (  # noqa: F401,E402 — 对外同名导出
    _COMPOSITE_MULTI,
    _COMPOSITE_TABLES,
    _TENANT_TABLES,
    _UNIQUE_COLS,
    _migrate_multitenant,
    _needs_multitenant,
    _pk_cols,
)

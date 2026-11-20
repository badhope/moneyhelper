"""持仓与自选门面：写入口 / 同名合并 / 自选股。

写入一律在事务内做「读旧值 → 校验 → 写快照 → 更新」，避免半截事务。
"""

from __future__ import annotations

__all__ = [
    "add_position",
    "add_watchlist",
    "append_position",
    "delete_position",
    "delete_watchlist",
    "list_watchlist",
    "merge_positions_by_name",
    "update_position",
]

from .portfolio_merge import merge_positions_by_name  # noqa: F401,E402
from .portfolio_write import (  # noqa: F401,E402
    _update_position_locked,
    add_position,
    append_position,
    delete_position,
    update_position,
)
from .watchlist import add_watchlist, delete_watchlist, list_watchlist  # noqa: F401,E402

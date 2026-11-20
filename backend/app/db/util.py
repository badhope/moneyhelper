"""db 通用小工具：行转 dict、分页上限。无连接、无状态。"""

from __future__ import annotations

from typing import Any


def row_dict(value: Any) -> dict[str, Any] | None:
    """aiosqlite.Row → dict；None 原样返回。

    gl / org / procurement 三个模块曾各写一份同名 `_row()`，逐字相同。
    """
    return dict(value) if value is not None else None

def _clamp_limit(limit: int, default: int = 50) -> int:
    """限制分页上限，防止 limit=9999999 导致内存爆炸。"""
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return default
    if n <= 0:
        return default
    return min(n, _LIST_LIMIT_MAX)

_LIST_LIMIT_MAX = 500

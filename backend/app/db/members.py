"""db 活跃成员与成员查询。

_active_member_id 是**进程级**状态（session_key → member_id），db 门面导出的是
同一个 dict 对象，测试对它 clear() 仍然生效。
"""

from __future__ import annotations

import uuid
from typing import Any

from . import _core

# 预定义配色池，轮流给新成员分配
_ACTIVE_KEY = "__default__"

_active_member_id: dict[str, int | None] = {}  # session_key → member_id

_AVATAR_COLORS = [
    "#b8891f",
    "#2e7d32",
    "#1565c0",
    "#6a1b9a",
    "#c62828",
    "#00838f",
    "#ef6c00",
    "#37474f",
    "#ad1457",
    "#3949ab",
]

def set_active_member(member_id: int | None, session_key: str = _ACTIVE_KEY) -> None:
    """切换当前活跃成员"""
    _active_member_id[session_key] = member_id

def get_active_member(session_key: str = _ACTIVE_KEY) -> int | None:
    """获取当前活跃成员 id"""
    return _active_member_id.get(session_key)

async def _fetch_member(member_id: int) -> dict[str, Any] | None:
    """根据 id 取成员信息（限当前租户，防跨租户按 id 探测）"""
    from .tenant import current_user_id

    conn = await _core._conn()
    cur = await conn.execute(
        "SELECT id, username, display_name, role, avatar_color, created_at "
        "FROM members WHERE user_id=? AND id=?",
        (current_user_id(), member_id),
    )
    row = await cur.fetchone()
    return dict(row) if row else None

def uuid_hex() -> str:
    return uuid.uuid4().hex

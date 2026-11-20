"""自选股：列表/添加/删除（代码只存符号，行情在 quotes 层）。"""

from __future__ import annotations

from typing import Any

from ._core import (
    _conn,
    _mark_user_data,
)
from .tenant import current_user_id

# --------------------------------------------------------------------------
# 自选行情（watchlist）
# --------------------------------------------------------------------------


async def list_watchlist() -> list[dict[str, Any]]:
    """当前租户的自选列表。"""
    conn = await _conn()
    cur = await conn.execute(
        "SELECT symbol,name,kind,created_at FROM watchlist WHERE user_id=? ORDER BY created_at",
        (current_user_id(),),
    )
    rows = await cur.fetchall()
    return [
        {"symbol": r[0], "name": r[1], "kind": r[2], "created_at": r[3]} for r in rows
    ]


async def add_watchlist(
    symbol: str, name: str = "", kind: str = "股票"
) -> dict[str, Any]:
    sym = str(symbol).strip().upper()
    if not sym:
        raise ValueError("代码不能为空")
    import datetime as _dt

    conn = await _conn()
    await conn.execute(
        "INSERT INTO watchlist(user_id,symbol,name,kind,created_at) VALUES(?,?,?,?,?)"
        " ON CONFLICT(user_id,symbol) DO UPDATE SET name=excluded.name, kind=excluded.kind",
        (
            current_user_id(),
            sym,
            str(name).strip()[:40] or sym,
            str(kind).strip()[:10] or "股票",
            _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        ),
    )
    await _mark_user_data(conn)
    await conn.commit()
    return {"ok": True, "symbol": sym}


async def delete_watchlist(symbol: str) -> dict[str, Any]:
    conn = await _conn()
    cur = await conn.execute(
        "DELETE FROM watchlist WHERE user_id=? AND symbol=?",
        (current_user_id(), symbol.strip().upper()),
    )
    await _mark_user_data(conn)
    await conn.commit()
    return {"ok": True, "deleted": cur.rowcount}

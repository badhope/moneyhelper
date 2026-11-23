"""只读分享快照：随机 token + 过期时间 + 可撤销，内容在创建时固化。"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta
from typing import Any

from ._core import _conn, get_write_lock
from .tenant import current_user_id

MAX_DAYS = 30


def _now() -> datetime:
    return datetime.now().astimezone()


async def create_share(
    thread_id: str,
    title: str,
    payload: dict[str, Any],
    expire_days: int = 7,
) -> dict[str, Any]:
    days = max(1, min(int(expire_days or 7), MAX_DAYS))
    token = secrets.token_urlsafe(24)
    created = _now()
    expires = created + timedelta(days=days)
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO shares(token,user_id,thread_id,title,payload_json,created_at,expires_at,revoked)"
            " VALUES(?,?,?,?,?,?,?,0)",
            (
                token,
                current_user_id(),
                thread_id,
                title[:120],
                json.dumps(payload, ensure_ascii=False),
                created.isoformat(timespec="seconds"),
                expires.isoformat(timespec="seconds"),
            ),
        )
        await conn.commit()
    return {
        "token": token,
        "path": f"/s/{token}",
        "expires_at": expires.isoformat(timespec="seconds"),
    }


async def get_share_public(token: str) -> dict[str, Any] | None:
    """公网只读访问：不读当前用户上下文，只看 token、过期与撤销位。"""
    raw = str(token or "").strip()
    if not raw or len(raw) > 128:
        return None
    conn = await _conn()
    cur = await conn.execute(
        "SELECT token,thread_id,title,payload_json,created_at,expires_at,revoked"
        " FROM shares WHERE token=?",
        (raw,),
    )
    row = await cur.fetchone()
    if not row or int(row["revoked"] or 0):
        return None
    try:
        exp = datetime.fromisoformat(str(row["expires_at"]))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=_now().tzinfo)
    except Exception:  # noqa: BLE001 — 时间戳损坏按失效处理
        return None
    if exp <= _now():
        return None
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except Exception:  # noqa: BLE001
        return None
    return {
        "token": row["token"],
        "thread_id": row["thread_id"],
        "title": row["title"] or "只读会话",
        "payload": payload if isinstance(payload, dict) else {},
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
    }


async def revoke_share(token: str) -> bool:
    conn = await _conn()
    async with get_write_lock():
        cur = await conn.execute(
            "UPDATE shares SET revoked=1 WHERE token=? AND user_id=?",
            (str(token or "").strip(), current_user_id()),
        )
        await conn.commit()
    return bool(cur.rowcount)

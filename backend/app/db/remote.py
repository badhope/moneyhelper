"""远程控制会话：签发一次性配对令牌、配对设备、校验/撤销设备令牌。

不存明文令牌，只存 SHA-256；设备令牌放在 HttpOnly cookie，撤销后下一次请求即失效。
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from ..timeutil import now_iso, now_local
from ._core import _conn, fetch_all, fetch_one, get_write_lock

REMOTE_COOKIE = "mh_remote"
PAIR_TTL_MINUTES = 10
DEFAULT_SESSION_HOURS = 12
MIN_SESSION_HOURS = 1
MAX_SESSION_HOURS = 168


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _expired(iso: str) -> bool:
    if not iso:
        return True
    try:
        return datetime.fromisoformat(iso) <= now_local()
    except ValueError:
        return True


def _device_name(ua: str, label: str) -> str:
    if label.strip():
        return label.strip()[:40]
    low = (ua or "").lower()
    if "iphone" in low:
        return "iPhone"
    if "ipad" in low:
        return "iPad"
    if "android" in low:
        return "Android 手机"
    if "macintosh" in low or "mac os" in low:
        return "Mac"
    if "windows" in low:
        return "Windows"
    return "手机"


def _public(row: dict[str, Any]) -> dict[str, Any]:
    paired = bool(row.get("paired_at"))
    revoked = bool(row.get("revoked_at"))
    expired = _expired(str(row.get("expires_at") or ""))
    return {
        "sid": row.get("sid"),
        "label": row.get("label") or "",
        "device_name": row.get("device_name") or "",
        "device_ua": row.get("device_ua") or "",
        "device_ip": row.get("device_ip") or "",
        "created_at": row.get("created_at") or "",
        "pair_expires_at": row.get("pair_expires_at") or "",
        "paired_at": row.get("paired_at") or "",
        "last_seen_at": row.get("last_seen_at") or "",
        "expires_at": row.get("expires_at") or "",
        "revoked_at": row.get("revoked_at") or "",
        "paired": paired,
        "revoked": revoked,
        "expired": expired,
        "active": (not revoked) and (not expired),
    }


async def create_remote_session(
    user_id: int,
    *,
    label: str = "",
    hours: int = DEFAULT_SESSION_HOURS,
) -> dict[str, Any]:
    """签发一条待配对会话，返回 sid / pair_token / 到期时间（令牌只回传一次）。"""
    hours = max(MIN_SESSION_HOURS, min(int(hours or DEFAULT_SESSION_HOURS), MAX_SESSION_HOURS))
    sid = uuid.uuid4().hex[:16]
    pair_token = secrets.token_urlsafe(32)
    created = now_local()
    pair_exp = created + timedelta(minutes=PAIR_TTL_MINUTES)
    expires = created + timedelta(hours=hours)
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO remote_sessions("
            "sid,user_id,label,pair_token_hash,pair_expires_at,created_at,expires_at"
            ") VALUES(?,?,?,?,?,?,?)",
            (
                sid,
                int(user_id),
                str(label or "").strip()[:40],
                _hash(pair_token),
                pair_exp.isoformat(timespec="seconds"),
                created.isoformat(timespec="seconds"),
                expires.isoformat(timespec="seconds"),
            ),
        )
        await conn.commit()
    return {
        "sid": sid,
        "pair_token": pair_token,
        "pair_expires_at": pair_exp.isoformat(timespec="seconds"),
        "expires_at": expires.isoformat(timespec="seconds"),
        "hours": hours,
    }


async def list_remote_sessions(user_id: int) -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT * FROM remote_sessions WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
        (int(user_id),),
    )
    return [_public(dict(r)) for r in rows]


async def get_remote_session(sid: str) -> dict[str, Any] | None:
    row = await fetch_one("SELECT * FROM remote_sessions WHERE sid=?", (str(sid or ""),))
    return dict(row) if row else None


async def pair_remote_session(
    sid: str,
    pair_token: str,
    *,
    ua: str = "",
    ip: str = "",
    device_label: str = "",
) -> dict[str, Any] | None:
    """用一次性配对令牌换设备令牌；已配对/过期/撤销/令牌错误一律返回 None。"""
    sid = str(sid or "").strip()
    token = str(pair_token or "").strip()
    if not sid or not token:
        return None
    row = await get_remote_session(sid)
    if not row or row.get("revoked_at") or _expired(str(row.get("expires_at") or "")):
        return None
    if row.get("paired_at"):
        return None
    if _expired(str(row.get("pair_expires_at") or "")):
        return None
    expected = str(row.get("pair_token_hash") or "")
    if not expected or not secrets.compare_digest(expected, _hash(token)):
        return None

    device_token = secrets.token_urlsafe(48)
    now = now_local().isoformat(timespec="seconds")
    conn = await _conn()
    async with get_write_lock():
        cur = await conn.execute(
            "UPDATE remote_sessions SET "
            "pair_token_hash='', paired_at=?, device_token_hash=?, "
            "device_name=?, device_ua=?, device_ip=?, last_seen_at=? "
            "WHERE sid=? AND paired_at='' AND revoked_at=''",
            (
                now,
                _hash(device_token),
                _device_name(ua, device_label),
                str(ua or "")[:300],
                str(ip or "")[:64],
                now,
                sid,
            ),
        )
        await conn.commit()
    if not cur.rowcount:
        return None
    return {"sid": sid, "device_token": device_token, "device_name": _device_name(ua, device_label)}


async def validate_remote_cookie(cookie_value: str) -> dict[str, Any] | None:
    """校验 cookie `sid.token`；有效时返回会话摘要，并低频刷新 last_seen_at。"""
    raw = str(cookie_value or "").strip()
    if "." not in raw:
        return None
    sid, token = raw.split(".", 1)
    if not sid or not token:
        return None
    row = await get_remote_session(sid)
    if not row or row.get("revoked_at") or _expired(str(row.get("expires_at") or "")):
        return None
    expected = str(row.get("device_token_hash") or "")
    if not expected or not secrets.compare_digest(expected, _hash(token)):
        return None

    last = str(row.get("last_seen_at") or "")
    now = now_local()
    try:
        stale = not last or (now - datetime.fromisoformat(last)).total_seconds() > 60
    except ValueError:
        stale = True
    if stale:
        conn = await _conn()
        async with get_write_lock():
            await conn.execute(
                "UPDATE remote_sessions SET last_seen_at=? WHERE sid=? AND revoked_at=''",
                (now.isoformat(timespec="seconds"), sid),
            )
            await conn.commit()

    return {
        "sid": sid,
        "user_id": int(row.get("user_id") or 0),
        "label": row.get("label") or "",
        "device_name": row.get("device_name") or "手机",
        "paired_at": row.get("paired_at") or "",
        "expires_at": row.get("expires_at") or "",
    }


async def rotate_remote_session(sid: str, user_id: int, *, hours: int = DEFAULT_SESSION_HOURS) -> dict[str, Any] | None:
    """刷新二维码：旧链接立即失效；若已配对，同时把已连设备踢下线。"""
    hours = max(MIN_SESSION_HOURS, min(int(hours or DEFAULT_SESSION_HOURS), MAX_SESSION_HOURS))
    row = await get_remote_session(sid)
    if not row or int(row.get("user_id") or 0) != int(user_id) or row.get("revoked_at"):
        return None
    pair_token = secrets.token_urlsafe(32)
    now = now_local()
    pair_exp = now + timedelta(minutes=PAIR_TTL_MINUTES)
    expires = now + timedelta(hours=hours)
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "UPDATE remote_sessions SET "
            "pair_token_hash=?, pair_expires_at=?, device_token_hash='', device_name='', "
            "device_ua='', device_ip='', paired_at='', last_seen_at='', expires_at=?, revoked_at='' "
            "WHERE sid=? AND user_id=?",
            (
                _hash(pair_token),
                pair_exp.isoformat(timespec="seconds"),
                expires.isoformat(timespec="seconds"),
                sid,
                int(user_id),
            ),
        )
        await conn.commit()
    return {
        "sid": sid,
        "pair_token": pair_token,
        "pair_expires_at": pair_exp.isoformat(timespec="seconds"),
        "expires_at": expires.isoformat(timespec="seconds"),
        "hours": hours,
    }


async def revoke_remote_session(sid: str, user_id: int | None = None) -> bool:
    sid = str(sid or "").strip()
    if not sid:
        return False
    conn = await _conn()
    async with get_write_lock():
        if user_id is None:
            cur = await conn.execute(
                "UPDATE remote_sessions SET revoked_at=? WHERE sid=? AND revoked_at=''",
                (now_iso(), sid),
            )
        else:
            cur = await conn.execute(
                "UPDATE remote_sessions SET revoked_at=? WHERE sid=? AND user_id=? AND revoked_at=''",
                (now_iso(), sid, int(user_id)),
            )
        await conn.commit()
    return bool(cur.rowcount)


async def revoke_all_remote_sessions(user_id: int) -> int:
    conn = await _conn()
    async with get_write_lock():
        cur = await conn.execute(
            "UPDATE remote_sessions SET revoked_at=? WHERE user_id=? AND revoked_at=''",
            (now_iso(), int(user_id)),
        )
        await conn.commit()
    return int(cur.rowcount or 0)


async def active_remote_count(user_id: int) -> int:
    rows = await list_remote_sessions(user_id)
    return sum(1 for r in rows if r["active"] and r["paired"])

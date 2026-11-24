"""外部投递通道存储（4.22.0）。

- 通道配置：`config_json` 存非敏感参数；密码/签名密钥走 vault，数据库只留密文。
- 投递记录：只记请求摘要与远端回执，不存整份账务底稿。
- vault 未激活时拒绝保存带密钥的通道，不降级明文。
"""

from __future__ import annotations

import json
from typing import Any

from .. import vault
from ..timeutil import now_iso as _now
from ._core import _conn, fetch_all, fetch_one, get_write_lock
from .tenant import current_user_id

ALLOWED_CHANNELS = ("smtp", "tax_gateway", "bank_gateway", "audit_gateway")
_STATUSES = {"pending", "accepted", "failed"}


def _json(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


async def save_channel(
    channel_id: str,
    *,
    label: str = "",
    config: dict[str, Any] | None = None,
    secret: dict[str, Any] | None = None,
    enabled: bool = False,
) -> dict[str, Any]:
    cid = str(channel_id or "").strip().lower()
    if cid not in ALLOWED_CHANNELS:
        raise ValueError(f"不支持的通道：{cid}")
    cfg = dict(config or {})
    try:
        cfg_json = json.dumps(cfg, ensure_ascii=False, default=str, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"通道参数无法序列化：{exc}") from None

    old = await fetch_one(
        "SELECT secret_enc FROM external_channels WHERE user_id=? AND channel_id=?",
        (current_user_id(), cid),
    )
    secret_enc = str(old["secret_enc"] if old else "")
    if secret is not None:
        if not isinstance(secret, dict) or not secret:
            raise ValueError("密钥不能为空；如需清除请使用删除通道")
        if not vault.is_active():
            raise RuntimeError(
                "VAULT_PASSPHRASE 未配置，拒绝保存通道密钥（不会降级为明文）"
            )
        payload = json.dumps(secret, ensure_ascii=False, default=str)
        secret_enc = await vault.encrypt_secret(payload)

    uid = current_user_id()
    now = _now()
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO external_channels(user_id,channel_id,label,config_json,secret_enc,enabled,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)"
            " ON CONFLICT(user_id,channel_id) DO UPDATE SET label=excluded.label,"
            " config_json=excluded.config_json, secret_enc=excluded.secret_enc,"
            " enabled=excluded.enabled, updated_at=excluded.updated_at",
            (
                uid,
                cid,
                str(label or cid)[:60],
                cfg_json,
                secret_enc,
                1 if enabled else 0,
                now,
                now,
            ),
        )
        await conn.commit()
    return (await get_channel(cid)) or {}


async def get_channel(channel_id: str) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT channel_id,label,config_json,secret_enc,enabled,last_test_at,last_test_ok,"
        "last_test_detail,created_at,updated_at FROM external_channels"
        " WHERE user_id=? AND channel_id=?",
        (current_user_id(), str(channel_id or "").strip().lower()),
    )
    return _public(row) if row else None


async def list_channels() -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT channel_id,label,config_json,secret_enc,enabled,last_test_at,last_test_ok,"
        "last_test_detail,created_at,updated_at FROM external_channels"
        " WHERE user_id=? ORDER BY channel_id",
        (current_user_id(),),
    )
    return [_public(row) for row in rows]


def _public(row: Any) -> dict[str, Any]:
    ok = row["last_test_ok"]
    return {
        "channel_id": str(row["channel_id"]),
        "label": str(row["label"] or ""),
        "config": _json(row["config_json"]),
        "enabled": bool(row["enabled"]),
        "configured": bool(row["secret_enc"]),
        "last_test_at": str(row["last_test_at"] or ""),
        "last_test_ok": None if ok is None else bool(ok),
        "last_test_detail": str(row["last_test_detail"] or ""),
        "created_at": str(row["created_at"] or ""),
        "updated_at": str(row["updated_at"] or ""),
    }


async def get_secret(channel_id: str) -> dict[str, Any] | None:
    cid = str(channel_id or "").strip().lower()
    row = await fetch_one(
        "SELECT secret_enc FROM external_channels WHERE user_id=? AND channel_id=?",
        (current_user_id(), cid),
    )
    if not row or not row["secret_enc"]:
        return None
    if not vault.is_active():
        raise RuntimeError("vault 未激活，无法解密通道密钥")
    plain = await vault.decrypt_secret(str(row["secret_enc"]))
    try:
        value = json.loads(plain)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"通道密钥密文损坏：{exc}") from None
    return value if isinstance(value, dict) else None


async def delete_channel(channel_id: str) -> bool:
    cid = str(channel_id or "").strip().lower()
    conn = await _conn()
    async with get_write_lock():
        cur = await conn.execute(
            "DELETE FROM external_channels WHERE user_id=? AND channel_id=?",
            (current_user_id(), cid),
        )
        await conn.commit()
    return bool(cur.rowcount)


async def mark_test(channel_id: str, ok: bool, detail: str) -> None:
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "UPDATE external_channels SET last_test_at=?,last_test_ok=?,last_test_detail=?,"
            "updated_at=? WHERE user_id=? AND channel_id=?",
            (
                _now(),
                1 if ok else 0,
                str(detail or "")[:240],
                _now(),
                current_user_id(),
                str(channel_id or "").strip().lower(),
            ),
        )
        await conn.commit()


async def get_delivery_by_key(
    channel_id: str, idempotency_key: str
) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT * FROM external_deliveries WHERE user_id=? AND channel_id=? AND idempotency_key=?",
        (
            current_user_id(),
            str(channel_id or "").strip().lower(),
            str(idempotency_key or ""),
        ),
    )
    return _delivery(row) if row else None


async def create_delivery(
    channel_id: str,
    kind: str,
    packet_id: str,
    source_hash: str,
    idempotency_key: str,
    *,
    recipient: str = "",
    request_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    uid = current_user_id()
    now = _now()
    summary = json.dumps(request_summary or {}, ensure_ascii=False, default=str)
    conn = await _conn()
    async with get_write_lock():
        cur = await conn.execute(
            "INSERT INTO external_deliveries(user_id,channel_id,kind,packet_id,source_hash,status,"
            "idempotency_key,recipient,request_summary,receipt_json,error_text,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,'{}','',?,?)"
            " ON CONFLICT(user_id,channel_id,idempotency_key) DO UPDATE SET status='pending',"
            " recipient=excluded.recipient, request_summary=excluded.request_summary,"
            " receipt_json='{}', error_text='', updated_at=excluded.updated_at",
            (
                uid,
                str(channel_id or "").strip().lower(),
                str(kind or ""),
                str(packet_id or ""),
                str(source_hash or ""),
                "pending",
                str(idempotency_key or ""),
                str(recipient or "")[:500],
                summary,
                now,
                now,
            ),
        )
        row_id = cur.lastrowid
        await conn.commit()
    row = await fetch_one("SELECT * FROM external_deliveries WHERE id=?", (row_id,))
    return _delivery(row) if row else {}


async def finish_delivery(
    delivery_id: int,
    *,
    status: str,
    receipt: dict[str, Any] | None = None,
    error: str = "",
) -> dict[str, Any]:
    if status not in _STATUSES - {"pending"}:
        raise ValueError("status 必须是 accepted 或 failed")
    receipt_json = json.dumps(receipt or {}, ensure_ascii=False, default=str)
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "UPDATE external_deliveries SET status=?,receipt_json=?,error_text=?,updated_at=? WHERE id=?",
            (status, receipt_json, str(error or "")[:500], _now(), int(delivery_id)),
        )
        await conn.commit()
    row = await fetch_one(
        "SELECT * FROM external_deliveries WHERE id=?", (int(delivery_id),)
    )
    return _delivery(row) if row else {}


async def list_deliveries(limit: int = 30) -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT * FROM external_deliveries WHERE user_id=? ORDER BY created_at DESC, id DESC LIMIT ?",
        (current_user_id(), max(1, min(int(limit or 30), 100))),
    )
    return [_delivery(row) for row in rows]


async def delivery_stats() -> dict[str, Any]:
    rows = await fetch_all(
        "SELECT status,COUNT(*) AS n FROM external_deliveries WHERE user_id=? GROUP BY status",
        (current_user_id(),),
    )
    stats = {"accepted": 0, "failed": 0, "pending": 0}
    for row in rows:
        if row["status"] in stats:
            stats[str(row["status"])] = int(row["n"])
    return stats


def _delivery(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "channel_id": str(row["channel_id"]),
        "kind": str(row["kind"]),
        "packet_id": str(row["packet_id"]),
        "source_hash": str(row["source_hash"]),
        "status": str(row["status"]),
        "recipient": str(row["recipient"] or ""),
        "request_summary": _json(row["request_summary"]),
        "receipt": _json(row["receipt_json"]),
        "error": str(row["error_text"] or ""),
        "created_at": str(row["created_at"] or ""),
        "updated_at": str(row["updated_at"] or ""),
    }

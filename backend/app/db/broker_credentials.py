"""券商凭据安全存取（v4.7）。

密钥字段整体序列化为 JSON 后交给 vault.encrypt_secret：
- 数据库里只有 `~salt:ciphertext`，不存单字段明文；
- list/get_masked 只返回字段名与 configured=true/false，不返回值；
- vault 未激活时拒绝保存（fail-closed），不自动降级成明文；
- broker_id 是白名单通道 id（futu/longport/tiger/ibkr/xtquant/easytrader），不接受任意 Python 类名。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .. import vault
from ._core import _conn, fetch_all, fetch_one, get_write_lock
from .tenant import current_user_id

ALLOWED_BROKER_IDS = ("futu", "longport", "tiger", "ibkr", "xtquant", "easytrader")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _meta(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


async def save_credentials(
    broker_id: str,
    secret: dict[str, Any],
    *,
    label: str = "",
    meta: dict[str, Any] | None = None,
    enabled: bool = False,
) -> dict[str, Any]:
    """保存券商凭据：没有 vault 主口令时直接拒绝。"""
    bid = str(broker_id or "").strip().lower()
    if bid not in ALLOWED_BROKER_IDS:
        raise ValueError(f"不支持的券商通道：{bid}")
    if not isinstance(secret, dict) or not secret:
        raise ValueError("至少需要一个凭据字段")
    if not vault.is_active():
        raise RuntimeError("VAULT_PASSPHRASE 未配置，拒绝保存券商凭据（不会降级为明文）")
    # 只允许 JSON 基本类型，防止把对象/文件句柄等意外序列化
    try:
        payload = json.dumps(secret, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"凭据无法序列化：{exc}") from None
    encrypted = await vault.encrypt_secret(payload)
    uid = current_user_id()
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO broker_credentials(user_id,broker_id,label,secret_enc,meta_json,enabled,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?)"
            " ON CONFLICT(user_id,broker_id) DO UPDATE SET label=excluded.label,secret_enc=excluded.secret_enc,"
            " meta_json=excluded.meta_json,enabled=excluded.enabled,updated_at=excluded.updated_at",
            (
                uid,
                bid,
                str(label or bid)[:60],
                encrypted,
                json.dumps(meta or {}, ensure_ascii=False, default=str),
                1 if enabled else 0,
                _now(),
                _now(),
            ),
        )
        await conn.commit()
    return (await get_masked(bid)) or {}


async def get_secret(broker_id: str) -> dict[str, Any] | None:
    """解密凭据给适配器进程内使用；调用方不得把返回值写日志/回包。"""
    bid = str(broker_id or "").strip().lower()
    row = await fetch_one(
        "SELECT secret_enc FROM broker_credentials WHERE user_id=? AND broker_id=?",
        (current_user_id(), bid),
    )
    if not row or not row["secret_enc"]:
        return None
    if not vault.is_active():
        raise RuntimeError("VAULT_PASSPHRASE 未配置，无法解密券商凭据")
    plain = await vault.decrypt_secret(str(row["secret_enc"]))
    try:
        value = json.loads(plain)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"券商凭据密文损坏：{exc}") from None
    return value if isinstance(value, dict) else None


async def get_masked(broker_id: str) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT user_id,broker_id,label,meta_json,enabled,created_at,updated_at,secret_enc"
        " FROM broker_credentials WHERE user_id=? AND broker_id=?",
        (current_user_id(), str(broker_id or "").strip().lower()),
    )
    if not row:
        return None
    meta = _meta(row["meta_json"])
    return {
        "broker_id": row["broker_id"],
        "label": row["label"],
        "meta": meta,
        "enabled": bool(row["enabled"]),
        "configured": bool(row["secret_enc"]),
        "secret_fields": [],  # 不解密；字段名通过 get_secret 内部供 probe 使用
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def list_masked() -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT broker_id,label,meta_json,enabled,created_at,updated_at,secret_enc"
        " FROM broker_credentials WHERE user_id=? ORDER BY updated_at DESC",
        (current_user_id(),),
    )
    return [
        {
            "broker_id": r["broker_id"],
            "label": r["label"],
            "meta": _meta(r["meta_json"]),
            "enabled": bool(r["enabled"]),
            "configured": bool(r["secret_enc"]),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


async def delete_credentials(broker_id: str) -> bool:
    conn = await _conn()
    async with get_write_lock():
        cur = await conn.execute(
            "DELETE FROM broker_credentials WHERE user_id=? AND broker_id=?",
            (current_user_id(), str(broker_id or "").strip().lower()),
        )
        await conn.commit()
    return cur.rowcount > 0

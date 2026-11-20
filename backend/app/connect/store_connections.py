"""连接账户 CRUD：状态机、配额与同步时间戳。"""

from __future__ import annotations

from typing import Any

from ..db._core import _conn, _mark_user_data, fetch_all, fetch_one, get_write_lock
from ..db.tenant import current_user_id
from ..timeutil import new_id as _new_id
from ..timeutil import now_iso as _now
from .catalog import get_connector
from .store_common import (
    CONNECTION_STATUSES,
    MAX_CONNECTIONS,
    _dumps,
    _loads,
    log,
)


async def list_connections() -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT * FROM connect_accounts WHERE user_id=? ORDER BY created_at ASC",
        (current_user_id(),),
    )
    out = []
    for r in rows:
        row = dict(r)
        row["meta"] = _loads(row.pop("meta_json", "{}"))
        out.append(row)
    return out


async def get_connection(cid: str) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT * FROM connect_accounts WHERE user_id=? AND id=?",
        (current_user_id(), str(cid)),
    )
    if not row:
        return None
    out = dict(row)
    out["meta"] = _loads(out.pop("meta_json", "{}"))
    return out


async def create_connection(
    connector_id: str,
    label: str = "",
    account_ref: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """新增一条连接。connector_id 必须存在于内置目录，否则拒绝（防脏数据）。"""
    connector = get_connector(connector_id)
    if connector is None:
        raise ValueError(f"未知的连接器：{connector_id}")

    uid = current_user_id()
    rows = await fetch_all(
        "SELECT id FROM connect_accounts WHERE user_id=?", (uid,)
    )
    if len(rows) >= MAX_CONNECTIONS:
        raise ValueError(f"最多 {MAX_CONNECTIONS} 个连接")

    # 同一连接器允许建多条（多张卡/多个账户），但标签不能完全相同
    clean_label = (label or connector["name"]).strip()[:40] or connector["name"]
    dup = await fetch_one(
        "SELECT id FROM connect_accounts WHERE user_id=? AND connector_id=? AND label=?",
        (uid, connector["id"], clean_label),
    )
    if dup:
        raise ValueError(f"已存在同名连接：{clean_label}")

    cid = _new_id("conn")
    now = _now()
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO connect_accounts"
            "(user_id,id,connector_id,label,kind,status,account_ref,meta_json,last_sync_at,last_error,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                uid,
                cid,
                connector["id"],
                clean_label,
                connector["kind"],
                "unconfigured",
                str(account_ref or "").strip()[:60],
                _dumps(meta),
                "",
                "",
                now,
                now,
            ),
        )
        await _mark_user_data(conn)
        await conn.commit()
    log.info("connect.created id=%s connector=%s", cid, connector["id"])
    return (await get_connection(cid)) or {}


async def update_connection(cid: str, patch: dict[str, Any]) -> dict[str, Any]:
    """更新连接：状态 / 标签 / 备注 / 错误信息。未知字段忽略。"""
    cur = await get_connection(cid)
    if cur is None:
        raise ValueError("连接不存在")

    status = str(patch.get("status") or cur["status"]).strip()
    if status not in CONNECTION_STATUSES:
        raise ValueError(f"状态只能是 {'/'.join(CONNECTION_STATUSES)}")

    label = str(patch.get("label") or cur["label"]).strip()[:40] or cur["label"]
    account_ref = str(patch.get("account_ref") or cur.get("account_ref") or "").strip()[:60]
    meta = patch.get("meta")
    meta_json = _dumps({**(cur.get("meta") or {}), **meta}) if isinstance(meta, dict) else _dumps(cur.get("meta") or {})
    last_error = str(patch.get("last_error", cur.get("last_error") or ""))[:300]

    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "UPDATE connect_accounts SET label=?, status=?, account_ref=?, meta_json=?, last_error=?, updated_at=?"
            " WHERE user_id=? AND id=?",
            (label, status, account_ref, meta_json, last_error, _now(), current_user_id(), cid),
        )
        await conn.commit()
    return (await get_connection(cid)) or {}


async def delete_connection(cid: str) -> bool:
    conn = await _conn()
    async with get_write_lock():
        cur = await conn.execute(
            "DELETE FROM connect_accounts WHERE user_id=? AND id=?", (current_user_id(), cid)
        )
        await conn.commit()
        return cur.rowcount > 0


async def touch_sync(cid: str, ok: bool, error: str = "") -> None:
    """记录一次同步结果：成功刷新 last_sync_at 并置 connected，失败置 error。"""
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "UPDATE connect_accounts SET status=?, last_sync_at=?, last_error=?, updated_at=?"
            " WHERE user_id=? AND id=?",
            (
                "connected" if ok else "error",
                _now() if ok else "",
                "" if ok else error[:300],
                _now(),
                current_user_id(),
                cid,
            ),
        )
        await conn.commit()

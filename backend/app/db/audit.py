"""审计与附件域：审计日志 + 附件元数据。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from ._core import (
    _clamp_limit,
    _conn,
    _mark_user_data,
    fetch_all,
)
from .tenant import current_user_id

# --------------------------------------------------------------------------
# 审计日志（P2 金融级治理）
# --------------------------------------------------------------------------


def _entry_hash(
    prev_hash: str,
    *,
    ts: str,
    action: str,
    method: str,
    path: str,
    status: int,
    actor: str,
    detail: str,
    duration_ms: int,
) -> str:
    """计算审计条目的 SHA-256；字段顺序固定，跨版本必须保持一致。"""
    payload = json.dumps(
        [ts, action, method, path, status, actor, detail, duration_ms],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256((prev_hash + payload).encode("utf-8")).hexdigest()


async def add_audit_log(
    action: str,
    method: str,
    path: str,
    status: int,
    actor: str = "",
    detail: str = "",
    duration_ms: int = 0,
    user_id: int | None = None,
) -> dict[str, Any]:
    """写一条审计日志。action: WRITE / READ_SENSITIVE / AUTH。

    user_id 显式传入时优先使用：中间件在 call_next 之后写审计时，请求级的
    租户 ContextVar 可能已经被重置为 0，不能依赖 current_user_id()。
    """
    conn = await _conn()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    uid = current_user_id() if user_id is None else int(user_id)
    ts_s = now
    action_s = str(action)[:20]
    method_s = str(method)[:8]
    path_s = str(path)[:200]
    status_i = int(status or 0)
    actor_s = str(actor)[:64]
    detail_s = str(detail)[:500]
    duration_i = int(duration_ms or 0)
    # SAVEPOINT 隔离：审计是旁路数据，不能把调用方未完成的事务一并 commit
    # （专家评审 P0-9 实测：批量入账失败时审计的 commit 会把前两条落库）。
    await conn.execute("SAVEPOINT audit_write")
    try:
        cur = await conn.execute(
            "SELECT entry_hash FROM audit_logs"
            " WHERE user_id=? AND entry_hash<>'' ORDER BY id DESC LIMIT 1",
            (uid,),
        )
        row = await cur.fetchone()
        prev_hash = str(row["entry_hash"]) if row else ""
        entry_hash = _entry_hash(
            prev_hash,
            ts=ts_s,
            action=action_s,
            method=method_s,
            path=path_s,
            status=status_i,
            actor=actor_s,
            detail=detail_s,
            duration_ms=duration_i,
        )
        await conn.execute(
            "INSERT INTO audit_logs(user_id,ts,action,method,path,status,actor,detail,"
            "duration_ms,prev_hash,entry_hash)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                uid,
                ts_s,
                action_s,
                method_s,
                path_s,
                status_i,
                actor_s,
                detail_s,
                duration_i,
                prev_hash,
                entry_hash,
            ),
        )
        await conn.execute("RELEASE audit_write")
    except Exception:
        try:
            await conn.execute("ROLLBACK TO audit_write")
            await conn.execute("RELEASE audit_write")
        except Exception:  # noqa: BLE001
            pass
        raise
    return {"ok": True}


async def list_audit_logs(
    limit: int = 200, action: str | None = None
) -> list[dict[str, Any]]:
    """列审计日志（新→旧），可按类型过滤。"""
    clamped = _clamp_limit(limit, default=200)
    if action:
        rows = await fetch_all(
            "SELECT * FROM audit_logs WHERE user_id=? AND action=? ORDER BY id DESC LIMIT ?",
            (current_user_id(), str(action)[:20], clamped),
        )
    else:
        rows = await fetch_all(
            "SELECT * FROM audit_logs WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (current_user_id(), clamped),
        )
    return rows


async def clear_audit_logs() -> dict[str, Any]:
    conn = await _conn()
    cur = await conn.execute(
        "DELETE FROM audit_logs WHERE user_id=?", (current_user_id(),)
    )
    await conn.commit()
    return {"ok": True, "deleted": cur.rowcount or 0}


async def verify_audit_chain(user_id: int | None = None) -> dict[str, Any]:
    """校验当前租户的审计哈希链。

    返回 {ok, checked, legacy_rows, head, broken_at?, reason?}。
    旧库历史行没有 entry_hash，作为 legacy 前缀跳过；从第一条有哈希的记录起
    逐条验证 prev_hash 与重算哈希。任何字段被改动、插入或删除中间行都会在
    断点处被检出。注意：没有外部锚点时，删除末尾记录无法被本函数发现——
    企业部署应把 head 定期写入独立存储/WORM 日志。
    """
    uid = current_user_id() if user_id is None else int(user_id)
    rows = await fetch_all(
        "SELECT id,ts,action,method,path,status,actor,detail,duration_ms,"
        "prev_hash,entry_hash FROM audit_logs WHERE user_id=? ORDER BY id",
        (uid,),
    )
    prev = ""
    checked = 0
    legacy = 0
    for r in rows:
        entry_hash = str(r.get("entry_hash") or "")
        if not entry_hash:
            legacy += 1
            continue
        expected = _entry_hash(
            prev,
            ts=str(r.get("ts") or ""),
            action=str(r.get("action") or ""),
            method=str(r.get("method") or ""),
            path=str(r.get("path") or ""),
            status=int(r.get("status") or 0),
            actor=str(r.get("actor") or ""),
            detail=str(r.get("detail") or ""),
            duration_ms=int(r.get("duration_ms") or 0),
        )
        if str(r.get("prev_hash") or "") != prev:
            return {
                "ok": False,
                "checked": checked,
                "legacy_rows": legacy,
                "broken_at": int(r.get("id") or 0),
                "reason": "prev_hash 与上一条不一致（可能删除或插入了记录）",
            }
        if entry_hash != expected:
            return {
                "ok": False,
                "checked": checked,
                "legacy_rows": legacy,
                "broken_at": int(r.get("id") or 0),
                "reason": "entry_hash 与内容重算不一致（记录被修改）",
            }
        prev = entry_hash
        checked += 1
    return {
        "ok": True,
        "checked": checked,
        "legacy_rows": legacy,
        "head": prev,
    }


# --------------------------------------------------------------------------
# 附件（P2 能力扩展）
# --------------------------------------------------------------------------


async def list_attachments(limit: int = 50) -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT id, filename, kind, size, indexed, created_at FROM attachments"
        " WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (current_user_id(), _clamp_limit(limit)),
    )
    return rows


async def list_indexed_attachments() -> list[dict[str, Any]]:
    """已加入知识库的附件（含正文，供检索切块）。"""
    return await fetch_all(
        "SELECT id, filename, kind, content FROM attachments"
        " WHERE user_id=? AND indexed=1 AND content <> '' ORDER BY id DESC",
        (current_user_id(),),
    )


async def set_attachment_indexed(att_id: int, indexed: bool) -> dict[str, Any]:
    conn = await _conn()
    cur = await conn.execute(
        "UPDATE attachments SET indexed=? WHERE user_id=? AND id=?",
        (1 if indexed else 0, current_user_id(), int(att_id)),
    )
    await conn.commit()
    if cur.rowcount == 0:
        raise ValueError("附件不存在")
    return {"ok": True, "id": int(att_id), "indexed": bool(indexed)}


async def add_attachment(
    filename: str, kind: str, size: int, content: str
) -> dict[str, Any]:
    conn = await _conn()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    cur = await conn.execute(
        "INSERT INTO attachments(user_id,filename,kind,size,content,created_at) VALUES(?,?,?,?,?,?)",
        (
            current_user_id(),
            str(filename)[:200],
            str(kind)[:20] or "text",
            int(size or 0),
            content[:6000],
            now,
        ),
    )
    await _mark_user_data(conn)
    await conn.commit()
    return {"ok": True, "id": cur.lastrowid}


async def get_attachment(att_id: int) -> dict[str, Any] | None:
    rows = await fetch_all(
        "SELECT * FROM attachments WHERE user_id=? AND id=?",
        (current_user_id(), int(att_id)),
    )
    return rows[0] if rows else None


async def delete_attachment(att_id: int) -> dict[str, Any]:
    conn = await _conn()
    cur = await conn.execute(
        "DELETE FROM attachments WHERE user_id=? AND id=?",
        (current_user_id(), int(att_id)),
    )
    await _mark_user_data(conn)
    await conn.commit()
    return {"ok": True, "deleted": cur.rowcount or 0}

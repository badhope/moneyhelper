"""同步任务：队列/执行/收尾三段式事件记录。"""

from __future__ import annotations

from typing import Any

from ..db._core import _conn, fetch_all, get_write_lock
from ..db.tenant import current_user_id
from ..timeutil import new_id as _new_id
from ..timeutil import now_iso as _now
from .catalog import get_connector
from .store_common import (
    _dumps,
    _loads,
)


async def create_job(connector_id: str, kind: str = "sync", message: str = "") -> dict[str, Any]:
    connector = get_connector(connector_id)
    if connector is None:
        raise ValueError(f"未知的连接器：{connector_id}")
    jid = _new_id("job")
    now = _now()
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO connect_jobs"
            "(user_id,id,connector_id,kind,status,progress,message,result_json,created_at,finished_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (current_user_id(), jid, connector["id"], str(kind)[:20], "queued", 0.0, str(message)[:200], "{}", now, ""),
        )
        await conn.commit()
    return {
        "id": jid,
        "connector_id": connector["id"],
        "kind": str(kind),
        "status": "queued",
        "progress": 0.0,
        "message": str(message),
        "created_at": now,
    }


async def finish_job(
    job_id: str,
    ok: bool,
    message: str = "",
    result: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "UPDATE connect_jobs SET status=?, progress=?, message=?, result_json=?, finished_at=?"
            " WHERE user_id=? AND id=?",
            (
                "done" if ok else "failed",
                1.0 if ok else 0.0,
                str(message)[:300],
                _dumps(result),
                _now(),
                current_user_id(),
                job_id,
            ),
        )
        await conn.commit()
    rows = await fetch_all(
        "SELECT * FROM connect_jobs WHERE user_id=? AND id=?", (current_user_id(), job_id)
    )
    if not rows:
        return None
    out = dict(rows[0])
    out["result"] = _loads(out.pop("result_json", "{}"))
    return out


async def list_jobs(limit: int = 30) -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT * FROM connect_jobs WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
        (current_user_id(), max(1, min(int(limit), 200))),
    )
    out = []
    for r in rows:
        row = dict(r)
        row["result"] = _loads(row.pop("result_json", "{}"))
        out.append(row)
    return out

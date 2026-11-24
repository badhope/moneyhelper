"""自动化运行台账持久化：定时触发与手动补跑共用同一份事实记录。"""

from __future__ import annotations

import json
import uuid
from typing import Any

from ..timeutil import now_iso
from ._core import fetch_all, fetch_one, write_txn
from .tenant import current_tenant_id, current_user_id

MAX_RUNS = 200


def _decode(row: Any) -> dict[str, Any]:
    out = dict(row)
    try:
        out["steps"] = json.loads(out.pop("steps_json") or "[]")
    except (TypeError, ValueError):
        out["steps"] = []
    return out


async def start_run(
    workflow: str,
    workflow_name: str,
    *,
    trigger: str = "manual",
    idempotency_key: str = "",
) -> dict[str, Any]:
    """创建运行记录；同租户同幂等键已存在时直接返回旧记录。"""
    tid, uid = current_tenant_id(), current_user_id()
    if idempotency_key:
        row = await fetch_one(
            "SELECT * FROM automation_runs WHERE tenant_id=? AND idempotency_key=?",
            (tid, idempotency_key),
        )
        if row:
            return _decode(row)
    rid = uuid.uuid4().hex[:12]
    now = now_iso()
    async with write_txn() as conn:
        await conn.execute(
            "INSERT INTO automation_runs"
            "(id,tenant_id,user_id,workflow,workflow_name,trigger,status,idempotency_key,"
            "started_at,finished_at,duration_ms,steps_json,error,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rid,
                tid,
                uid,
                workflow,
                workflow_name,
                trigger,
                "running",
                idempotency_key,
                now,
                "",
                0,
                "[]",
                "",
                now,
            ),
        )
    return {
        "id": rid,
        "tenant_id": tid,
        "user_id": uid,
        "workflow": workflow,
        "workflow_name": workflow_name,
        "trigger": trigger,
        "status": "running",
        "idempotency_key": idempotency_key,
        "started_at": now,
        "finished_at": "",
        "duration_ms": 0,
        "steps": [],
        "error": "",
        "created_at": now,
    }


async def finish_run(
    run_id: str,
    *,
    status: str,
    duration_ms: int,
    steps: list[dict[str, Any]],
    error: str = "",
) -> dict[str, Any] | None:
    now = now_iso()
    async with write_txn() as conn:
        await conn.execute(
            "UPDATE automation_runs SET status=?,finished_at=?,duration_ms=?,steps_json=?,error=?"
            " WHERE id=? AND tenant_id=?",
            (
                status,
                now,
                int(duration_ms),
                json.dumps(steps, ensure_ascii=False),
                error[:500],
                run_id,
                current_tenant_id(),
            ),
        )
    return await get_run(run_id)


async def get_run(run_id: str) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT * FROM automation_runs WHERE id=? AND tenant_id=?",
        (run_id, current_tenant_id()),
    )
    return _decode(row) if row else None


async def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT * FROM automation_runs WHERE tenant_id=? ORDER BY created_at DESC LIMIT ?",
        (current_tenant_id(), max(1, min(int(limit), MAX_RUNS))),
    )
    return [_decode(r) for r in rows]


async def prune_runs() -> None:
    """只保留最近 MAX_RUNS 条，避免审计台账无限增长。"""
    rows = await fetch_all(
        "SELECT id FROM automation_runs WHERE tenant_id=? ORDER BY created_at DESC",
        (current_tenant_id(),),
    )
    drop = [r["id"] for r in rows[MAX_RUNS:]]
    if not drop:
        return
    async with write_txn() as conn:
        for rid in drop:
            await conn.execute(
                "DELETE FROM automation_runs WHERE id=? AND tenant_id=?",
                (rid, current_tenant_id()),
            )
            # 运行被裁掉后，指向它的告警也删掉；否则“重放”会指向不存在的 run。
            await conn.execute(
                "DELETE FROM automation_alerts WHERE run_id=? AND tenant_id=?",
                (rid, current_tenant_id()),
            )


def _decode_alert(row: Any) -> dict[str, Any]:
    out = dict(row)
    out["acknowledged"] = bool(out.get("acknowledged_at"))
    return out


async def create_alert(
    run_id: str,
    workflow: str,
    *,
    severity: str,
    message: str,
) -> dict[str, Any]:
    """失败/部分失败的运行各留一条告警；同一 run 重放不重复写。"""
    tid, uid = current_tenant_id(), current_user_id()
    row = await fetch_one(
        "SELECT * FROM automation_alerts WHERE tenant_id=? AND run_id=?",
        (tid, run_id),
    )
    if row:
        return _decode_alert(row)
    aid = uuid.uuid4().hex[:12]
    now = now_iso()
    async with write_txn() as conn:
        await conn.execute(
            "INSERT INTO automation_alerts"
            "(id,tenant_id,user_id,run_id,workflow,severity,message,created_at,acknowledged_at)"
            " VALUES(?,?,?,?,?,?,?,?,'')",
            (aid, tid, uid, run_id, workflow, severity, message[:300], now),
        )
    return await get_alert(aid) or {
        "id": aid,
        "run_id": run_id,
        "workflow": workflow,
        "severity": severity,
        "message": message[:300],
        "created_at": now,
        "acknowledged_at": "",
        "acknowledged": False,
    }


async def get_alert(alert_id: str) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT * FROM automation_alerts WHERE id=? AND tenant_id=?",
        (alert_id, current_tenant_id()),
    )
    return _decode_alert(row) if row else None


async def list_alerts(limit: int = 20, *, unread_only: bool = False) -> list[dict[str, Any]]:
    where = "tenant_id=?" + (" AND acknowledged_at=''" if unread_only else "")
    rows = await fetch_all(
        "SELECT * FROM automation_alerts WHERE "
        + where
        + " ORDER BY created_at DESC LIMIT ?",
        (current_tenant_id(), max(1, min(int(limit), 200))),
    )
    return [_decode_alert(r) for r in rows]


async def unread_alert_count() -> int:
    row = await fetch_one(
        "SELECT COUNT(*) AS n FROM automation_alerts WHERE tenant_id=? AND acknowledged_at=''",
        (current_tenant_id(),),
    )
    return int(row["n"]) if row else 0


async def acknowledge_alert(alert_id: str) -> dict[str, Any] | None:
    now = now_iso()
    async with write_txn() as conn:
        await conn.execute(
            "UPDATE automation_alerts SET acknowledged_at=? WHERE id=? AND tenant_id=?",
            (now, alert_id, current_tenant_id()),
        )
    return await get_alert(alert_id)


async def latest_scheduled_run(workflow: str, since: str) -> dict[str, Any] | None:
    """查某个工作流在 since 之后最近一次定时/补偿运行；用于启动补偿判定。"""
    row = await fetch_one(
        "SELECT * FROM automation_runs WHERE tenant_id=? AND workflow=?"
        " AND trigger IN ('schedule','catchup') AND started_at>=?"
        " ORDER BY started_at DESC LIMIT 1",
        (current_tenant_id(), workflow, since),
    )
    return _decode(row) if row else None

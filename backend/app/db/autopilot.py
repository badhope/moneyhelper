"""托管策略与决策持久化（4.23.0）。

策略是“用户预先授权的规则”，不是模型自行决定；决策表保存每次评估结果。
写入走统一锁，读取按当前用户隔离。
"""

from __future__ import annotations

import json
from typing import Any

from ..timeutil import now_iso as _now
from ._core import _conn, fetch_all, fetch_one, get_write_lock
from .tenant import current_user_id

ALLOWED_MODES = ("manual", "assist", "auto")
MAX_DECISIONS = 300


def _json(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _policy(row: Any) -> dict[str, Any]:
    return {
        "action_key": str(row["action_key"]),
        "mode": str(row["mode"] or "manual"),
        "enabled": bool(row["enabled"]),
        "config": _json(row["config_json"]),
        "updated_at": str(row["updated_at"] or ""),
    }


def _decision(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "action_key": str(row["action_key"]),
        "mode": str(row["mode"] or "manual"),
        "decision": str(row["decision"] or ""),
        "summary": _json(row["summary_json"]),
        "created_at": str(row["created_at"] or ""),
    }


async def list_policies() -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT * FROM autopilot_policies WHERE user_id=? ORDER BY action_key",
        (current_user_id(),),
    )
    return [_policy(row) for row in rows]


async def get_policy(action_key: str) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT * FROM autopilot_policies WHERE user_id=? AND action_key=?",
        (current_user_id(), str(action_key)),
    )
    return _policy(row) if row else None


async def save_policy(
    action_key: str,
    *,
    mode: str,
    enabled: bool,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    key = str(action_key or "").strip()
    if not key:
        raise ValueError("动作不能为空")
    mode_value = str(mode or "manual").strip().lower()
    if mode_value not in ALLOWED_MODES:
        raise ValueError("托管模式必须是 manual / assist / auto")
    cfg = dict(config or {})
    try:
        cfg_json = json.dumps(cfg, ensure_ascii=False, default=str, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"托管规则无法序列化：{exc}") from None
    uid = current_user_id()
    now = _now()
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO autopilot_policies(user_id,action_key,mode,enabled,config_json,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?)"
            " ON CONFLICT(user_id,action_key) DO UPDATE SET mode=excluded.mode,"
            " enabled=excluded.enabled, config_json=excluded.config_json, updated_at=excluded.updated_at",
            (uid, key, mode_value, 1 if enabled else 0, cfg_json, now, now),
        )
        await conn.commit()
    row = await fetch_one(
        "SELECT * FROM autopilot_policies WHERE user_id=? AND action_key=?",
        (uid, key),
    )
    if not row:
        raise RuntimeError("托管策略保存失败")
    return _policy(row)


async def record_decision(
    action_key: str,
    *,
    mode: str,
    decision: str,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(summary or {})
    try:
        summary_json = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        summary_json = "{}"
    now = _now()
    conn = await _conn()
    async with get_write_lock():
        cursor = await conn.execute(
            "INSERT INTO autopilot_decisions(user_id,action_key,mode,decision,summary_json,created_at)"
            " VALUES(?,?,?,?,?,?)",
            (
                current_user_id(),
                str(action_key),
                str(mode or "manual"),
                str(decision),
                summary_json,
                now,
            ),
        )
        await conn.commit()
        new_id = int(cursor.lastrowid or 0)
        await conn.execute(
            "DELETE FROM autopilot_decisions WHERE user_id=? AND id NOT IN ("
            " SELECT id FROM autopilot_decisions WHERE user_id=? ORDER BY id DESC LIMIT ?)",
            (current_user_id(), current_user_id(), MAX_DECISIONS),
        )
        await conn.commit()
    row = await fetch_one(
        "SELECT * FROM autopilot_decisions WHERE id=? AND user_id=?",
        (new_id, current_user_id()),
    )
    if not row:
        raise RuntimeError("托管决策保存失败")
    return _decision(row)


async def list_decisions(limit: int = 30) -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT * FROM autopilot_decisions WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (current_user_id(), max(1, min(int(limit or 30), 100))),
    )
    return [_decision(row) for row in rows]


async def decision_stats() -> dict[str, Any]:
    rows = await fetch_all(
        "SELECT decision, COUNT(*) AS n FROM autopilot_decisions WHERE user_id=? GROUP BY decision",
        (current_user_id(),),
    )
    stats = {str(row["decision"]): int(row["n"]) for row in rows}
    return {
        "total": sum(stats.values()),
        "executed": stats.get("executed", 0),
        "awaiting": stats.get("awaiting", 0),
        "blocked": stats.get("blocked", 0),
        "manual": stats.get("manual", 0),
    }

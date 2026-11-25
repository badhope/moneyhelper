"""电商测算场景持久化（4.23.0）。"""

from __future__ import annotations

import json
from typing import Any

from ..timeutil import now_iso as _now
from ._core import _conn, fetch_all, fetch_one, get_write_lock, json_dict
from .tenant import current_user_id


def _row(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "name": str(row["name"]),
        "input": json_dict(row["input_json"]),
        "result": json_dict(row["result_json"]),
        "created_at": str(row["created_at"] or ""),
    }


async def save_scenario(
    name: str, input_data: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    label = str(name or "").strip()[:80]
    if not label:
        raise ValueError("场景名称不能为空")
    try:
        input_json = json.dumps(input_data, ensure_ascii=False, default=str)
        result_json = json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"测算场景无法序列化：{exc}") from None
    conn = await _conn()
    async with get_write_lock():
        cursor = await conn.execute(
            "INSERT INTO ecommerce_scenarios(user_id,name,input_json,result_json,created_at)"
            " VALUES(?,?,?,?,?)",
            (current_user_id(), label, input_json, result_json, _now()),
        )
        await conn.commit()
    row = await fetch_one(
        "SELECT * FROM ecommerce_scenarios WHERE id=? AND user_id=?",
        (int(cursor.lastrowid or 0), current_user_id()),
    )
    if not row:
        raise RuntimeError("场景保存失败")
    return _row(row)


async def list_scenarios(limit: int = 30) -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT * FROM ecommerce_scenarios WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (current_user_id(), max(1, min(int(limit or 30), 100))),
    )
    return [_row(row) for row in rows]


async def delete_scenario(scenario_id: int) -> bool:
    conn = await _conn()
    async with get_write_lock():
        cursor = await conn.execute(
            "DELETE FROM ecommerce_scenarios WHERE id=? AND user_id=?",
            (int(scenario_id), current_user_id()),
        )
        await conn.commit()
        return bool(cursor.rowcount)

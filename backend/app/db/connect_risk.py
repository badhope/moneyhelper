"""交易风控设置：默认值、读写与区间校验。"""

from __future__ import annotations

from typing import Any

from ..logging_utils import get_logger
from ..timeutil import now_iso as _now
from ._core import _conn, fetch_one, get_write_lock
from .tenant import current_user_id

log = get_logger(__name__)


RISK_DEFAULTS = {
    "daily_limit": 200_000.0,
    "deviation_pct": 3.0,
    "concentration_pct": 30.0,
    "auto_execute_paper": 1,
}


async def get_risk_settings() -> dict[str, Any]:
    row = await fetch_one(
        "SELECT * FROM trade_risk_settings WHERE user_id=?", (current_user_id(),)
    )
    if not row:
        return dict(RISK_DEFAULTS)
    out = dict(RISK_DEFAULTS)
    # sqlite3.Row 没有 .get()：只能用 keys() 判断后再取（SIM118 的写法在这里不适用）
    keys = set(row.keys())
    out.update({k: row[k] for k in RISK_DEFAULTS if k in keys})
    out["updated_at"] = row["updated_at"] if "updated_at" in keys else ""
    return out


async def save_risk_settings(payload: dict[str, Any]) -> dict[str, Any]:
    current = await get_risk_settings()
    merged = {**current}
    for key in ("daily_limit", "deviation_pct", "concentration_pct"):
        if key in payload:
            try:
                merged[key] = float(payload[key])
            except (TypeError, ValueError):
                raise ValueError(f"{key} 必须是数字") from None
    if "auto_execute_paper" in payload:
        merged["auto_execute_paper"] = 1 if payload["auto_execute_paper"] else 0
    if merged["daily_limit"] < 0:
        raise ValueError("日限额不能为负")
    if not (0 <= merged["deviation_pct"] <= 100):
        raise ValueError("偏离阈值需在 0-100")
    if not (1 <= merged["concentration_pct"] <= 100):
        raise ValueError("集中度阈值需在 1-100")

    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO trade_risk_settings(user_id,daily_limit,deviation_pct,concentration_pct,"
            "auto_execute_paper,updated_at) VALUES(?,?,?,?,?,?)"
            " ON CONFLICT(user_id) DO UPDATE SET daily_limit=excluded.daily_limit,"
            " deviation_pct=excluded.deviation_pct, concentration_pct=excluded.concentration_pct,"
            " auto_execute_paper=excluded.auto_execute_paper, updated_at=excluded.updated_at",
            (
                current_user_id(),
                merged["daily_limit"],
                merged["deviation_pct"],
                merged["concentration_pct"],
                merged["auto_execute_paper"],
                _now(),
            ),
        )
        await conn.commit()
    return await get_risk_settings()

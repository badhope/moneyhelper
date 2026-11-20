"""条件单监控：状态机与上限守卫，不在这里下单。"""

from __future__ import annotations

from typing import Any

from ..logging_utils import get_logger
from ..timeutil import new_id as _new_id
from ..timeutil import now_iso as _now
from ._core import _conn, _mark_user_data, fetch_all, fetch_one, get_write_lock
from .tenant import current_user_id

log = get_logger(__name__)

CONDITIONAL_STATUSES = ("watching", "triggered", "cancelled", "expired")
TRIGGER_TYPES = ("price_below", "price_above", "pct_change_below", "pct_change_above")
MAX_CONDITIONAL = 100


async def create_conditional(payload: dict[str, Any]) -> dict[str, Any]:
    symbol = str(payload.get("symbol") or "").strip().upper()
    if not (symbol.isdigit() and len(symbol) == 6):
        raise ValueError("代码需为 6 位数字")
    side = str(payload.get("side") or "").lower()
    if side not in ("buy", "sell"):
        raise ValueError("方向只能是 buy / sell")
    trigger_type = str(payload.get("trigger_type") or "price_below")
    if trigger_type not in TRIGGER_TYPES:
        raise ValueError(f"触发类型只能是 {'/'.join(TRIGGER_TYPES)}")
    try:
        trigger_value = float(payload.get("trigger_value") or 0)
        price = float(payload.get("price") or 0)
        shares = float(payload.get("shares") or 0)
    except (TypeError, ValueError):
        raise ValueError("触发值/价格/股数必须是数字") from None
    if trigger_value <= 0 or price <= 0 or shares <= 0:
        raise ValueError("触发值、价格、股数必须大于 0")
    mode = str(payload.get("mode") or "paper")
    if mode not in ("paper", "live"):
        raise ValueError("mode 只能是 paper / live")

    rows = await fetch_all(
        "SELECT id FROM conditional_orders WHERE user_id=? AND status='watching'",
        (current_user_id(),),
    )
    if len(rows) >= MAX_CONDITIONAL:
        raise ValueError(f"最多 {MAX_CONDITIONAL} 条观察中的条件单")

    cid = _new_id("cond")
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO conditional_orders(user_id,id,symbol,name,side,trigger_type,"
            "trigger_value,price,shares,mode,status,note,triggered_at,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                current_user_id(),
                cid,
                symbol,
                str(payload.get("name") or "")[:40],
                side,
                trigger_type,
                round(trigger_value, 4),
                round(price, 4),
                round(shares, 4),
                mode,
                "watching",
                str(payload.get("note") or "")[:200],
                "",
                _now(),
            ),
        )
        await _mark_user_data(conn)
        await conn.commit()
    return await get_conditional(cid) or {}


async def get_conditional(cid: str) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT * FROM conditional_orders WHERE user_id=? AND id=?",
        (current_user_id(), cid),
    )
    return dict(row) if row else None


async def list_conditionals(status: str = "") -> list[dict[str, Any]]:
    params: list[Any] = [current_user_id()]
    sql = "SELECT * FROM conditional_orders WHERE user_id=?"
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY created_at DESC"
    return await fetch_all(sql, tuple(params))


async def update_conditional_status(cid: str, status: str) -> dict[str, Any]:
    if status not in CONDITIONAL_STATUSES:
        raise ValueError(f"状态只能是 {'/'.join(CONDITIONAL_STATUSES)}")
    conn = await _conn()
    async with get_write_lock():
        cur = await conn.execute(
            "UPDATE conditional_orders SET status=?, triggered_at=? WHERE user_id=? AND id=?",
            (status, _now() if status == "triggered" else "", current_user_id(), cid),
        )
        await conn.commit()
        if cur.rowcount == 0:
            raise ValueError("条件单不存在")
    return await get_conditional(cid) or {}


async def delete_conditional(cid: str) -> bool:
    conn = await _conn()
    async with get_write_lock():
        cur = await conn.execute(
            "DELETE FROM conditional_orders WHERE user_id=? AND id=?",
            (current_user_id(), cid),
        )
        await conn.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# 风控设置
# ---------------------------------------------------------------------------

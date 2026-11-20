"""交易意图：草稿→待确认→执行/拒绝/过期，单向状态机。"""

from __future__ import annotations

from typing import Any

from ..db._core import _conn, _mark_user_data, fetch_all, fetch_one, get_write_lock
from ..db.tenant import current_user_id
from ..timeutil import new_id as _new_id
from ..timeutil import now_iso as _now
from .catalog import get_connector
from .store_common import (
    INTENT_STATUSES,
    MAX_INTENTS,
    _dumps,
    _loads,
)


async def create_intent(payload: dict[str, Any]) -> dict[str, Any]:
    """创建交易意图：标的 / 方向 / 价格 / 股数 / 执行方式（paper 模拟盘，live 实盘交接）。"""
    connector_id = str(payload.get("connector_id") or "").strip()
    if connector_id:
        connector = get_connector(connector_id)
        if connector is None:
            raise ValueError(f"未知的连接器：{connector_id}")
        if not connector.get("supports_trade"):
            raise ValueError(f"{connector['name']} 不支持交易委托")

    symbol = str(payload.get("symbol") or "").strip().upper()
    if not symbol:
        raise ValueError("标的不为空")
    side = str(payload.get("side") or "").strip().lower()
    if side not in ("buy", "sell"):
        raise ValueError("方向只能是 buy / sell")
    try:
        price = float(payload.get("price") or 0)
        shares = float(payload.get("shares") or 0)
    except (TypeError, ValueError):
        raise ValueError("价格与股数必须是数字") from None
    if price <= 0 or shares <= 0:
        raise ValueError("价格与股数必须大于 0")

    mode = str(payload.get("mode") or "paper").strip()
    if mode not in ("paper", "live"):
        raise ValueError("mode 只能是 paper / live")

    rows = await fetch_all("SELECT id FROM connect_intents WHERE user_id=?", (current_user_id(),))
    if len(rows) >= MAX_INTENTS:
        # 只清理最老的已终结记录，保留待确认与已执行（审计需要）
        conn = await _conn()
        async with get_write_lock():
            await conn.execute(
                "DELETE FROM connect_intents WHERE user_id=? AND status IN ('rejected','expired')"
                " AND id IN (SELECT id FROM connect_intents WHERE user_id=? AND status IN ('rejected','expired')"
                " ORDER BY created_at ASC LIMIT ?)",
                (current_user_id(), current_user_id(), max(1, len(rows) - MAX_INTENTS + 1)),
            )
            await conn.commit()

    iid = _new_id("ord")
    now = _now()
    amount = round(price * shares, 2)
    status = "awaiting_confirm"
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO connect_intents"
            "(user_id,id,connector_id,symbol,name,side,price,shares,amount,mode,status,note,result_json,created_at,executed_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                current_user_id(),
                iid,
                connector_id,
                symbol,
                str(payload.get("name") or "").strip()[:40],
                side,
                round(price, 4),
                round(shares, 4),
                amount,
                mode,
                status,
                str(payload.get("note") or "").strip()[:200],
                "{}",
                now,
                "",
            ),
        )
        await _mark_user_data(conn)
        await conn.commit()
    return (await get_intent(iid)) or {}


async def get_intent(iid: str) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT * FROM connect_intents WHERE user_id=? AND id=?",
        (current_user_id(), str(iid)),
    )
    if not row:
        return None
    out = dict(row)
    out["result"] = _loads(out.pop("result_json", "{}"))
    return out


async def list_intents(limit: int = 50, status: str = "") -> list[dict[str, Any]]:
    params: list[Any] = [current_user_id()]
    sql = "SELECT * FROM connect_intents WHERE user_id=?"
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 200)))
    rows = await fetch_all(sql, tuple(params))
    out = []
    for r in rows:
        row = dict(r)
        row["result"] = _loads(row.pop("result_json", "{}"))
        out.append(row)
    return out


async def update_intent(
    iid: str,
    status: str,
    note: str = "",
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in INTENT_STATUSES:
        raise ValueError(f"状态只能是 {'/'.join(INTENT_STATUSES)}")
    cur = await get_intent(iid)
    if cur is None:
        raise ValueError("交易意图不存在")
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "UPDATE connect_intents SET status=?, note=?, result_json=?, executed_at=?"
            " WHERE user_id=? AND id=?",
            (
                status,
                (note or cur.get("note") or "")[:200],
                _dumps(result if result is not None else cur.get("result")),
                _now() if status == "executed" else (cur.get("executed_at") or ""),
                current_user_id(),
                iid,
            ),
        )
        await conn.commit()
    return (await get_intent(iid)) or {}

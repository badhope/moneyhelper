"""策略域：目标配置（再平衡）与定投计划的持久化。

两张表都以 user_id 为首列，与其他业务表同构；所有读写都带租户过滤，
避免多用户实例下互相看到对方的配置（与 _TENANT_TABLES 的护栏一致）。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ._core import _conn, fetch_all
from .tenant import current_user_id

MAX_TARGETS = 60
MAX_DCA_PLANS = 40


# --------------------------------------------------------------------------
# 目标配置
# --------------------------------------------------------------------------


async def list_allocation_targets() -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT symbol, name, target_pct, updated_at FROM allocation_targets"
        " WHERE user_id=? ORDER BY target_pct DESC, symbol",
        (current_user_id(),),
    )
    return [dict(r) for r in rows]


async def replace_allocation_targets(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """整表替换（前端"保存目标配置"语义）。空列表即清空。"""
    uid = current_user_id()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    clean: list[tuple[str, str, float]] = []
    seen: set[str] = set()
    for t in targets[:MAX_TARGETS]:
        sym = str(t.get("symbol") or "").strip()
        if not sym or sym in seen:
            continue
        try:
            pct = float(t.get("target_pct", 0) or 0)
        except (TypeError, ValueError):
            continue
        if pct < 0 or pct > 100:
            continue
        seen.add(sym)
        clean.append((sym, str(t.get("name") or sym)[:60], round(pct, 2)))

    conn = await _conn()
    await conn.execute("DELETE FROM allocation_targets WHERE user_id=?", (uid,))
    for sym, name, pct in clean:
        await conn.execute(
            "INSERT INTO allocation_targets(user_id,symbol,name,target_pct,updated_at) VALUES(?,?,?,?,?)",
            (uid, sym, name, pct, now),
        )
    await conn.commit()
    return await list_allocation_targets()


# --------------------------------------------------------------------------
# 定投计划
# --------------------------------------------------------------------------


async def list_dca_plans() -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT id, symbol, name, amount, frequency, day, start_date, note, active, created_at"
        " FROM dca_plans WHERE user_id=? ORDER BY created_at",
        (current_user_id(),),
    )
    out = []
    for r in rows:
        d = dict(r)
        d["active"] = bool(d.get("active"))
        out.append(d)
    return out


async def upsert_dca_plan(payload: dict[str, Any]) -> dict[str, Any]:
    uid = current_user_id()
    plan_id = str(payload.get("id") or "").strip() or uuid.uuid4().hex[:12]
    symbol = str(payload.get("symbol") or "").strip()
    if not symbol:
        raise ValueError("缺少标的代码")
    try:
        amount = float(payload.get("amount", 0) or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("定投金额必须是数字") from exc
    if amount <= 0:
        raise ValueError("定投金额必须大于 0")
    freq = str(payload.get("frequency") or "monthly")
    if freq not in ("monthly", "weekly"):
        freq = "monthly"
    try:
        day = int(payload.get("day", 1) or 1)
    except (TypeError, ValueError):
        day = 1
    day = max(1, min(28 if freq == "monthly" else 7, day))
    existing = await fetch_all(
        "SELECT id FROM dca_plans WHERE user_id=?", (uid,)
    )
    if len(existing) >= MAX_DCA_PLANS and not any(r["id"] == plan_id for r in existing):
        raise ValueError(f"定投计划最多 {MAX_DCA_PLANS} 条")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = await _conn()
    await conn.execute(
        "INSERT INTO dca_plans(user_id,id,symbol,name,amount,frequency,day,start_date,note,active,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(user_id,id) DO UPDATE SET"
        " symbol=excluded.symbol, name=excluded.name, amount=excluded.amount,"
        " frequency=excluded.frequency, day=excluded.day, start_date=excluded.start_date,"
        " note=excluded.note, active=excluded.active",
        (
            uid,
            plan_id,
            symbol,
            str(payload.get("name") or symbol)[:60],
            round(amount, 2),
            freq,
            day,
            str(payload.get("start_date") or now[:10]),
            str(payload.get("note") or "")[:200],
            1 if payload.get("active", True) else 0,
            str(payload.get("created_at") or now),
        ),
    )
    await conn.commit()
    plans = await list_dca_plans()
    return next((p for p in plans if p["id"] == plan_id), {})


async def delete_dca_plan(plan_id: str) -> bool:
    conn = await _conn()
    cur = await conn.execute(
        "DELETE FROM dca_plans WHERE user_id=? AND id=?", (current_user_id(), plan_id)
    )
    await conn.commit()
    return cur.rowcount > 0

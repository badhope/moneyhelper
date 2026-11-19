"""负债与订阅域。"""
from __future__ import annotations

from typing import Any

from ._core import (
    _clean_due_day,
    _conn,
    _mark_user_data,
)
from .undo import _record_snapshot, _row_to_json


async def add_debt(d: dict[str, Any]) -> dict[str, Any]:
    conn = await _conn()
    clean = {
        "name": str(d.get("name", "")).strip(),
        "monthly": float(d.get("monthly", 0) or 0),
        "balance": float(d.get("balance", 0) or 0),
        "rate": float(d.get("rate", 0) or 0),
        "due_day": _clean_due_day(d.get("due_day", "")),
    }
    if not clean["name"]:
        raise ValueError("名称不能为空")
    from .tenant import current_user_id

    uid = current_user_id()
    # 撤销快照：upsert 前的状态（已存在=旧行，新增='{}'）
    existing = await (
        await conn.execute(
            "SELECT * FROM debts WHERE user_id=? AND name=?", (uid, clean["name"])
        )
    ).fetchone()
    await _record_snapshot("debt", clean["name"], _row_to_json(existing))
    await conn.execute(
        "INSERT INTO debts(user_id,name,monthly,balance,rate,due_day)"
        " VALUES(:user_id,:name,:monthly,:balance,:rate,:due_day)"
        " ON CONFLICT(user_id,name) DO UPDATE SET monthly=excluded.monthly,"
        " balance=excluded.balance, rate=excluded.rate, due_day=excluded.due_day",
        {**clean, "user_id": uid},
    )
    await _mark_user_data(conn)
    await conn.commit()
    return {"ok": True, "name": clean["name"]}


async def _delete_by_name(table: str, kind: str, name: str) -> dict[str, Any]:
    """按「用户 + 名称」删一行，删前写撤销快照。

    `delete_debt` / `delete_subscription` 原本是逐字复制的两份实现，只有表名与
    快照 kind 不同。收敛成一份后，新增同类实体（如保险、学费）只要调用本函数。
    table 只允许传本模块内的常量，不来自请求参数，因此不存在注入面。
    """
    from .tenant import current_user_id

    conn = await _conn()
    uid = current_user_id()
    # 撤销快照：记录删除前的完整旧行，撤回时 INSERT OR REPLACE 恢复
    old = await (
        await conn.execute(f"SELECT * FROM {table} WHERE user_id=? AND name=?", (uid, name))
    ).fetchone()
    if old is None:
        return {"ok": False, "deleted": 0}
    await _record_snapshot(kind, name, _row_to_json(old))
    cur = await conn.execute(f"DELETE FROM {table} WHERE user_id=? AND name=?", (uid, name))
    await _mark_user_data(conn)
    await conn.commit()
    return {"ok": True, "deleted": cur.rowcount}


async def delete_debt(name: str) -> dict[str, Any]:
    return await _delete_by_name("debts", "debt", name)


async def add_subscription(s: dict[str, Any]) -> dict[str, Any]:
    conn = await _conn()
    clean = {
        "name": str(s.get("name", "")).strip(),
        "monthly": float(s.get("monthly", 0) or 0),
        "note": str(s.get("note", "")).strip(),
        "due_day": _clean_due_day(s.get("due_day", "")),
    }
    if not clean["name"]:
        raise ValueError("名称不能为空")
    if clean["monthly"] <= 0:
        raise ValueError("月支出需大于 0")
    from .tenant import current_user_id

    uid = current_user_id()
    # 撤销快照：upsert 前的状态（已存在=旧行，新增='{}'）
    existing = await (
        await conn.execute(
            "SELECT * FROM subscriptions WHERE user_id=? AND name=?", (uid, clean["name"])
        )
    ).fetchone()
    await _record_snapshot("subscription", clean["name"], _row_to_json(existing))
    await conn.execute(
        "INSERT INTO subscriptions(user_id,name,monthly,note,due_day)"
        " VALUES(:user_id,:name,:monthly,:note,:due_day)"
        " ON CONFLICT(user_id,name) DO UPDATE SET monthly=excluded.monthly,"
        " note=excluded.note, due_day=excluded.due_day",
        {**clean, "user_id": uid},
    )
    await _mark_user_data(conn)
    await conn.commit()
    return {"ok": True, "name": clean["name"]}


async def delete_subscription(name: str) -> dict[str, Any]:
    return await _delete_by_name("subscriptions", "subscription", name)

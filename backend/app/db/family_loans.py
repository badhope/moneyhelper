"""成员借款：借出/列表/结清/删除。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ._core import (
    _conn,
    fetch_all,
)
from .tenant import current_user_id

# --------------------------------------------------------------------------
# 成员间借贷 CRUD
# --------------------------------------------------------------------------


async def loan_create(
    from_member_id: int,
    to_member_id: int,
    amount: float,
    note: str = "",
    currency: str = "CNY",
) -> int:
    """创建成员间借贷，返回 id。"""
    if from_member_id == to_member_id:
        raise ValueError("借贷双方不能是同一成员")
    amt = float(amount)
    if amt <= 0:
        raise ValueError("借贷金额必须大于 0")
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    conn = await _conn()
    cur = await conn.execute(
        "INSERT INTO member_loans(user_id, from_member_id, to_member_id, amount, currency, note, settled, created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (
            current_user_id(),
            from_member_id,
            to_member_id,
            amt,
            currency,
            note.strip()[:200],
            0,
            now,
        ),
    )
    await conn.commit()
    return cur.lastrowid


async def list_loans(settled: bool | None = None) -> list[dict[str, Any]]:
    """列出借贷；settled=None 全部 / True 已结 / False 未结"""
    sql = "SELECT * FROM member_loans WHERE user_id=?"
    params: tuple = (current_user_id(),)
    if settled is not None:
        sql += " AND settled=?"
        params = (current_user_id(), 1 if settled else 0,)
    sql += " ORDER BY created_at DESC"
    return await fetch_all(sql, params)


async def loan_settle(loan_id: int) -> dict[str, Any]:
    """结清一笔借贷"""
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    conn = await _conn()
    cur = await conn.execute(
        "UPDATE member_loans SET settled=1, settled_at=? WHERE user_id=? AND id=?",
        (now, current_user_id(), loan_id),
    )
    await conn.commit()
    return {"ok": True, "updated": cur.rowcount}


async def loan_delete(loan_id: int) -> dict[str, Any]:
    """删除一笔借贷"""
    conn = await _conn()
    cur = await conn.execute(
        "DELETE FROM member_loans WHERE user_id=? AND id=?", (current_user_id(), loan_id)
    )
    await conn.commit()
    return {"ok": True, "deleted": cur.rowcount}

"""家庭域：成员/成员间借贷/家庭汇总。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ._core import (
    _AVATAR_COLORS,
    _conn,
    _fetch_member,
    fetch_all,
    fetch_one,
)
from .tenant import current_user_id

# --------------------------------------------------------------------------
# 家庭成员 CRUD
# --------------------------------------------------------------------------


async def member_create(
    display_name: str,
    role: str = "member",
    username: str = "",
    avatar_color: str = "",
) -> int:
    """创建家庭成员，返回 id。"""
    valid_roles = {"owner", "admin", "member", "viewer"}
    if role not in valid_roles:
        role = "member"
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    uname = (
        username or f"member_{now.replace(':', '').replace('-', '').replace('T', '_')}"
    )[:40]
    # 保底唯一
    base = uname
    counter = 1
    conn = await _conn()
    while True:
        row = await (
            await conn.execute(
                "SELECT id FROM members WHERE user_id=? AND username=?",
                (current_user_id(), uname),
            )
        ).fetchone()
        if row is None:
            break
        uname = f"{base}_{counter}"[:40]
        counter += 1
    if not avatar_color:
        # 轮转分配颜色
        cnt = await member_count()
        avatar_color = _AVATAR_COLORS[cnt % len(_AVATAR_COLORS)]
    cur = await conn.execute(
        "INSERT INTO members(user_id, username, display_name, role, avatar_color, created_at) "
        "VALUES(?,?,?,?,?,?)",
        (
            current_user_id(),
            uname,
            display_name.strip()[:40] or "未命名",
            role,
            avatar_color,
            now,
        ),
    )
    await conn.commit()
    return cur.lastrowid


async def member_count() -> int:
    """家庭成员总数"""
    row = await fetch_one(
        "SELECT COUNT(*) as cnt FROM members WHERE user_id=?", (current_user_id(),)
    )
    return int(row["cnt"]) if row else 0


async def list_members() -> list[dict[str, Any]]:
    """列出所有家庭成员"""
    return await fetch_all(
        "SELECT * FROM members WHERE user_id=? ORDER BY id", (current_user_id(),)
    )


async def member_update(member_id: int, **kwargs: Any) -> dict[str, Any]:
    """修改成员信息。支持 display_name / role / avatar_color。"""
    allowed = {"display_name", "role", "avatar_color"}
    sets: list[str] = []
    vals: list[Any] = []
    for k, v in kwargs.items():
        if k not in allowed or v is None:
            continue
        if k == "role" and v not in ("owner", "admin", "member", "viewer"):
            continue
        sets.append(f"{k}=?")
        vals.append(v)
    if not sets:
        # 无有效修改字段，直接返回当前信息
        m = await _fetch_member(member_id)
        return m or {}
    vals.append(current_user_id())
    vals.append(member_id)
    conn = await _conn()
    await conn.execute(
        f"UPDATE members SET {','.join(sets)} WHERE user_id=? AND id=?",
        tuple(vals),
    )
    await conn.commit()
    return await _fetch_member(member_id) or {}


async def member_delete(member_id: int) -> dict[str, Any]:
    """移除成员（该成员的流水 owner_id 置 NULL，不级联删除）。

    顺序要求：先删引用方（member_loans），再删被引用方（members）。
    反序会触发外键约束，导致"有借贷记录的成员永远删不掉"。
    整体在事务里，任一步失败回滚，不留半截状态。
    """
    uid = current_user_id()
    from ._core import write_txn

    # 顺序要求：先删引用方（member_loans），再删被引用方（members），反序会撞外键。
    # 用 write_txn 而不是裸 BEGIN：全库单连接，多语句事务必须拿写锁，
    # 否则并发时会撞 "cannot start a transaction within a transaction"。
    async with write_txn() as conn:
        # 软切断：该成员的流水不再归属任何人（保持流水不计丢）
        await conn.execute(
            "UPDATE transactions SET owner_id=NULL WHERE user_id=? AND owner_id=?",
            (uid, member_id),
        )
        await conn.execute(
            "DELETE FROM member_loans WHERE user_id=? AND (from_member_id=? OR to_member_id=?)",
            (uid, member_id, member_id),
        )
        cur = await conn.execute(
            "DELETE FROM members WHERE user_id=? AND id=?", (uid, member_id)
        )
    return {"ok": True, "deleted": cur.rowcount}


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


# --------------------------------------------------------------------------
# 成员汇总 / 家庭仪表板
# --------------------------------------------------------------------------


async def member_summary(member_id: int) -> dict[str, Any]:
    """查询单个成员的收支汇总"""
    income = await fetch_one(
        "SELECT COALESCE(SUM(amount), 0) as val FROM transactions "
        "WHERE user_id=? AND owner_id=? AND amount > 0 AND is_shared=1",
        (current_user_id(), member_id),
    )
    expense = await fetch_one(
        "SELECT COALESCE(SUM(ABS(amount)), 0) as val FROM transactions "
        "WHERE user_id=? AND owner_id=? AND amount < 0 AND is_shared=1",
        (current_user_id(), member_id),
    )
    count_row = await fetch_one(
        "SELECT COUNT(*) as val FROM transactions WHERE user_id=? AND owner_id=?",
        (current_user_id(), member_id),
    )
    return {
        "member_id": member_id,
        "income": float(income["val"]) if income else 0.0,
        "expense": float(expense["val"]) if expense else 0.0,
        "transaction_count": int(count_row["val"]) if count_row else 0,
    }


async def all_members_summary() -> list[dict[str, Any]]:
    """查询所有成员的收支汇总"""
    members = await list_members()
    result = []
    for m in members:
        s = await member_summary(m["id"])
        s["display_name"] = m["display_name"]
        s["role"] = m["role"]
        s["avatar_color"] = m["avatar_color"]
        result.append(s)
    return result


async def member_outstanding_loans() -> list[dict[str, Any]]:
    """未结清借贷（附成员显示名）"""
    loans = await list_loans(settled=False)
    members = {m["id"]: m["display_name"] for m in await list_members()}
    result = []
    for ln in loans:
        result.append(
            {
                "id": ln["id"],
                "from_member_id": ln["from_member_id"],
                "from_name": members.get(ln["from_member_id"], ""),
                "to_member_id": ln["to_member_id"],
                "to_name": members.get(ln["to_member_id"], ""),
                "amount": ln["amount"],
                "currency": ln["currency"],
                "note": ln["note"],
                "created_at": ln["created_at"],
            }
        )
    return result


async def family_summary() -> dict[str, Any]:
    """家庭整体汇总仪表板数据"""
    # 全局统计：所有 shared=1 的流水 + owner_id=NULL 的流水（向后兼容单用户）
    income_row = await fetch_one(
        "SELECT COALESCE(SUM(amount), 0) as val FROM transactions "
        "WHERE user_id=? AND amount > 0 AND (is_shared=1 OR owner_id IS NULL)",
        (current_user_id(),),
    )
    expense_row = await fetch_one(
        "SELECT COALESCE(SUM(ABS(amount)), 0) as val FROM transactions "
        "WHERE user_id=? AND amount < 0 AND (is_shared=1 OR owner_id IS NULL)",
        (current_user_id(),),
    )
    total_income = float(income_row["val"]) if income_row else 0.0
    total_expense = float(expense_row["val"]) if expense_row else 0.0

    # 各成员占比
    members = await list_members()
    member_stats = []
    for m in members:
        s = await member_summary(m["id"])
        member_stats.append(
            {
                "id": m["id"],
                "display_name": m["display_name"],
                "role": m["role"],
                "avatar_color": m["avatar_color"],
                "income": s["income"],
                "expense": s["expense"],
                "balance": round(s["income"] - s["expense"], 2),
                "pct": round(s["expense"] / total_expense * 100, 1)
                if total_expense > 0
                else 0.0,
                "transaction_count": s["transaction_count"],
            }
        )

    # 未结清借贷
    loans = await member_outstanding_loans()

    # Top categories（本月）
    now = datetime.now()
    month_prefix = now.strftime("%Y-%m")
    cat_rows = await fetch_all(
        "SELECT category, COALESCE(SUM(ABS(amount)), 0) as total "
        "FROM transactions WHERE user_id=? AND amount < 0 AND date >= ? AND date < ? "
        "GROUP BY category ORDER BY total DESC LIMIT 5",
        (current_user_id(), f"{month_prefix}-01", f"{month_prefix}-32"),
    )
    top_categories = [
        {"category": r["category"], "amount": round(float(r["total"]), 2)}
        for r in cat_rows
    ]

    return {
        "household_income": round(total_income, 2),
        "household_expense": round(total_expense, 2),
        "household_net": round(total_income - total_expense, 2),
        "members": member_stats,
        "outstanding_loans": loans,
        "top_categories": top_categories,
    }

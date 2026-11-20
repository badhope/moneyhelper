"""家庭成员：新增/列表/编辑/删除（配色池轮换）。"""

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

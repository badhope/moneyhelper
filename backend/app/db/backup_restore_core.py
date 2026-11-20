"""备份恢复·基础域：持仓/成员/借贷/家庭表决/流水/订阅/负债。"""

from __future__ import annotations

from typing import Any

import aiosqlite

from .backup_restore import _restore_table


async def _restore_core_tables(
    conn: aiosqlite.Connection,
    data: dict[str, Any],
    counts: dict[str, int],
    uid: str,
) -> None:
    counts["positions"] = await _restore_table(
        conn,
        "positions",
        data.get("positions"),
        "INSERT INTO positions(user_id,symbol,name,kind,industry,shares,cost,last,buy_date,fee)"
        " VALUES(:user_id,:symbol,:name,:kind,:industry,:shares,:cost,:last,:buy_date,:fee)",
    )
    # ---- 按外键依赖顺序恢复：members -> member_loans -> transactions ----
    # 反序会让带 owner_id 的流水在成员还不存在时触发 FOREIGN KEY 失败，
    # 而 _restore_table 的静默跳过会把它们悄悄丢掉（专家评审 P0-7）。
    counts["members"] = await _restore_table(
        conn,
        "members",
        data.get("members"),
        "INSERT INTO members(user_id,id,username,display_name,role,avatar_color,created_at)"
        " VALUES(:user_id,:id,:username,:display_name,:role,:avatar_color,:created_at)",
    )
    counts["member_loans"] = await _restore_table(
        conn,
        "member_loans",
        data.get("member_loans"),
        "INSERT INTO member_loans(user_id,id,from_member_id,to_member_id,amount,currency,note,settled,created_at,settled_at)"
        " VALUES(:user_id,:id,:from_member_id,:to_member_id,:amount,:currency,:note,:settled,:created_at,:settled_at)",
    )
    counts["family_motions"] = await _restore_table(
        conn,
        "family_motions",
        data.get("family_motions"),
        "INSERT INTO family_motions(user_id,id,title,amount,category,note,proposer_id,status,created_at,decided_at)"
        " VALUES(:user_id,:id,:title,:amount,:category,:note,:proposer_id,:status,:created_at,:decided_at)",
    )
    counts["family_votes"] = await _restore_table(
        conn,
        "family_votes",
        data.get("family_votes"),
        "INSERT INTO family_votes(user_id,motion_id,member_id,vote,note,created_at)"
        " VALUES(:user_id,:motion_id,:member_id,:vote,:note,:created_at)",
    )
    counts["transactions"] = await _restore_table(
        conn,
        "transactions",
        data.get("transactions"),
        "INSERT INTO transactions(user_id,date,item,category,amount,owner_id,is_shared)"
        " VALUES(:user_id,:date,:item,:category,:amount,:owner_id,:is_shared)",
    )
    counts["subscriptions"] = await _restore_table(
        conn,
        "subscriptions",
        data.get("subscriptions"),
        "INSERT INTO subscriptions(user_id,name,monthly,note,due_day)"
        " VALUES(:user_id,:name,:monthly,:note,:due_day)",
    )
    counts["debts"] = await _restore_table(
        conn,
        "debts",
        data.get("debts"),
        "INSERT INTO debts(user_id,name,monthly,balance,rate,due_day)"
        " VALUES(:user_id,:name,:monthly,:balance,:rate,:due_day)",
    )

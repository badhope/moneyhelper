"""家庭议会（M6.4）：motion 提案 + 成员投票 + 多数决。

规则（确定性，可解释）：
- 参与人数 = 当前家庭成员数；投票率需达到 2/3 才可能通过（避免 1 人代投）；
- 通过阈值：yes > (yes + no) 的严格多数；弃权不计入分母；
- 提案人有一票，且不能给自己投反对以外的特殊权；
- 状态机 voting → approved / rejected / withdrawn，单向不可回退；
- 通过后只标记「已通过」，不自动改账本——资金动作仍走审批与交易链。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ._core import _conn, fetch_all, fetch_one
from .tenant import current_user_id

QUORUM_RATIO = 2 / 3
VOTES = ("yes", "no", "abstain")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


async def create_motion(
    title: str, *, amount: float = 0.0, category: str = "", note: str = "", proposer_id: int | None = None
) -> dict[str, Any]:
    name = str(title or "").strip()
    if not name:
        raise ValueError("提案标题不能为空")
    mid = f"mot_{uuid.uuid4().hex[:12]}"
    conn = await _conn()
    await conn.execute(
        "INSERT INTO family_motions(user_id,id,title,amount,category,note,proposer_id,status,created_at,decided_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            current_user_id(),
            mid,
            name[:120],
            round(float(amount or 0), 2),
            str(category or "")[:30],
            str(note or "")[:300],
            proposer_id,
            "voting",
            _now(),
            "",
        ),
    )
    await conn.commit()
    return await get_motion(mid) or {}


async def get_motion(motion_id: str) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT * FROM family_motions WHERE user_id=? AND id=?",
        (current_user_id(), str(motion_id)),
    )
    if not row:
        return None
    out = dict(row)
    out["votes"] = await list_votes(motion_id)
    out["tally"] = await tally(motion_id)
    return out


async def list_motions(status: str = "") -> list[dict[str, Any]]:
    params: list[Any] = [current_user_id()]
    sql = "SELECT * FROM family_motions WHERE user_id=?"
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY created_at DESC"
    rows = await fetch_all(sql, tuple(params))
    out = []
    for r in rows:
        item = dict(r)
        item["votes"] = await list_votes(str(r["id"]))
        item["tally"] = await tally(str(r["id"]))
        out.append(item)
    return out


async def list_votes(motion_id: str) -> list[dict[str, Any]]:
    return await fetch_all(
        "SELECT * FROM family_votes WHERE user_id=? AND motion_id=? ORDER BY created_at",
        (current_user_id(), str(motion_id)),
    )


async def cast_vote(motion_id: str, member_id: int, vote: str, note: str = "") -> dict[str, Any]:
    if vote not in VOTES:
        raise ValueError(f"投票只能是 {'/'.join(VOTES)}")
    motion = await get_motion(motion_id)
    if motion is None:
        raise ValueError("提案不存在")
    if motion["status"] != "voting":
        raise ValueError(f"提案已结束（{motion['status']}），不能再投票")
    conn = await _conn()
    await conn.execute(
        "INSERT INTO family_votes(user_id,motion_id,member_id,vote,note,created_at)"
        " VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,motion_id,member_id)"
        " DO UPDATE SET vote=excluded.vote, note=excluded.note, created_at=excluded.created_at",
        (current_user_id(), str(motion_id), int(member_id), vote, str(note or "")[:200], _now()),
    )
    await conn.commit()
    await _maybe_decide(motion_id)
    return await get_motion(motion_id) or {}


async def _member_count() -> int:
    row = await fetch_one("SELECT COUNT(*) AS c FROM members WHERE user_id=?", (current_user_id(),))
    return int(row["c"]) if row else 0


async def tally(motion_id: str) -> dict[str, Any]:
    """计票：参与率、同意率、是否达到法定人数与多数。"""
    votes = await list_votes(motion_id)
    yes = sum(1 for v in votes if v["vote"] == "yes")
    no = sum(1 for v in votes if v["vote"] == "no")
    abstain = sum(1 for v in votes if v["vote"] == "abstain")
    total_members = await _member_count()
    voted = len(votes)
    quorum_needed = max(1, int(total_members * QUORUM_RATIO + 0.999)) if total_members else 1
    decisive = yes + no
    passed = bool(decisive and yes > no and voted >= quorum_needed)
    return {
        "yes": yes,
        "no": no,
        "abstain": abstain,
        "voted": voted,
        "members": total_members,
        "quorum_needed": quorum_needed,
        "quorum_met": voted >= quorum_needed,
        "would_pass": passed,
    }


async def _maybe_decide(motion_id: str) -> None:
    """投票人数达到全员时自动定案；未达全员保持 voting。"""
    motion = await get_motion(motion_id)
    if motion is None or motion["status"] != "voting":
        return
    t = motion["tally"]
    if t["members"] and t["voted"] >= t["members"]:
        status = "approved" if t["would_pass"] else "rejected"
        conn = await _conn()
        await conn.execute(
            "UPDATE family_motions SET status=?, decided_at=? WHERE user_id=? AND id=?",
            (status, _now(), current_user_id(), str(motion_id)),
        )
        await conn.commit()


async def withdraw_motion(motion_id: str) -> dict[str, Any]:
    motion = await get_motion(motion_id)
    if motion is None:
        raise ValueError("提案不存在")
    if motion["status"] != "voting":
        raise ValueError(f"提案已结束（{motion['status']}）")
    conn = await _conn()
    await conn.execute(
        "UPDATE family_motions SET status='withdrawn', decided_at=? WHERE user_id=? AND id=?",
        (_now(), current_user_id(), str(motion_id)),
    )
    await conn.commit()
    return await get_motion(motion_id) or {}

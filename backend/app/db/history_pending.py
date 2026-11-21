"""会话摘要与 HITL 待确认动作：摘要读写、pending token 认领/标记/分叉。

从 history.py 拆出；连接与助手仍走 _core，租户口径走 tenant。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ._core import (
    PENDING_TTL_MINUTES,
    _conn,
    _now_iso,
    fetch_all,
    get_write_lock,
    uuid_hex,
)
from .tenant import current_user_id


async def get_conversation_summary(thread_id: str) -> dict[str, Any] | None:
    """取会话压缩摘要；无则返回 None。"""
    rows = await fetch_all(
        "SELECT summary, source, covered_to, updated_at FROM conversation_summary"
        " WHERE user_id=? AND thread_id=?",
        (current_user_id(), thread_id),
    )
    if not rows:
        return None
    return rows[0]

async def set_conversation_summary(
    thread_id: str, summary: str, source: str, covered_to: int
) -> dict[str, Any]:
    """写入/覆盖会话摘要（长会话压缩后的持久化上下文）。"""
    conn = await _conn()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    await conn.execute(
        "INSERT INTO conversation_summary(user_id,thread_id,summary,source,covered_to,updated_at)"
        " VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,thread_id) DO UPDATE SET"
        " summary=excluded.summary, source=excluded.source,"
        " covered_to=excluded.covered_to, updated_at=excluded.updated_at",
        (
            current_user_id(),
            thread_id,
            summary[:4000],
            source[:16],
            int(covered_to or 0),
            now,
        ),
    )
    await conn.commit()
    return {"ok": True}

async def clear_conversation_summary(thread_id: str) -> dict[str, Any]:
    """删除某会话摘要（会话重置/清理时用）。"""
    conn = await _conn()
    await conn.execute(
        "DELETE FROM conversation_summary WHERE user_id=? AND thread_id=?",
        (current_user_id(), thread_id),
    )
    await conn.commit()
    return {"ok": True}

async def create_pending_action(
    tool_name: str, args: dict[str, Any], summary: str, lang: str = "zh"
) -> dict[str, Any]:
    """登记一个待用户确认的写类动作，返回带一次性 token 的 pending 记录。"""
    import uuid as _uuid

    token = _uuid.uuid4().hex
    now = _now_iso()
    from datetime import timedelta

    expires = (
        datetime.now().astimezone() + timedelta(minutes=PENDING_TTL_MINUTES)
    ).isoformat(timespec="seconds")
    conn = await _conn()
    await conn.execute(
        "INSERT INTO pending_actions(user_id,token,tool_name,args,summary,lang,status,created_at,expires_at)"
        " VALUES(?,?,?,?,?,?,'pending',?,?)",
        (
            current_user_id(),
            token,
            tool_name,
            json.dumps(args, ensure_ascii=False),
            summary,
            lang,
            now,
            expires,
        ),
    )
    await conn.commit()
    return {
        "ok": True,
        "token": token,
        "tool_name": tool_name,
        "args": args,
        "summary": summary,
        "expires_at": expires,
    }

async def get_pending_action(token: str) -> dict[str, Any] | None:
    """按 token 取待确认动作；不存在/已消费/已取消/已过期一律返回 None（token 一次性）。"""
    rows = await fetch_all(
        "SELECT * FROM pending_actions WHERE user_id=? AND token=? AND status='pending'",
        (current_user_id(), token),
    )
    if not rows:
        return None
    row = rows[0]
    # 惰性过期：到期未确认的标记 expired 并作废
    if str(row["expires_at"] or "") < _now_iso():
        conn = await _conn()
        # 必须和批量入账共用写锁：这里单独 commit 会把并发批量事务的
        # BEGIN IMMEDIATE 提前提交掉，对方 COMMIT 时报 "no transaction is active"。
        async with get_write_lock():
            await conn.execute(
                "UPDATE pending_actions SET status='expired'"
                " WHERE user_id=? AND token=? AND status='pending'",
                (current_user_id(), token),
            )
            await conn.commit()
        return None
    return {
        "token": row["token"],
        "tool_name": row["tool_name"],
        "args": json.loads(row["args"] or "{}"),
        "summary": row["summary"],
        "lang": row.get("lang") or "zh",
        "expires_at": row["expires_at"],
    }

async def claim_pending_action(token: str) -> dict[str, Any] | None:
    """原子地把 pending 动作置为 consumed 并返回其内容；已被占用/失效返回 None。

    为什么需要：确认流程是"取出来 → 执行 → 标记"，三步之间如果有第二条请求
    进来，就会重复执行同一笔买入/记账（不可逆）。这里用带条件的 UPDATE 抢占，
    只有 rowcount==1 的调用者拿到执行权，天然互斥（进程内锁 + 多进程都成立）。
    """
    rows = await fetch_all(
        "SELECT * FROM pending_actions WHERE user_id=? AND token=? AND status='pending'",
        (current_user_id(), token),
    )
    if not rows:
        return None
    row = rows[0]
    if str(row["expires_at"] or "") < _now_iso():
        await mark_pending_action(token, "expired")
        return None
    conn = await _conn()
    async with get_write_lock():
        cur = await conn.execute(
            "UPDATE pending_actions SET status='consumed'"
            " WHERE user_id=? AND token=? AND status='pending'",
            (current_user_id(), token),
        )
        await conn.commit()
    if cur.rowcount != 1:
        return None
    return {
        "token": row["token"],
        "tool_name": row["tool_name"],
        "args": json.loads(row["args"] or "{}"),
        "summary": row["summary"],
        "lang": row.get("lang") or "zh",
        "expires_at": row["expires_at"],
    }

async def force_pending_status(token: str, status: str) -> dict[str, Any]:
    """无条件设置待确认动作状态（用于执行失败后把 consumed 改成 failed）。

    与 mark_pending_action 的区别：后者带 status='pending' 条件（只影响待处理行），
    对已被 claim 消费的行是空操作；这里需要覆盖已消费行，才能如实记录失败。
    """
    conn = await _conn()
    async with get_write_lock():
        cur = await conn.execute(
            "UPDATE pending_actions SET status=? WHERE user_id=? AND token=?",
            (status, current_user_id(), token),
        )
        await conn.commit()
    return {"ok": True, "changed": cur.rowcount}

async def mark_pending_action(token: str, status: str) -> dict[str, Any]:
    conn = await _conn()
    async with get_write_lock():
        cur = await conn.execute(
            "UPDATE pending_actions SET status=? WHERE user_id=? AND token=? AND status='pending'",
            (status, current_user_id(), token),
        )
        await conn.commit()
    return {"ok": True, "changed": cur.rowcount}

async def session_usage(thread_id: str) -> dict[str, Any]:
    """某会话的 token 用量汇总（harness 上下文仪表的数据源）。

    tokens 逐轮来自模型真实回传（无模型/模板轮为 0）；context_est 用
    近轮 tokens_in 总和 + 会话摘要长度估算，仅作仪表展示，不参与计费。
    """
    rows = await fetch_all(
        "SELECT tokens_in, tokens_out, created_at FROM runs"
        " WHERE user_id=? AND thread_id=? ORDER BY id ASC",
        (current_user_id(), thread_id),
    )
    tokens_in = sum(int(r["tokens_in"] or 0) for r in rows)
    tokens_out = sum(int(r["tokens_out"] or 0) for r in rows)
    turns = len(rows)
    summary = await get_conversation_summary(thread_id)
    summary_chars = len(str((summary or {}).get("summary") or ""))
    # 粗估：中文 ≈1.6 char/token，摘要按 1.6 折算 + 每轮 token_in 本身已含当轮上下文
    context_est = tokens_in + int(summary_chars / 1.6)
    return {
        "thread_id": thread_id,
        "turns": turns,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_total": tokens_in + tokens_out,
        "context_est": context_est,
        "summary_chars": summary_chars,
        "compacted": bool(summary and (summary.get("summary"))),
    }

async def fork_session(thread_id: str, run_id: int) -> dict[str, Any] | None:
    """从某条问答处分叉出新会话（opencode 式 branch）：复制该轮及之前的全部 run。

    新线程标题取「原标题 · 分支」；摘要表不复制（分叉后各自演化）。
    run_id 不属于该会话时返回 None，绝不复制错会话的数据。
    """
    rows = await fetch_all(
        "SELECT * FROM runs WHERE user_id=? AND thread_id=? AND id<=?"
        " ORDER BY id ASC",
        (current_user_id(), thread_id, int(run_id)),
    )
    if not rows:
        return None
    sessions = await fetch_all(
        "SELECT title FROM sessions WHERE user_id=? AND thread_id=?",
        (current_user_id(), thread_id),
    )
    base_title = (sessions[0]["title"] if sessions else "") or "新会话"
    new_tid = uuid_hex()
    from ._core import write_txn

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    # 会话 + 全部 run 必须成组写入，否则中途失败会留下"分支会话存在但对话只有半截"。
    async with write_txn() as conn:
        await conn.execute(
            "INSERT INTO sessions(user_id,thread_id,title,created_at,updated_at)"
            " VALUES(?,?,?,?,?)",
            (current_user_id(), new_tid, f"{base_title} · 分支"[:40], now, now),
        )
        for r in rows:
            await conn.execute(
                "INSERT INTO runs(user_id,thread_id,question,answer,level,flags_json,created_at,"
                "route,llm,route_reason,tools,actions,tokens_in,tokens_out)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    current_user_id(),
                    new_tid,
                    r["question"],
                    r["answer"],
                    r["level"] or "",
                    r["flags_json"] or "[]",
                    r["created_at"],
                    r["route"] or "",
                    r["llm"] or "",
                    r["route_reason"] or "",
                    r["tools"] or "[]",
                    r["actions"] or "[]",
                    int(r["tokens_in"] or 0),
                    int(r["tokens_out"] or 0),
                ),
            )
    return {"ok": True, "thread_id": new_tid, "copied": len(rows)}

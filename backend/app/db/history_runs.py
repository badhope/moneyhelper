"""问答运行记录：保存/删除/列表/搜索/定时任务回执/历史清空。

从 history.py 拆出；连接与助手仍走 _core，租户口径走 tenant。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ._core import (
    _clamp_limit,
    _conn,
    fetch_all,
    get_write_lock,
)
from .history_sessions import upsert_session
from .tenant import current_user_id


async def save_run(
    thread_id: str,
    question: str,
    answer: str,
    level: str,
    flags: list[dict[str, Any]] | None = None,
    route: str = "",
    llm: str = "",
    route_reason: str = "",
    tools: list[str] | None = None,
    actions: list[dict[str, Any]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    skip_session: bool = False,
    tokens: dict[str, int] | None = None,
) -> dict[str, Any]:
    conn = await _conn()
    created = datetime.now().astimezone().isoformat(timespec="seconds")
    usage = tokens if isinstance(tokens, dict) else {}
    # 共用写锁：单条 commit 会把并发批量事务（BEGIN IMMEDIATE）提前提交掉，
    # 对方 COMMIT 时报 "no transaction is active"（并发确认入账实测）。
    async with get_write_lock():
        cur = await conn.execute(
            "INSERT INTO runs(user_id,thread_id,question,answer,level,flags_json,created_at,"
            "route,llm,route_reason,tools,actions,attachments_json,tokens_in,tokens_out)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            current_user_id(),
            thread_id or "default",
            question,
            answer,
            level or "",
            json.dumps(flags or [], ensure_ascii=False),
            created,
            route or "",
            llm or "",
            route_reason or "",
            json.dumps(tools or [], ensure_ascii=False),
            json.dumps(actions or [], ensure_ascii=False),
            json.dumps(attachments or [], ensure_ascii=False),
            int(usage.get("prompt") or 0),
            int(usage.get("completion") or 0),
            ),
        )
        await conn.commit()
    if not skip_session:
        # 会话列表只收录真实对话；定时晨报等系统归档（thread_id='cron'）不建会话，
        # 晨报历史仍按 thread_id='cron' 从 runs 表读取，不污染「问AI」会话列表。
        await upsert_session(thread_id or "default", question)
    return {"ok": True, "id": cur.lastrowid}

async def delete_last_run(
    thread_id: str, question: str | None = None
) -> dict[str, Any]:
    """删除指定会话中某问题的最近一条问答（'重新生成'用：先移除旧回答再重答）。

    传 question 时精确匹配该问题的最近记录并删除；传了但未命中返回 deleted=0，
    绝不退化为删除线程最后一条（避免误删另一问题的回答）。未传 question 才删线程末条。
    """
    conn = await _conn()
    if question:
        cur = await conn.execute(
            "SELECT id, attachments_json FROM runs WHERE user_id=? AND thread_id=? AND question=?"
            " ORDER BY id DESC LIMIT 1",
            (current_user_id(), thread_id, question),
        )
        row = await cur.fetchone()
        if row:
            await conn.execute(
                "DELETE FROM runs WHERE user_id=? AND id=?",
                (current_user_id(), row["id"]),
            )
            await conn.commit()
            return _deleted_run(row)
        return {"ok": True, "deleted": 0, "attachments": []}
    cur = await conn.execute(
        "SELECT id, attachments_json FROM runs WHERE user_id=? AND thread_id=? ORDER BY id DESC LIMIT 1",
        (current_user_id(), thread_id),
    )
    row = await cur.fetchone()
    if row:
        await conn.execute(
            "DELETE FROM runs WHERE user_id=? AND id=?", (current_user_id(), row["id"])
        )
        await conn.commit()
        return _deleted_run(row)
    return {"ok": True, "attachments": []}


def _deleted_run(row: Any) -> dict[str, Any]:
    try:
        attachments = json.loads(dict(row).get("attachments_json") or "[]")
    except Exception:
        attachments = []
    if not isinstance(attachments, list):
        attachments = []
    return {"ok": True, "deleted": 1, "attachments": attachments}


async def list_runs(
    thread_id: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    clamped = _clamp_limit(limit)
    if thread_id:
        rows = await fetch_all(
            "SELECT * FROM runs WHERE user_id=? AND thread_id=?"
            " ORDER BY id DESC LIMIT ?",
            (current_user_id(), thread_id, clamped),
        )
    else:
        rows = await fetch_all(
            "SELECT * FROM runs WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (current_user_id(), clamped),
        )
    return [_hydrate_run(r) for r in rows]

async def list_scheduled_runs(limit: int = 30) -> list[dict[str, Any]]:
    """定时产出时间线（system 线程）：晨报（thread='cron'）+ 技能触发（thread='skill:*'）。

    这两类线程与「问AI」会话列表隔离（不建会话行），但产出需要可查——
    收件箱统一从 runs 表读取，最新在前。
    """
    clamped = _clamp_limit(limit)
    rows = await fetch_all(
        "SELECT * FROM runs WHERE user_id=? AND (thread_id='cron' OR thread_id LIKE 'skill:%')"
        " ORDER BY id DESC LIMIT ?",
        (current_user_id(), clamped),
    )
    return [_hydrate_run(r) for r in rows]

async def claim_pending_nl(thread_id: str) -> bool:
    """原子消费该线程最后一条 nl_pending run（大额审批回执，确认/取消共用）。

    单条 UPDATE + rowcount 判定：并发回执或断连重试时仅一个能 claim 成功，
    防止同一笔待确认被重复入账；claim 成功后该 run 的 route 记为 nl_pending_consumed。
    """
    conn = await _conn()
    cur = await conn.execute(
        "UPDATE runs SET route='nl_pending_consumed' "
        "WHERE id = (SELECT id FROM runs WHERE user_id=? AND thread_id=?"
        "            ORDER BY id DESC LIMIT 1) "
        "AND route='nl_pending'",
        (current_user_id(), thread_id),
    )
    await conn.commit()
    return cur.rowcount == 1

def _hydrate_run(r: dict[str, Any]) -> dict[str, Any]:
    """把 runs 行的 JSON 列反序列化（flags/tools/actions），返回可序列化 dict。"""
    out = dict(r)
    for col, field in (
        ("flags_json", "flags"),
        ("tools", "tools"),
        ("actions", "actions"),
        ("attachments_json", "attachments"),
    ):
        try:
            out[field] = json.loads(out.pop(col, "[]") or "[]")
        except Exception:
            out[field] = []
    return out

async def search_runs(q: str, limit: int = 50) -> list[dict[str, Any]]:
    """跨会话全文搜索历次问答（question / answer LIKE），附带所属会话标题，供全局历史跳转。"""
    # 转义 LIKE 通配符：用户输入含 % 或 _ 时按字面字符处理，不可充当通配符（防注入+DoS）
    esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    kw = f"%{esc}%"
    rows = await fetch_all(
        "SELECT r.*, s.title AS session_title, s.archived AS session_archived"
        " FROM runs r LEFT JOIN sessions s"
        "   ON s.thread_id = r.thread_id AND s.user_id = r.user_id"
        " WHERE r.user_id=? AND (r.question LIKE ? ESCAPE '\\' OR r.answer LIKE ? ESCAPE '\\')"
        " ORDER BY r.id DESC LIMIT ?",
        (current_user_id(), kw, kw, _clamp_limit(limit)),
    )
    return [_hydrate_run(r) for r in rows]

async def delete_runs_from(thread_id: str, run_id: int) -> dict[str, Any]:
    """删掉指定 run 及其之后的所有轮次（编辑并重发用）。

    只允许删除该 thread 自己的 run；不按时间猜、不跨会话删。删除后由调用方
    用同一 thread 重新提问，保证「编辑第 N 轮」等于把第 N 轮之后的历史截断。
    """
    conn = await _conn()
    cur = await conn.execute(
        "SELECT id FROM runs WHERE user_id=? AND thread_id=? AND id=?",
        (current_user_id(), thread_id, int(run_id)),
    )
    row = await cur.fetchone()
    if not row:
        raise ValueError("该轮次不属于当前会话")
    cur = await conn.execute(
        "DELETE FROM runs WHERE user_id=? AND thread_id=? AND id>=?",
        (current_user_id(), thread_id, int(run_id)),
    )
    await conn.commit()
    return {"ok": True, "deleted": cur.rowcount or 0}


async def delete_run(run_id: int) -> dict[str, Any]:
    """删除单条历史问答记录。"""
    conn = await _conn()
    cur = await conn.execute(
        "DELETE FROM runs WHERE user_id=? AND id=?", (current_user_id(), int(run_id))
    )
    await conn.commit()
    return {"ok": True, "deleted": cur.rowcount or 0}

async def clear_history() -> dict[str, Any]:
    """清空全部历史：删除所有会话、问答记录与会话摘要。"""
    conn = await _conn()
    uid = current_user_id()
    await conn.execute("DELETE FROM runs WHERE user_id=?", (uid,))
    await conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    await conn.execute("DELETE FROM conversation_summary WHERE user_id=?", (uid,))
    await conn.commit()
    return {"ok": True, "cleared": True}

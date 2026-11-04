"""历史域：问答 runs/会话 sessions/会话摘要/待确认动作。"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ._core import (
    PENDING_TTL_MINUTES,
    _clamp_limit,
    _conn,
    _now_iso,
    fetch_all,
    uuid_hex,
)
from .tenant import current_user_id

# --------------------------------------------------------------------------
# 运行历史
# --------------------------------------------------------------------------


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
    skip_session: bool = False,
    tokens: dict[str, int] | None = None,
) -> dict[str, Any]:
    conn = await _conn()
    created = datetime.now().astimezone().isoformat(timespec="seconds")
    usage = tokens if isinstance(tokens, dict) else {}
    cur = await conn.execute(
        "INSERT INTO runs(user_id,thread_id,question,answer,level,flags_json,created_at,route,llm,route_reason,tools,actions,tokens_in,tokens_out)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
            "SELECT id FROM runs WHERE user_id=? AND thread_id=? AND question=?"
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
            return {"ok": True, "deleted": 1}
        return {"ok": True, "deleted": 0}
    cur = await conn.execute(
        "SELECT id FROM runs WHERE user_id=? AND thread_id=? ORDER BY id DESC LIMIT 1",
        (current_user_id(), thread_id),
    )
    row = await cur.fetchone()
    if row:
        await conn.execute(
            "DELETE FROM runs WHERE user_id=? AND id=?", (current_user_id(), row["id"])
        )
        await conn.commit()
    return {"ok": True}


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
    ):
        try:
            out[field] = json.loads(out.pop(col) or "[]")
        except Exception:
            out[field] = []
    return out


async def search_runs(q: str, limit: int = 50) -> list[dict[str, Any]]:
    """跨会话全文搜索历次问答（question / answer LIKE），附带所属会话标题，供全局历史跳转。"""
    # 转义 LIKE 通配符：用户输入含 % 或 _ 时按字面字符处理，不可充当通配符（防注入+DoS）
    esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    kw = f"%{esc}%"
    rows = await fetch_all(
        "SELECT r.*, s.title AS session_title"
        " FROM runs r LEFT JOIN sessions s"
        "   ON s.thread_id = r.thread_id AND s.user_id = r.user_id"
        " WHERE r.user_id=? AND (r.question LIKE ? ESCAPE '\\' OR r.answer LIKE ? ESCAPE '\\')"
        " ORDER BY r.id DESC LIMIT ?",
        (current_user_id(), kw, kw, _clamp_limit(limit)),
    )
    return [_hydrate_run(r) for r in rows]


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


# --------------------------------------------------------------------------
# 会话管理（thread 列表：新建 / 重命名 / 删除）
# --------------------------------------------------------------------------


def is_system_thread(thread_id: str) -> bool:
    """系统归档线程（不属于「问AI」会话列表）：cron 晨报 / skill:<id> 技能定时触发。"""
    return thread_id == "cron" or thread_id.startswith("skill:")


async def upsert_session(thread_id: str, title: str) -> dict[str, Any]:
    """问答落库时同步会话表：标题仍为默认'新会话'时用首个问题覆盖，否则保留自定义；刷新 updated_at。

    系统归档线程直接拒绝（第三道防线：调用方应传 skip_session，读侧与启动迁移也各自排除）。
    """
    if is_system_thread(thread_id):
        return {"ok": True, "thread_id": thread_id, "skipped": "system_thread"}
    conn = await _conn()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    await conn.execute(
        "INSERT INTO sessions(user_id,thread_id,title,created_at,updated_at)"
        " VALUES(?,?,?,?,?)"
        " ON CONFLICT(user_id,thread_id) DO UPDATE SET"
        " title=CASE WHEN sessions.title='新会话' THEN excluded.title ELSE sessions.title END,"
        " updated_at=excluded.updated_at",
        (current_user_id(), thread_id, title[:40] or "新会话", now, now),
    )
    await conn.commit()
    return {"ok": True, "thread_id": thread_id}


async def create_session(
    thread_id: str | None = None, title: str = "新会话"
) -> dict[str, Any]:
    conn = await _conn()
    tid = thread_id or uuid_hex()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    cur = await conn.execute(
        "INSERT INTO sessions(user_id,thread_id,title,created_at,updated_at)"
        " VALUES(?,?,?,?,?)",
        (current_user_id(), tid, title[:40] or "新会话", now, now),
    )
    await conn.commit()
    return {"ok": True, "id": cur.lastrowid, "thread_id": tid}


async def list_sessions() -> list[dict[str, Any]]:
    # 读侧同样排除系统归档线程（cron 晨报 / skill:<id> 技能触发）：即使旧库已被
    # 误建，界面也不会把它们当会话展示；启动迁移会做彻底清理。
    rows = await fetch_all(
        "SELECT id, thread_id, title, created_at, updated_at"
        " FROM sessions WHERE user_id=? AND thread_id <> 'cron' AND thread_id NOT LIKE 'skill:%'"
        " ORDER BY updated_at DESC",
        (current_user_id(),),
    )
    return rows


async def rename_session(session_id: int, title: str) -> dict[str, Any]:
    conn = await _conn()
    await conn.execute(
        "UPDATE sessions SET title=?, updated_at=? WHERE user_id=? AND id=?",
        (
            str(title).strip()[:40] or "新会话",
            datetime.now().astimezone().isoformat(timespec="seconds"),
            current_user_id(),
            int(session_id),
        ),
    )
    await conn.commit()
    return {"ok": True}


async def delete_session(session_id: int) -> dict[str, Any]:
    """删除会话及其全部问答记录（含长会话摘要）。"""
    conn = await _conn()
    row = await (
        await conn.execute(
            "SELECT thread_id FROM sessions WHERE user_id=? AND id=?",
            (current_user_id(), int(session_id)),
        )
    ).fetchone()
    await conn.execute(
        "DELETE FROM sessions WHERE user_id=? AND id=?", (current_user_id(), int(session_id))
    )
    if row:
        await conn.execute(
            "DELETE FROM runs WHERE user_id=? AND thread_id=?",
            (current_user_id(), row["thread_id"]),
        )
        await conn.execute(
            "DELETE FROM conversation_summary WHERE user_id=? AND thread_id=?",
            (current_user_id(), row["thread_id"]),
        )
    await conn.commit()
    return {"ok": True, "deleted": True}


async def session_thread_id(session_id: int) -> str | None:
    """会话对应的 thread_id；不存在返回 None。"""
    conn = await _conn()
    row = await (
        await conn.execute(
            "SELECT thread_id FROM sessions WHERE user_id=? AND id=?",
            (current_user_id(), int(session_id)),
        )
    ).fetchone()
    return row["thread_id"] if row else None


async def move_runs(from_tid: str, to_tid: str) -> int:
    """把 from 线程下的 runs 迁到 to 线程（乐观新建会话窗口内的提问归位）。返回迁移条数。"""
    if not from_tid or from_tid == to_tid:
        return 0
    conn = await _conn()
    cur = await conn.execute(
        "UPDATE runs SET thread_id=? WHERE user_id=? AND thread_id=?",
        (to_tid, current_user_id(), from_tid),
    )
    await conn.commit()
    return cur.rowcount or 0


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
    cur = await conn.execute(
        "UPDATE pending_actions SET status=? WHERE user_id=? AND token=?",
        (status, current_user_id(), token),
    )
    await conn.commit()
    return {"ok": True, "changed": cur.rowcount}


async def mark_pending_action(token: str, status: str) -> dict[str, Any]:
    conn = await _conn()
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
    conn = await _conn()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    await conn.execute(
        "INSERT INTO sessions(user_id,thread_id,title,created_at,updated_at)"
        " VALUES(?,?,?,?,?)",
        (current_user_id(), new_tid, ("%s · 分支" % base_title)[:40], now, now),
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
    await conn.commit()
    return {"ok": True, "thread_id": new_tid, "copied": len(rows)}

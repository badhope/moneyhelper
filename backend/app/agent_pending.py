"""HITL 挂起动作的磁盘持久化：token → thread_id，跨进程重启可恢复。

从 agent_graph.py 拆出。数据库与 checkpoint 库同目录但分文件（agent_pending.db），
路径在首次建连时按当前 data_dir 解析（不缓存 import 时的值，测试换目录即生效）。
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any

from . import db, service
from .logging_utils import get_logger

log = get_logger(__name__)

_PENDING_APPROVAL_TTL_MINUTES = 30

def _pending_db_path():
    """pending 库路径由 agent_graph 的 `_PENDING_DB` 决定。

    每次建连时读取而不是 import 时固化：测试夹具会直接改这个值指到临时目录，
    缓存在本模块会连到上一个用例/真实库。
    """
    from .agent_graph import _PENDING_DB

    return _PENDING_DB

_pending_conn: sqlite3.Connection | None = None

def _pending_sql() -> sqlite3.Connection:
    global _pending_conn
    if _pending_conn is None:
        db_path = _pending_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _pending_conn = sqlite3.connect(str(db_path), check_same_thread=False)
        _pending_conn.execute("PRAGMA journal_mode=WAL")
        _pending_conn.execute(
            "CREATE TABLE IF NOT EXISTS pending("
            " token TEXT PRIMARY KEY, thread_id TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        _pending_conn.commit()
    return _pending_conn

async def _save_pending(token: str, thread_id: str) -> None:
    def _w() -> None:
        c = _pending_sql()
        # 顺手清理过期条目：pending 表此前只增不删，用户反复触发写操作但不确认时
        # 会无限增长（重启后还能被 resume 的也只是最近 30 分钟内的）。
        c.execute(
            "DELETE FROM pending WHERE created_at < ?",
            (_pending_cutoff(),),
        )
        c.execute(
            "INSERT OR REPLACE INTO pending(token, thread_id, created_at) VALUES(?,?,?)",
            (token, thread_id, time.strftime("%Y-%m-%dT%H:%M:%S")),
        )
        c.commit()

    await asyncio.to_thread(_w)

def _pending_cutoff() -> str:
    """早于此刻的 pending 记录视为过期（与审批 TTL 一致，避免陈旧 token 被恢复）。"""
    from datetime import timedelta

    return (datetime.now() - timedelta(minutes=_PENDING_APPROVAL_TTL_MINUTES)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )

async def _load_pending(token: str) -> str | None:
    def _r() -> str | None:
        row = (
            _pending_sql()
            .execute(
                "SELECT thread_id FROM pending WHERE token=? AND created_at >= ?",
                (token, _pending_cutoff()),
            )
            .fetchone()
        )
        return row[0] if row else None

    return await asyncio.to_thread(_r)

async def _delete_pending(token: str) -> None:
    def _d() -> None:
        c = _pending_sql()
        c.execute("DELETE FROM pending WHERE token=?", (token,))
        c.commit()

    await asyncio.to_thread(_d)

def _close_pending_conn() -> None:
    global _pending_conn
    if _pending_conn is not None:
        try:
            _pending_conn.close()
        except Exception:
            pass
        _pending_conn = None

async def _pending_confirm_context(
    question: str, thread_id: str | None
) -> dict[str, Any] | None:
    """上一轮为 nl_pending 待确认时，把「确认/取消」短回复识别为审批回执。

    仅当该线程最后一条 run 的 route 是 nl_pending、未过 TTL 且回复命中词表才算，否则返回 None。
    （消费动作由调用方经 db.claim_pending_nl 原子完成，本函数只做识别。）
    """
    if not thread_id:
        return None
    decision = service._confirm_decision(question)
    if decision is None:
        return None
    runs = await db.list_runs(thread_id, 1)
    if not runs or runs[0].get("route") != "nl_pending":
        return None
    try:
        created = datetime.fromisoformat(str(runs[0].get("created_at") or ""))
        if datetime.now().astimezone() - created > timedelta(
            minutes=_PENDING_APPROVAL_TTL_MINUTES
        ):
            return None
    except ValueError:
        pass  # 时间戳异常不阻断（按未过期处理）
    return {"decision": decision, "question": str(runs[0].get("question") or "")}

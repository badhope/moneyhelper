"""财报分析域持久化：标准化三表 JSON 的存取（v4.0）。

表 financial_statements：user_id + id 复合主键，payload 存原始三表输入
（可重新分析），report 存最近一次报告文本快照。租户隔离与 _TENANT_TABLES
一致（新表本身即带 user_id 主键，无需迁移）。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from ._core import _conn, fetch_all, fetch_one
from .tenant import current_user_id

MAX_REPORTS = 40  # 每用户最多保存 40 份，防止无限堆积


async def save_statement(
    company: str,
    payload: dict[str, Any],
    report: str = "",
    currency: str = "CNY",
) -> dict[str, Any]:
    """保存一份财报分析。返回插入后的记录。"""
    uid = current_user_id()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    sid = uuid.uuid4().hex[:12]

    # 超限清理：保留最新的 MAX_REPORTS-1 条后插入
    rows = await fetch_all(
        "SELECT id FROM financial_statements WHERE user_id=? ORDER BY created_at DESC",
        (uid,),
    )
    if len(rows) >= MAX_REPORTS:
        drop = [r["id"] for r in rows[MAX_REPORTS - 1 :]]
        conn = await _conn()
        for did in drop:
            await conn.execute(
                "DELETE FROM financial_statements WHERE user_id=? AND id=?", (uid, did)
            )
        await conn.commit()

    conn = await _conn()
    await conn.execute(
        "INSERT INTO financial_statements(user_id,id,company,currency,payload,report,created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (uid, sid, company[:120], currency, json.dumps(payload, ensure_ascii=False), report, now),
    )
    await conn.commit()
    return {"id": sid, "company": company, "currency": currency, "created_at": now}


async def list_statements() -> list[dict[str, Any]]:
    """列出当前用户的财报记录（不含 payload，减载）。"""
    rows = await fetch_all(
        "SELECT id, company, currency, created_at, substr(report,1,80) AS summary"
        " FROM financial_statements WHERE user_id=? ORDER BY created_at DESC",
        (current_user_id(),),
    )
    return [dict(r) for r in rows]


async def get_statement(sid: str) -> dict[str, Any] | None:
    """取单条记录（含 payload，供重新分析）。"""
    row = await fetch_one(
        "SELECT * FROM financial_statements WHERE user_id=? AND id=?",
        (current_user_id(), sid),
    )
    if not row:
        return None
    out = dict(row)
    try:
        out["payload"] = json.loads(out.pop("payload") or "{}")
    except (TypeError, ValueError):
        out["payload"] = {}
    return out


async def delete_statement(sid: str) -> bool:
    """删除单条记录，返回是否真的删掉了。"""
    conn = await _conn()
    cur = await conn.execute(
        "DELETE FROM financial_statements WHERE user_id=? AND id=?",
        (current_user_id(), sid),
    )
    await conn.commit()
    return cur.rowcount > 0


async def update_statement_report(sid: str, report: str) -> None:
    """更新报告文本快照（重新分析后）。"""
    conn = await _conn()
    await conn.execute(
        "UPDATE financial_statements SET report=? WHERE user_id=? AND id=?",
        (report, current_user_id(), sid),
    )
    await conn.commit()

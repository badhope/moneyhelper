"""凭证写入：加锁插入、建单与草稿删除。"""

from __future__ import annotations

from typing import Any

from ..timeutil import now_str as _now
from ._core import _conn, get_write_lock
from .gl_accounts import (
    _open_period_for_date,
    _parse_date,
)
from .gl_entries_validate import _validate_lines
from .gl_entries_view import gl_get_entry


async def _insert_entry_locked(
    conn: Any,
    tenant_id: int,
    entry_date: str,
    period_id: int,
    description: str,
    normalized: list[dict[str, Any]],
    *,
    status: str,
    source: str,
    reversal_of: int | None = None,
    created_by: int | None = None,
) -> int:
    _, d = _parse_date(entry_date)
    seq_row = await (
        await conn.execute(
            "SELECT COUNT(*) AS n FROM gl_entries WHERE tenant_id=? AND period_id=?",
            (int(tenant_id), int(period_id)),
        )
    ).fetchone()
    seq = int(seq_row["n"]) + 1 if seq_row else 1
    entry_no = f"GL-{d.year}{d.month:02d}-{seq:04d}"
    now = _now()
    cur = await conn.execute(
        "INSERT INTO gl_entries(tenant_id,entry_no,entry_date,period_id,description,"
        "status,source,reversal_of,created_by,created_at,posted_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            int(tenant_id),
            entry_no,
            entry_date,
            int(period_id),
            str(description or "")[:300],
            status,
            source,
            reversal_of,
            created_by,
            now,
            now if status == "posted" else "",
        ),
    )
    entry_id = int(cur.lastrowid)
    await conn.executemany(
        "INSERT INTO gl_entry_lines(tenant_id,entry_id,line_no,account_id,"
        "debit_cents,credit_cents,memo) VALUES(?,?,?,?,?,?,?)",
        [
            (
                int(tenant_id),
                entry_id,
                int(x["line_no"]),
                int(x["account_id"]),
                int(x["debit_cents"]),
                int(x["credit_cents"]),
                x["memo"],
            )
            for x in normalized
        ],
    )
    return entry_id


async def gl_create_entry(
    tenant_id: int,
    entry_date: str,
    description: str,
    lines: Any,
    created_by: int | None = None,
) -> dict[str, Any]:
    period = await _open_period_for_date(tenant_id, entry_date)
    normalized, _total = await _validate_lines(tenant_id, lines)
    async with get_write_lock():
        conn = await _conn()
        await conn.execute("BEGIN IMMEDIATE")
        try:
            # 期间可能在等待写锁期间被关闭；事务内再确认一次。
            status_row = await (
                await conn.execute(
                    "SELECT status FROM gl_periods WHERE tenant_id=? AND id=?",
                    (int(tenant_id), int(period["id"])),
                )
            ).fetchone()
            if status_row is None or str(status_row["status"]) != "open":
                raise ValueError("会计期间已关闭，不能新增凭证")
            entry_id = await _insert_entry_locked(
                conn,
                tenant_id,
                entry_date,
                int(period["id"]),
                description,
                normalized,
                status="draft",
                source="manual",
                created_by=created_by,
            )
            await conn.execute("COMMIT")
        except BaseException:
            await conn.execute("ROLLBACK")
            raise
    created = await gl_get_entry(tenant_id, entry_id)
    assert created is not None
    return created

async def gl_delete_draft_entry(tenant_id: int, entry_id: int) -> None:
    """删除草稿凭证及其分录行；已过账凭证只能反冲，不能删除。"""
    entry = await gl_get_entry(tenant_id, entry_id)
    if entry is None:
        raise ValueError("凭证不存在")
    if entry["status"] != "draft":
        raise ValueError("只有草稿凭证可以删除")
    conn = await _conn()
    async with get_write_lock():
        await conn.execute("BEGIN IMMEDIATE")
        try:
            await conn.execute(
                "DELETE FROM gl_entry_lines WHERE tenant_id=? AND entry_id=?",
                (int(tenant_id), int(entry_id)),
            )
            await conn.execute(
                "DELETE FROM gl_entries WHERE tenant_id=? AND id=? AND status='draft'",
                (int(tenant_id), int(entry_id)),
            )
            await conn.execute("COMMIT")
        except BaseException:
            try:
                await conn.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
            raise

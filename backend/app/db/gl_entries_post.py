"""凭证过账与反冲：状态单向推进，反冲生成红字凭证。"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from ..timeutil import now_str as _now
from ._core import _conn, get_write_lock
from .gl_accounts import _open_period_for_date
from .gl_entries_view import gl_get_entry
from .gl_entries_write import _insert_entry_locked


async def gl_post_entry(tenant_id: int, entry_id: int) -> dict[str, Any]:
    conn = await _conn()
    async with get_write_lock():
        await conn.execute("BEGIN IMMEDIATE")
        try:
            entry = await (
                await conn.execute(
                    "SELECT status,period_id FROM gl_entries WHERE tenant_id=? AND id=?",
                    (int(tenant_id), int(entry_id)),
                )
            ).fetchone()
            if entry is None:
                raise ValueError("凭证不存在")
            if str(entry["status"]) != "draft":
                raise ValueError("只有草稿凭证可以过账")
            period = await (
                await conn.execute(
                    "SELECT status FROM gl_periods WHERE tenant_id=? AND id=?",
                    (int(tenant_id), int(entry["period_id"])),
                )
            ).fetchone()
            if period is None or str(period["status"]) != "open":
                raise ValueError("会计期间已关闭，不能过账")
            totals = await (
                await conn.execute(
                    "SELECT COALESCE(SUM(debit_cents),0) AS d,"
                    " COALESCE(SUM(credit_cents),0) AS c"
                    " FROM gl_entry_lines WHERE tenant_id=? AND entry_id=?",
                    (int(tenant_id), int(entry_id)),
                )
            ).fetchone()
            if totals is None or int(totals["d"]) != int(totals["c"]) or int(totals["d"]) == 0:
                raise ValueError("借贷不平衡，不能过账")
            await conn.execute(
                "UPDATE gl_entries SET status='posted',posted_at=?"
                " WHERE tenant_id=? AND id=?",
                (_now(), int(tenant_id), int(entry_id)),
            )
            await conn.execute("COMMIT")
        except BaseException:
            try:
                await conn.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
            raise
    posted = await gl_get_entry(tenant_id, entry_id)
    assert posted is not None
    return posted

async def gl_reverse_entry(
    tenant_id: int,
    entry_id: int,
    entry_date: str | None = None,
    description: str | None = None,
    created_by: int | None = None,
) -> dict[str, Any]:
    original = await gl_get_entry(tenant_id, entry_id)
    if original is None:
        raise ValueError("凭证不存在")
    if original["status"] != "posted":
        raise ValueError("只有已过账凭证可以反冲")
    if original.get("source") == "reversal":
        raise ValueError("反冲凭证不能再反冲")
    rev_date = str(entry_date or date.today().isoformat())
    period = await _open_period_for_date(tenant_id, rev_date)
    normalized = [
        {
            "line_no": idx,
            "account_id": int(line["account_id"]),
            "debit_cents": int(line["credit_cents"]),
            "credit_cents": int(line["debit_cents"]),
            "memo": line.get("memo") or "",
        }
        for idx, line in enumerate(original["lines"], 1)
    ]
    async with get_write_lock():
        conn = await _conn()
        await conn.execute("BEGIN IMMEDIATE")
        try:
            existing = await (
                await conn.execute(
                    "SELECT id FROM gl_entries"
                    " WHERE tenant_id=? AND reversal_of=? LIMIT 1",
                    (int(tenant_id), int(entry_id)),
                )
            ).fetchone()
            if existing is not None:
                raise ValueError("该凭证已经反冲过")
            status_row = await (
                await conn.execute(
                    "SELECT status FROM gl_periods WHERE tenant_id=? AND id=?",
                    (int(tenant_id), int(period["id"])),
                )
            ).fetchone()
            if status_row is None or str(status_row["status"]) != "open":
                raise ValueError("会计期间已关闭，不能反冲")
            rev_id = await _insert_entry_locked(
                conn,
                tenant_id,
                rev_date,
                int(period["id"]),
                description or f"反冲 {original['entry_no']}",
                normalized,
                status="posted",
                source="reversal",
                reversal_of=int(entry_id),
                created_by=created_by,
            )
            await conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            try:
                await conn.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
            raise ValueError("该凭证已经反冲过") from exc
        except BaseException:
            try:
                await conn.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
            raise
    reversal = await gl_get_entry(tenant_id, rev_id)
    assert reversal is not None
    return reversal

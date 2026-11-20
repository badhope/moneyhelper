"""复式总账：凭证的校验、记账、过账、反冲与试算平衡。

从 gl.py 拆出；科目与期间见 gl_accounts.py。
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from ..calculations.gl import (
    GL_NORMAL_BALANCE,
    assert_balanced,
    to_cents,
)
from ..money import yuan as _money
from ..timeutil import now_str as _now
from ._core import _conn, fetch_all, fetch_one, get_write_lock
from .gl_accounts import (
    _account_payload,
    _open_period_for_date,
    _parse_date,
    gl_get_period,
)


def _line_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "debit": _money(row.get("debit_cents")),
        "credit": _money(row.get("credit_cents")),
    }

def _entry_payload(row: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, Any]:
    debit_cents = sum(int(x.get("debit_cents") or 0) for x in lines)
    credit_cents = sum(int(x.get("credit_cents") or 0) for x in lines)
    return {
        **row,
        "debit": _money(debit_cents),
        "credit": _money(credit_cents),
        "debit_cents": debit_cents,
        "credit_cents": credit_cents,
        "lines": [_line_payload(x) for x in lines],
    }

async def gl_get_entry(tenant_id: int, entry_id: int) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT id,tenant_id,entry_no,entry_date,period_id,description,status,source,"
        "reversal_of,created_by,created_at,posted_at"
        " FROM gl_entries WHERE tenant_id=? AND id=?",
        (int(tenant_id), int(entry_id)),
    )
    if row is None:
        return None
    lines = await fetch_all(
        "SELECT id,tenant_id,entry_id,line_no,account_id,debit_cents,credit_cents,memo"
        " FROM gl_entry_lines WHERE tenant_id=? AND entry_id=? ORDER BY line_no",
        (int(tenant_id), int(entry_id)),
    )
    return _entry_payload(dict(row), lines)

async def gl_list_entries(
    tenant_id: int, period_id: int | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    clamped = max(1, min(int(limit or 200), 500))
    sql = (
        "SELECT e.id,e.tenant_id,e.entry_no,e.entry_date,e.period_id,e.description,"
        "e.status,e.source,e.reversal_of,e.created_by,e.created_at,e.posted_at,"
        "COALESCE((SELECT SUM(l.debit_cents) FROM gl_entry_lines l"
        " WHERE l.tenant_id=e.tenant_id AND l.entry_id=e.id),0) AS debit_cents,"
        "COALESCE((SELECT SUM(l.credit_cents) FROM gl_entry_lines l"
        " WHERE l.tenant_id=e.tenant_id AND l.entry_id=e.id),0) AS credit_cents"
        " FROM gl_entries e WHERE e.tenant_id=?"
    )
    params: list[Any] = [int(tenant_id)]
    if period_id is not None:
        sql += " AND e.period_id=?"
        params.append(int(period_id))
    sql += " ORDER BY e.id DESC LIMIT ?"
    params.append(clamped)
    rows = await fetch_all(sql, tuple(params))
    return [
        {
            **r,
            "debit": _money(r.get("debit_cents")),
            "credit": _money(r.get("credit_cents")),
        }
        for r in rows
    ]

async def _validate_lines(
    tenant_id: int, lines: Any
) -> tuple[list[dict[str, Any]], int]:
    assert_balanced(lines)
    # 一次取齐所有科目，避免逐行查询（凭证行数多时是 N 次往返）。
    wanted = {int(line.get("account_id") or 0) for line in lines}
    wanted.discard(0)
    accounts: dict[int, dict[str, Any]] = {}
    if wanted:
        placeholders = ",".join("?" * len(wanted))
        rows = await fetch_all(
            "SELECT id,tenant_id,code,name,type,parent_id,is_active,created_at"
            f" FROM gl_accounts WHERE tenant_id=? AND id IN ({placeholders})",
            (int(tenant_id), *sorted(wanted)),
        )
        accounts = {int(r["id"]): _account_payload(dict(r)) for r in rows}
    normalized: list[dict[str, Any]] = []
    for idx, line in enumerate(lines, 1):
        account_id = int(line.get("account_id") or 0)
        account = accounts.get(account_id)
        if account is None or not account["is_active"]:
            raise ValueError(f"第 {idx} 行科目不存在或已停用")
        debit = to_cents(line.get("debit", 0))
        credit = to_cents(line.get("credit", 0))
        normalized.append(
            {
                "line_no": idx,
                "account_id": account_id,
                "debit_cents": debit,
                "credit_cents": credit,
                "memo": str(line.get("memo") or "")[:200],
            }
        )
    total = sum(x["debit_cents"] for x in normalized)
    return normalized, total

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

async def gl_trial_balance(tenant_id: int, period_id: int) -> dict[str, Any]:
    period = await gl_get_period(tenant_id, period_id)
    if period is None:
        raise ValueError("会计期间不存在")
    rows = await fetch_all(
        "SELECT a.id,a.code,a.name,a.type,"
        "COALESCE(SUM(l.debit_cents),0) AS debit_cents,"
        "COALESCE(SUM(l.credit_cents),0) AS credit_cents"
        " FROM gl_entry_lines l"
        " JOIN gl_entries e ON e.id=l.entry_id AND e.tenant_id=l.tenant_id"
        " JOIN gl_accounts a ON a.id=l.account_id AND a.tenant_id=l.tenant_id"
        " WHERE l.tenant_id=? AND e.period_id=? AND e.status='posted'"
        " GROUP BY a.id,a.code,a.name,a.type ORDER BY a.code",
        (int(tenant_id), int(period_id)),
    )
    items = []
    total_debit = 0
    total_credit = 0
    for r in rows:
        debit = int(r.get("debit_cents") or 0)
        credit = int(r.get("credit_cents") or 0)
        total_debit += debit
        total_credit += credit
        items.append(
            {
                "account_id": r["id"],
                "code": r["code"],
                "name": r["name"],
                "type": r["type"],
                "normal_balance": GL_NORMAL_BALANCE.get(str(r["type"]), ""),
                "debit": _money(debit),
                "credit": _money(credit),
                "balance": _money(debit - credit),
                "debit_cents": debit,
                "credit_cents": credit,
            }
        )
    return {
        "period": period,
        "items": items,
        "total_debit": _money(total_debit),
        "total_credit": _money(total_credit),
        "total_debit_cents": total_debit,
        "total_credit_cents": total_credit,
        "balanced": total_debit == total_credit,
    }

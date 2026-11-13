"""复式总账数据层（切片 4）：科目、期间、凭证、过账、反冲、试算表。

金额在库里一律存整数分；API 层再转成元。所有操作按 tenant_id 隔离，
不读写现有单式 `transactions`。
"""

from __future__ import annotations

import calendar
import sqlite3
from datetime import date, datetime
from typing import Any

from ..calculations.gl import (
    GL_ACCOUNT_TYPES,
    GL_NORMAL_BALANCE,
    assert_balanced,
    to_cents,
)
from ._core import _conn, fetch_all, fetch_one, get_write_lock


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _row(value: Any) -> dict[str, Any] | None:
    return dict(value) if value is not None else None


def _money(cents: Any) -> float:
    return round(int(cents or 0) / 100, 2)


def _parse_date(value: Any) -> tuple[str, date]:
    s = str(value or "").strip()
    try:
        d = date.fromisoformat(s)
    except ValueError:
        raise ValueError("日期需为 YYYY-MM-DD") from None
    return s, d


def _account_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "is_active": bool(row.get("is_active")),
        "normal_balance": GL_NORMAL_BALANCE.get(str(row.get("type")), ""),
    }


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


# ---------------------------------------------------------------------------
# 科目
# ---------------------------------------------------------------------------


async def gl_get_account(tenant_id: int, account_id: int) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT id,tenant_id,code,name,type,parent_id,is_active,created_at"
        " FROM gl_accounts WHERE tenant_id=? AND id=?",
        (int(tenant_id), int(account_id)),
    )
    return _account_payload(dict(row)) if row is not None else None


async def gl_list_accounts(tenant_id: int) -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT id,tenant_id,code,name,type,parent_id,is_active,created_at"
        " FROM gl_accounts WHERE tenant_id=? ORDER BY code",
        (int(tenant_id),),
    )
    return [_account_payload(x) for x in rows]


async def gl_create_account(
    tenant_id: int,
    code: str,
    name: str,
    account_type: str,
    parent_id: int | None = None,
) -> dict[str, Any]:
    clean_code = str(code or "").strip()[:20]
    clean_name = str(name or "").strip()[:80]
    if not clean_code or not clean_name:
        raise ValueError("科目编码和名称不能为空")
    if account_type not in GL_ACCOUNT_TYPES:
        raise ValueError(f"科目类型只能是 {'/'.join(GL_ACCOUNT_TYPES)}")
    if parent_id not in (None, ""):
        parent = await gl_get_account(tenant_id, int(parent_id))
        if parent is None:
            raise ValueError("上级科目不存在或不属于当前租户")
        parent_id = int(parent_id)
    else:
        parent_id = None
    conn = await _conn()
    try:
        cur = await conn.execute(
            "INSERT INTO gl_accounts(tenant_id,code,name,type,parent_id,is_active,created_at)"
            " VALUES(?,?,?,?,?,1,?)",
            (int(tenant_id), clean_code, clean_name, account_type, parent_id, _now()),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("科目编码已存在") from exc
    await conn.commit()
    created = await gl_get_account(tenant_id, int(cur.lastrowid))
    assert created is not None
    return created


# ---------------------------------------------------------------------------
# 会计期间
# ---------------------------------------------------------------------------


async def gl_get_period(tenant_id: int, period_id: int) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT id,tenant_id,year,month,start_date,end_date,status,created_at,closed_at"
        " FROM gl_periods WHERE tenant_id=? AND id=?",
        (int(tenant_id), int(period_id)),
    )
    return _row(row)


async def gl_list_periods(tenant_id: int) -> list[dict[str, Any]]:
    return await fetch_all(
        "SELECT p.id,p.tenant_id,p.year,p.month,p.start_date,p.end_date,p.status,"
        "p.created_at,p.closed_at,"
        "(SELECT COUNT(*) FROM gl_entries e WHERE e.tenant_id=p.tenant_id"
        " AND e.period_id=p.id AND e.status='posted') AS posted_entries,"
        "(SELECT COUNT(*) FROM gl_entries e WHERE e.tenant_id=p.tenant_id"
        " AND e.period_id=p.id AND e.status='draft') AS draft_entries"
        " FROM gl_periods p WHERE p.tenant_id=? ORDER BY p.year DESC,p.month DESC",
        (int(tenant_id),),
    )


async def gl_create_period(tenant_id: int, year: int, month: int) -> dict[str, Any]:
    try:
        year_i = int(year)
        month_i = int(month)
    except (TypeError, ValueError):
        raise ValueError("year/month 必须是整数") from None
    if not 2000 <= year_i <= 2100 or not 1 <= month_i <= 12:
        raise ValueError("year 需在 2000-2100，month 需在 1-12")
    last_day = calendar.monthrange(year_i, month_i)[1]
    start = date(year_i, month_i, 1).isoformat()
    end = date(year_i, month_i, last_day).isoformat()
    conn = await _conn()
    try:
        cur = await conn.execute(
            "INSERT INTO gl_periods(tenant_id,year,month,start_date,end_date,status,created_at)"
            " VALUES(?,?,?,?,?,'open',?)",
            (int(tenant_id), year_i, month_i, start, end, _now()),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("该会计期间已存在") from exc
    await conn.commit()
    created = await gl_get_period(tenant_id, int(cur.lastrowid))
    assert created is not None
    return created


async def gl_close_period(tenant_id: int, period_id: int) -> dict[str, Any]:
    period = await gl_get_period(tenant_id, period_id)
    if period is None:
        raise ValueError("会计期间不存在")
    if period["status"] == "closed":
        return period
    conn = await _conn()
    async with get_write_lock():
        await conn.execute("BEGIN IMMEDIATE")
        try:
            # 在事务内复查草稿：避免“检查时无草稿、关账后新草稿插入”的竞态。
            drafts = await (
                await conn.execute(
                    "SELECT COUNT(*) AS n FROM gl_entries"
                    " WHERE tenant_id=? AND period_id=? AND status='draft'",
                    (int(tenant_id), int(period_id)),
                )
            ).fetchone()
            if drafts and int(drafts["n"]) > 0:
                raise ValueError("期间内仍有草稿凭证，先过账或删除后再关账")
            await conn.execute(
                "UPDATE gl_periods SET status='closed',closed_at=?"
                " WHERE tenant_id=? AND id=?",
                (_now(), int(tenant_id), int(period_id)),
            )
            await conn.execute("COMMIT")
        except BaseException:
            try:
                await conn.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
            raise
    closed = await gl_get_period(tenant_id, period_id)
    assert closed is not None
    return closed


async def _open_period_for_date(tenant_id: int, entry_date: str) -> dict[str, Any]:
    _, d = _parse_date(entry_date)
    row = await fetch_one(
        "SELECT id,tenant_id,year,month,start_date,end_date,status,created_at,closed_at"
        " FROM gl_periods WHERE tenant_id=? AND year=? AND month=?",
        (int(tenant_id), d.year, d.month),
    )
    if row is None:
        raise ValueError("该日期所属会计期间未打开，请先创建期间")
    period = dict(row)
    if period["status"] != "open":
        raise ValueError("会计期间已关闭，不能新增或过账凭证")
    return period


# ---------------------------------------------------------------------------
# 凭证
# ---------------------------------------------------------------------------


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
    normalized: list[dict[str, Any]] = []
    for idx, line in enumerate(lines, 1):
        account_id = int(line.get("account_id") or 0)
        account = await gl_get_account(tenant_id, account_id)
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


# ---------------------------------------------------------------------------
# 试算表
# ---------------------------------------------------------------------------


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

"""备份恢复·复式总账：科目/期间/凭证/分录，内部 ID 全部重映射。"""

from __future__ import annotations

from typing import Any

import aiosqlite


async def _restore_gl(
    conn: aiosqlite.Connection, data: dict[str, Any], tenant_id: int
) -> dict[str, int]:
    """恢复总账并重映射内部 ID（科目/期间/凭证/分录行）。

    备份里的 id/外键只在原库有意义；跨库恢复必须重新分配，否则会与
    其他租户的全局自增 id 冲突，或把分录挂到错误的凭证上。
    """

    def rows(name: str) -> list[dict[str, Any]]:
        raw = data.get(name) or []
        if not isinstance(raw, list) or any(not isinstance(x, dict) for x in raw):
            raise ValueError(f"{name} 备份格式不正确")
        return raw

    accounts = rows("gl_accounts")
    periods = rows("gl_periods")
    entries = rows("gl_entries")
    lines = rows("gl_entry_lines")

    for table in ("gl_entry_lines", "gl_entries", "gl_periods", "gl_accounts"):
        await conn.execute(
            f"DELETE FROM {table} WHERE tenant_id=?", (int(tenant_id),)
        )

    account_map: dict[int, int] = {}
    for a in accounts:
        cur = await conn.execute(
            "INSERT INTO gl_accounts(tenant_id,code,name,type,parent_id,is_active,created_at)"
            " VALUES(?,?,?,?,NULL,?,?)",
            (
                int(tenant_id),
                str(a.get("code") or "")[:20],
                str(a.get("name") or "")[:80],
                str(a.get("type") or ""),
                int(a.get("is_active", 1) or 0),
                str(a.get("created_at") or ""),
            ),
        )
        account_map[int(a["id"])] = int(cur.lastrowid)
    for a in accounts:
        parent = a.get("parent_id")
        if parent is None:
            continue
        parent_id = account_map.get(int(parent))
        if parent_id is None:
            raise ValueError("总账科目上级引用缺失")
        await conn.execute(
            "UPDATE gl_accounts SET parent_id=? WHERE tenant_id=? AND id=?",
            (parent_id, int(tenant_id), account_map[int(a["id"])]),
        )

    period_map: dict[int, int] = {}
    for p in periods:
        cur = await conn.execute(
            "INSERT INTO gl_periods(tenant_id,year,month,start_date,end_date,status,"
            "created_at,closed_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                int(p.get("year") or 0),
                int(p.get("month") or 0),
                str(p.get("start_date") or ""),
                str(p.get("end_date") or ""),
                str(p.get("status") or "open"),
                str(p.get("created_at") or ""),
                str(p.get("closed_at") or ""),
            ),
        )
        period_map[int(p["id"])] = int(cur.lastrowid)

    entry_map: dict[int, int] = {}
    for e in entries:
        period_id = period_map.get(int(e.get("period_id") or 0))
        if period_id is None:
            raise ValueError("总账凭证的期间引用缺失")
        cur = await conn.execute(
            "INSERT INTO gl_entries(tenant_id,entry_no,entry_date,period_id,description,"
            "status,source,reversal_of,created_by,created_at,posted_at)"
            " VALUES(?,?,?,?,?,?,?,NULL,?,?,?)",
            (
                int(tenant_id),
                str(e.get("entry_no") or ""),
                str(e.get("entry_date") or ""),
                period_id,
                str(e.get("description") or ""),
                str(e.get("status") or "draft"),
                str(e.get("source") or "manual"),
                e.get("created_by"),
                str(e.get("created_at") or ""),
                str(e.get("posted_at") or ""),
            ),
        )
        entry_map[int(e["id"])] = int(cur.lastrowid)
    for e in entries:
        rev = e.get("reversal_of")
        if rev is None:
            continue
        rev_id = entry_map.get(int(rev))
        if rev_id is None:
            raise ValueError("总账反冲引用缺失")
        await conn.execute(
            "UPDATE gl_entries SET reversal_of=? WHERE tenant_id=? AND id=?",
            (rev_id, int(tenant_id), entry_map[int(e["id"])]),
        )

    for line in lines:
        entry_id = entry_map.get(int(line.get("entry_id") or 0))
        account_id = account_map.get(int(line.get("account_id") or 0))
        if entry_id is None or account_id is None:
            raise ValueError("总账分录行引用缺失")
        await conn.execute(
            "INSERT INTO gl_entry_lines(tenant_id,entry_id,line_no,account_id,"
            "debit_cents,credit_cents,memo) VALUES(?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                entry_id,
                int(line.get("line_no") or 0),
                account_id,
                int(line.get("debit_cents") or 0),
                int(line.get("credit_cents") or 0),
                str(line.get("memo") or "")[:200],
            ),
        )

    return {
        "gl_accounts": len(accounts),
        "gl_periods": len(periods),
        "gl_entries": len(entries),
        "gl_entry_lines": len(lines),
    }, {
        "accounts": account_map,
        "periods": period_map,
        "entries": entry_map,
    }

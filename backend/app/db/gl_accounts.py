"""复式总账：科目与会计期间的建立、查询与结账。

从 gl.py 拆出；凭证相关操作见 gl_entries.py。
"""

from __future__ import annotations

import calendar
import sqlite3
from datetime import date
from typing import Any

from ..calculations.gl import (
    GL_ACCOUNT_TYPES,
    GL_NORMAL_BALANCE,
)
from ..timeutil import now_str as _now
from ._core import _conn, fetch_all, fetch_one, get_write_lock
from ._core import row_dict as _row


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

async def gl_bootstrap(tenant_id: int, ref_date: str | None = None) -> dict[str, Any]:
    """一键建账：铺默认科目表 + 打开参考日期所在期间。

    只补缺、不覆盖：已有科目一律不碰（用户改过名字或编码的，保持原样），
    重复调用是幂等的。这是"人不用懂会计"的前提——不给用户一张空科目表。
    """
    from ..calculations.chart import DEFAULT_CHART

    have = {str(a.get("code")) for a in await gl_list_accounts(tenant_id)}
    created = 0
    for code, name, account_type in DEFAULT_CHART:
        if code in have:
            continue
        await gl_create_account(tenant_id, code, name, account_type)
        created += 1

    day = date.today()
    if ref_date:
        _, day = _parse_date(ref_date)
    try:
        period = await gl_create_period(tenant_id, day.year, day.month)
    except ValueError:
        # 期间已存在：复用，不当成错误（幂等的关键）
        row = await fetch_one(
            "SELECT * FROM gl_periods WHERE tenant_id=? AND year=? AND month=?",
            (int(tenant_id), day.year, day.month),
        )
        if row is None:
            raise
        period = dict(row)
    return {"accounts_created": created, "period": period}

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

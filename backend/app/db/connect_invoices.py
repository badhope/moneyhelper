"""发票台账：内容指纹去重、解析落库、状态流转与汇总。"""

from __future__ import annotations

import hashlib
from typing import Any

from ..logging_utils import get_logger
from ..timeutil import new_id as _new_id
from ..timeutil import now_iso as _now
from ._core import _conn, _mark_user_data, fetch_all, fetch_one, get_write_lock
from .tenant import current_user_id

log = get_logger(__name__)

INVOICE_STATUSES = ("parsed", "confirmed", "archived", "ignored")

MAX_INVOICES = 2000


def file_hash(raw: bytes) -> str:
    """内容指纹：同文件重复上传/重复扫描都能识别。"""
    return hashlib.sha256(raw).hexdigest()[:32]


# ---------------------------------------------------------------------------
# 发票
# ---------------------------------------------------------------------------


async def save_invoice(
    *,
    file_name: str,
    raw: bytes,
    parsed: dict[str, Any],
    note: str = "",
) -> dict[str, Any]:
    """归档一张发票。同内容文件已存在时返回既有记录（duplicate=True）。"""
    uid = current_user_id()
    digest = file_hash(raw)
    existing = await fetch_one(
        "SELECT id FROM invoices WHERE user_id=? AND file_hash=?", (uid, digest)
    )
    if existing:
        row = await get_invoice(str(existing["id"]))
        return {**(row or {}), "duplicate": True}

    rows = await fetch_all("SELECT id FROM invoices WHERE user_id=?", (uid,))
    if len(rows) >= MAX_INVOICES:
        raise ValueError(f"最多归档 {MAX_INVOICES} 张发票")

    iid = _new_id("inv")
    conn = await _conn()
    async with get_write_lock():
        await conn.execute(
            "INSERT INTO invoices(user_id,id,file_name,file_hash,source_format,invoice_code,"
            "invoice_number,invoice_date,buyer,seller,item,total_amount,tax_amount,tax_rate,"
            "kind,confidence,status,note,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                uid,
                iid,
                file_name[:120],
                digest,
                str(parsed.get("source_format") or "")[:20],
                str(parsed.get("invoice_code") or "")[:30],
                str(parsed.get("invoice_number") or "")[:30],
                str(parsed.get("invoice_date") or "")[:10],
                str(parsed.get("buyer") or "")[:80],
                str(parsed.get("seller") or "")[:80],
                str(parsed.get("item") or "")[:120],
                parsed.get("total_amount"),
                parsed.get("tax_amount"),
                str(parsed.get("tax_rate") or "")[:12],
                str(parsed.get("kind") or "")[:24],
                str(parsed.get("confidence") or "")[:12],
                "parsed",
                note[:200],
                _now(),
            ),
        )
        await _mark_user_data(conn)
        await conn.commit()
    return {**(await get_invoice(iid) or {}), "duplicate": False}


async def get_invoice(iid: str) -> dict[str, Any] | None:
    row = await fetch_one(
        "SELECT i.*, CASE WHEN p.invoice_id IS NULL THEN 0 ELSE 1 END AS posted"
        " FROM invoices i LEFT JOIN invoice_postings p"
        " ON p.user_id=i.user_id AND p.invoice_id=i.id"
        " WHERE i.user_id=? AND i.id=?",
        (current_user_id(), iid),
    )
    return dict(row) if row else None


async def list_invoices(limit: int = 100, status: str = "") -> list[dict[str, Any]]:
    params: list[Any] = [current_user_id()]
    sql = (
        "SELECT i.*, CASE WHEN p.invoice_id IS NULL THEN 0 ELSE 1 END AS posted"
        " FROM invoices i LEFT JOIN invoice_postings p"
        " ON p.user_id=i.user_id AND p.invoice_id=i.id"
        " WHERE i.user_id=?"
    )
    if status:
        sql += " AND i.status=?"
        params.append(status)
    sql += " ORDER BY i.created_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    return await fetch_all(sql, tuple(params))


async def list_invoices_for_post(period: str, limit: int = 200) -> list[dict[str, Any]]:
    """当期已确认、尚未入账的支出票候选。

    入账只认 `confirmed`：`parsed` 还可能缺税号/金额，`archived` 是已归档的历史票，
    都不该被批量写进总账。真正的幂等由 `invoice_postings` 唯一键兜底。
    """
    month = str(period or "").strip()
    if len(month) != 7 or month[4] != "-":
        raise ValueError("账期需为 YYYY-MM")
    rows = await fetch_all(
        "SELECT i.* FROM invoices i"
        " LEFT JOIN invoice_postings p"
        "   ON p.user_id=i.user_id AND p.invoice_id=i.id"
        " WHERE i.user_id=? AND i.status='confirmed'"
        "   AND i.invoice_date>=? AND i.invoice_date<?"
        "   AND p.invoice_id IS NULL"
        " ORDER BY i.invoice_date,i.id LIMIT ?",
        (
            current_user_id(),
            f"{month}-01",
            f"{month}-32",
            max(1, min(int(limit), 500)),
        ),
    )
    return rows


async def update_invoice_status(iid: str, status: str, note: str = "") -> dict[str, Any]:
    if status not in INVOICE_STATUSES:
        raise ValueError(f"状态只能是 {'/'.join(INVOICE_STATUSES)}")
    conn = await _conn()
    async with get_write_lock():
        cur = await conn.execute(
            "UPDATE invoices SET status=?, note=? WHERE user_id=? AND id=?",
            (status, note[:200], current_user_id(), iid),
        )
        await conn.commit()
        if cur.rowcount == 0:
            raise ValueError("发票不存在")
    return await get_invoice(iid) or {}


async def invoice_summary() -> dict[str, Any]:
    """发票汇总：张数、价税合计、税额、按月分布。"""
    rows = await fetch_all(
        "SELECT invoice_date,total_amount,tax_amount,status FROM invoices WHERE user_id=?",
        (current_user_id(),),
    )
    total_amount = round(sum(float(r["total_amount"] or 0) for r in rows), 2)
    total_tax = round(sum(float(r["tax_amount"] or 0) for r in rows), 2)
    by_month: dict[str, float] = {}
    for r in rows:
        month = str(r["invoice_date"] or "")[:7] or "未知"
        by_month[month] = round(by_month.get(month, 0.0) + float(r["total_amount"] or 0), 2)
    return {
        "count": len(rows),
        "total_amount": total_amount,
        "total_tax": total_tax,
        "by_month": [{"month": k, "amount": v} for k, v in sorted(by_month.items())],
        "pending": sum(1 for r in rows if r["status"] == "parsed"),
    }


async def delete_invoice(iid: str) -> bool:
    conn = await _conn()
    async with get_write_lock():
        cur = await conn.execute(
            "DELETE FROM invoices WHERE user_id=? AND id=?", (current_user_id(), iid)
        )
        await conn.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# 持仓对账单导入
# ---------------------------------------------------------------------------

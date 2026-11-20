"""采购单：查询/创建/提交/审批，关联供应商。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from ..calculations.gl import to_cents
from ..timeutil import now_str as _now
from ._core import _conn, fetch_all, fetch_one, get_write_lock
from .procurement_common import _amount, _parse_date
from .procurement_vendor import _assert_vendor

_PO_SELECT = (
    "SELECT po.id,po.tenant_id,po.po_no,po.vendor_id,po.order_date,po.expected_date,"
    "po.amount_cents,po.description,po.status,po.approved_by,po.approved_at,"
    "po.created_at,po.updated_at,v.code AS vendor_code,v.name AS vendor_name"
    " FROM purchase_orders po"
    " LEFT JOIN vendors v ON v.id=po.vendor_id AND v.tenant_id=po.tenant_id"
)


async def po_get(tenant_id: int, po_id: int) -> dict[str, Any] | None:
    row = await fetch_one(
        _PO_SELECT + " WHERE po.tenant_id=? AND po.id=?",
        (int(tenant_id), int(po_id)),
    )
    return _amount(row) if row is not None else None


async def po_list(tenant_id: int) -> list[dict[str, Any]]:
    return [
        _amount(r)
        for r in await fetch_all(
            _PO_SELECT + " WHERE po.tenant_id=? ORDER BY po.id DESC LIMIT 300",
            (int(tenant_id),),
        )
    ]


async def po_create(
    tenant_id: int,
    vendor_id: int,
    order_date: str,
    expected_date: str,
    amount: Any,
    description: str = "",
) -> dict[str, Any]:
    await _assert_vendor(tenant_id, vendor_id)
    order_day = _parse_date(order_date, "采购日期")
    expected = _parse_date(expected_date, "预计到货日期") if expected_date else ""
    amount_cents = to_cents(amount)
    if amount_cents <= 0:
        raise ValueError("采购金额必须大于 0")
    month = datetime.now().strftime("%Y%m")
    conn = await _conn()
    async with get_write_lock():
        await conn.execute("BEGIN IMMEDIATE")
        try:
            row = await (
                await conn.execute(
                    "SELECT COUNT(*) AS n FROM purchase_orders"
                    " WHERE tenant_id=? AND po_no LIKE ?",
                    (int(tenant_id), f"PO-{month}-%"),
                )
            ).fetchone()
            seq = int(row["n"]) + 1 if row else 1
            po_no = f"PO-{month}-{seq:04d}"
            cur = await conn.execute(
                "INSERT INTO purchase_orders(tenant_id,po_no,vendor_id,order_date,"
                "expected_date,amount_cents,description,status,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,'draft',?,?)",
                (
                    int(tenant_id),
                    po_no,
                    int(vendor_id),
                    order_day,
                    expected,
                    amount_cents,
                    str(description or "")[:300],
                    _now(),
                    _now(),
                ),
            )
            await conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            await conn.execute("ROLLBACK")
            raise ValueError("采购单号冲突，请重试") from exc
        except BaseException:
            await conn.execute("ROLLBACK")
            raise
    created = await po_get(tenant_id, int(cur.lastrowid))
    assert created is not None
    return created


async def po_submit(tenant_id: int, po_id: int) -> dict[str, Any]:
    conn = await _conn()
    cur = await conn.execute(
        "UPDATE purchase_orders SET status='submitted',updated_at=?"
        " WHERE tenant_id=? AND id=? AND status='draft'",
        (_now(), int(tenant_id), int(po_id)),
    )
    await conn.commit()
    if not cur.rowcount:
        raise ValueError("只有草稿采购单可以提交")
    po = await po_get(tenant_id, po_id)
    assert po is not None
    return po


async def po_approve(tenant_id: int, po_id: int, approved_by: int) -> dict[str, Any]:
    conn = await _conn()
    cur = await conn.execute(
        "UPDATE purchase_orders SET status='approved',approved_by=?,approved_at=?,"
        "updated_at=? WHERE tenant_id=? AND id=? AND status='submitted'",
        (_now(), int(approved_by), _now(), int(tenant_id), int(po_id)),
    )
    await conn.commit()
    if not cur.rowcount:
        raise ValueError("只有已提交采购单可以审核")
    po = await po_get(tenant_id, po_id)
    assert po is not None
    return po

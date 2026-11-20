"""应付创建与提交：先落草稿，提交后进入审批。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from ..calculations.gl import to_cents
from ..timeutil import now_str as _now
from ._core import _conn, get_write_lock
from .procurement_common import _parse_date
from .procurement_payable_query import _assert_payable_accounts, payable_get
from .procurement_po import po_get
from .procurement_vendor import _assert_vendor


async def payable_create(
    tenant_id: int,
    vendor_id: int,
    po_id: int | None,
    invoice_no: str,
    invoice_date: str,
    due_date: str,
    amount: Any,
    tax: Any,
    expense_account_id: int,
    payable_account_id: int,
) -> dict[str, Any]:
    await _assert_vendor(tenant_id, vendor_id)
    invoice_day = _parse_date(invoice_date, "发票日期")
    due = _parse_date(due_date, "到期日") if due_date else ""
    amount_cents = to_cents(amount)
    tax_cents = to_cents(tax or 0)
    if amount_cents <= 0:
        raise ValueError("应付金额必须大于 0")
    if tax_cents > amount_cents:
        raise ValueError("税额不能大于价税合计")
    if po_id not in (None, ""):
        po = await po_get(tenant_id, int(po_id))
        if po is None:
            raise ValueError("采购单不存在")
        if po["status"] != "approved":
            raise ValueError("只有已审核采购单可以生成应付")
        if int(po["vendor_id"]) != int(vendor_id):
            raise ValueError("采购单供应商与应付单不一致")
        po_id = int(po_id)
    else:
        po_id = None
    await _assert_payable_accounts(tenant_id, expense_account_id, payable_account_id)
    month = datetime.now().strftime("%Y%m")
    conn = await _conn()
    async with get_write_lock():
        await conn.execute("BEGIN IMMEDIATE")
        try:
            row = await (
                await conn.execute(
                    "SELECT COUNT(*) AS n FROM payables WHERE tenant_id=? AND payable_no LIKE ?",
                    (int(tenant_id), f"AP-{month}-%"),
                )
            ).fetchone()
            seq = int(row["n"]) + 1 if row else 1
            payable_no = f"AP-{month}-{seq:04d}"
            cur = await conn.execute(
                "INSERT INTO payables(tenant_id,payable_no,vendor_id,po_id,invoice_no,"
                "invoice_date,due_date,amount_cents,tax_cents,expense_account_id,"
                "payable_account_id,status,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,'draft',?,?)",
                (
                    int(tenant_id),
                    payable_no,
                    int(vendor_id),
                    po_id,
                    str(invoice_no or "")[:80],
                    invoice_day,
                    due,
                    amount_cents,
                    tax_cents,
                    int(expense_account_id),
                    int(payable_account_id),
                    _now(),
                    _now(),
                ),
            )
            await conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            await conn.execute("ROLLBACK")
            raise ValueError("应付单号冲突，请重试") from exc
        except BaseException:
            await conn.execute("ROLLBACK")
            raise
    created = await payable_get(tenant_id, int(cur.lastrowid))
    assert created is not None
    return created

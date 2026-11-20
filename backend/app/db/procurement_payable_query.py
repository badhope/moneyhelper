"""应付查询：单条与按租户列表，含科目校验前置数据。"""

from __future__ import annotations

from typing import Any

from ._core import fetch_all, fetch_one
from .gl import gl_get_account
from .procurement_common import _amount

_PAYABLE_SELECT = (
    "SELECT p.id,p.tenant_id,p.payable_no,p.vendor_id,p.po_id,p.invoice_no,"
    "p.invoice_date,p.due_date,p.amount_cents,p.tax_cents,p.expense_account_id,"
    "p.payable_account_id,p.status,p.gl_entry_id,p.payment_id,p.approved_by,"
    "p.approved_at,p.created_at,p.updated_at,v.code AS vendor_code,v.name AS vendor_name,"
    "po.po_no,ge.entry_no AS gl_entry_no,ge.status AS gl_status,pay.payment_no"
    " FROM payables p"
    " LEFT JOIN vendors v ON v.id=p.vendor_id AND v.tenant_id=p.tenant_id"
    " LEFT JOIN purchase_orders po ON po.id=p.po_id AND po.tenant_id=p.tenant_id"
    " LEFT JOIN gl_entries ge ON ge.id=p.gl_entry_id AND ge.tenant_id=p.tenant_id"
    " LEFT JOIN payments pay ON pay.id=p.payment_id AND pay.tenant_id=p.tenant_id"
)


async def payable_get(tenant_id: int, payable_id: int) -> dict[str, Any] | None:
    row = await fetch_one(
        _PAYABLE_SELECT + " WHERE p.tenant_id=? AND p.id=?",
        (int(tenant_id), int(payable_id)),
    )
    return _amount(row) if row is not None else None


async def payable_list(tenant_id: int) -> list[dict[str, Any]]:
    return [
        _amount(r)
        for r in await fetch_all(
            _PAYABLE_SELECT + " WHERE p.tenant_id=? ORDER BY p.id DESC LIMIT 300",
            (int(tenant_id),),
        )
    ]


async def _assert_payable_accounts(
    tenant_id: int, expense_account_id: int, payable_account_id: int
) -> None:
    expense = await gl_get_account(tenant_id, expense_account_id)
    if expense is None or not expense["is_active"] or expense["type"] not in (
        "asset",
        "expense",
    ):
        raise ValueError("借方科目必须是启用的资产或费用类科目")
    payable = await gl_get_account(tenant_id, payable_account_id)
    if payable is None or not payable["is_active"] or payable["type"] != "liability":
        raise ValueError("贷方科目必须是启用的负债类科目")

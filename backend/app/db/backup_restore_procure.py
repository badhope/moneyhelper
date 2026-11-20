"""备份恢复·采购应付：供应商/采购单/应付单，重映射科目与凭证，回传付款回填关系。"""

from __future__ import annotations

from typing import Any

import aiosqlite


async def _restore_procurement(
    conn: aiosqlite.Connection,
    data: dict[str, Any],
    tenant_id: int,
    account_map: dict[int, int],
    entry_map: dict[int, int],
) -> tuple[dict[str, int], dict[int, int], list[tuple[int, int]]]:
    """恢复供应商 / 采购单 / 应付单。

    付款与应付单互相引用（应付单记 payment_id，付款记 payable_id），
    这里先不写 payment_id，返回待回填清单，等 payments 落库后由调用方补上。
    """
    vendors = data.get("vendors") or []
    orders = data.get("purchase_orders") or []
    payables = data.get("payables") or []
    for name, rows in (
        ("vendors", vendors),
        ("purchase_orders", orders),
        ("payables", payables),
    ):
        if not isinstance(rows, list) or any(not isinstance(x, dict) for x in rows):
            raise ValueError(f"{name} 备份格式不正确")

    await conn.execute("DELETE FROM payables WHERE tenant_id=?", (int(tenant_id),))
    await conn.execute(
        "DELETE FROM purchase_orders WHERE tenant_id=?", (int(tenant_id),)
    )
    await conn.execute("DELETE FROM vendors WHERE tenant_id=?", (int(tenant_id),))

    vendor_map: dict[int, int] = {}
    for v in vendors:
        cur = await conn.execute(
            "INSERT INTO vendors(tenant_id,code,name,tax_no,contact,phone,status,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                str(v.get("code") or ""),
                str(v.get("name") or ""),
                str(v.get("tax_no") or ""),
                str(v.get("contact") or ""),
                str(v.get("phone") or ""),
                str(v.get("status") or "active"),
                str(v.get("created_at") or ""),
            ),
        )
        vendor_map[int(v["id"])] = int(cur.lastrowid)

    po_map: dict[int, int] = {}
    for po in orders:
        new_vendor = vendor_map.get(int(po.get("vendor_id") or 0))
        if new_vendor is None:
            raise ValueError("采购单关联的供应商引用缺失")
        cur = await conn.execute(
            "INSERT INTO purchase_orders(tenant_id,po_no,vendor_id,order_date,"
            "expected_date,amount_cents,description,status,approved_by,approved_at,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                str(po.get("po_no") or ""),
                new_vendor,
                str(po.get("order_date") or ""),
                str(po.get("expected_date") or ""),
                int(po.get("amount_cents") or 0),
                str(po.get("description") or ""),
                str(po.get("status") or "draft"),
                po.get("approved_by"),
                str(po.get("approved_at") or ""),
                str(po.get("created_at") or ""),
                str(po.get("updated_at") or ""),
            ),
        )
        po_map[int(po["id"])] = int(cur.lastrowid)

    payable_map: dict[int, int] = {}
    pending_payments: list[tuple[int, int]] = []
    for ap in payables:
        new_vendor = vendor_map.get(int(ap.get("vendor_id") or 0))
        if new_vendor is None:
            raise ValueError("应付单关联的供应商引用缺失")
        old_po = ap.get("po_id")
        new_po = None
        if old_po is not None:
            new_po = po_map.get(int(old_po))
            if new_po is None:
                raise ValueError("应付单关联的采购单引用缺失")
        new_expense = account_map.get(int(ap.get("expense_account_id") or 0))
        new_payable_account = account_map.get(int(ap.get("payable_account_id") or 0))
        if new_expense is None or new_payable_account is None:
            raise ValueError("应付单关联的会计科目引用缺失")
        old_entry = ap.get("gl_entry_id")
        new_entry = None
        if old_entry is not None:
            new_entry = entry_map.get(int(old_entry))
            if new_entry is None:
                raise ValueError("应付单关联的总账凭证引用缺失")
        cur = await conn.execute(
            "INSERT INTO payables(tenant_id,payable_no,vendor_id,po_id,invoice_no,"
            "invoice_date,due_date,amount_cents,tax_cents,expense_account_id,"
            "payable_account_id,status,gl_entry_id,payment_id,approved_by,approved_at,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,?,?,?)",
            (
                int(tenant_id),
                str(ap.get("payable_no") or ""),
                new_vendor,
                new_po,
                str(ap.get("invoice_no") or ""),
                str(ap.get("invoice_date") or ""),
                str(ap.get("due_date") or ""),
                int(ap.get("amount_cents") or 0),
                int(ap.get("tax_cents") or 0),
                new_expense,
                new_payable_account,
                str(ap.get("status") or "draft"),
                new_entry,
                ap.get("approved_by"),
                str(ap.get("approved_at") or ""),
                str(ap.get("created_at") or ""),
                str(ap.get("updated_at") or ""),
            ),
        )
        new_payable_id = int(cur.lastrowid)
        payable_map[int(ap["id"])] = new_payable_id
        if ap.get("payment_id") is not None:
            pending_payments.append((new_payable_id, int(ap["payment_id"])))
    return (
        {
            "vendors": len(vendors),
            "purchase_orders": len(orders),
            "payables": len(payables),
        },
        payable_map,
        pending_payments,
    )

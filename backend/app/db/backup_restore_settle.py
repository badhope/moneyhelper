"""备份恢复·报销与付款：报销单随总账凭证重映射，付款重映射应付与凭证引用。"""

from __future__ import annotations

from typing import Any

import aiosqlite


async def _restore_expenses(
    conn: aiosqlite.Connection,
    data: dict[str, Any],
    tenant_id: int,
    entry_map: dict[int, int],
) -> tuple[dict[str, int], dict[int, int]]:
    """恢复报销单；gl_entry_id 必须映射到新总账凭证 id。"""
    raw = data.get("expense_claims") or []
    if not isinstance(raw, list) or any(not isinstance(x, dict) for x in raw):
        raise ValueError("expense_claims 备份格式不正确")
    await conn.execute(
        "DELETE FROM expense_claims WHERE tenant_id=?", (int(tenant_id),)
    )
    claim_map: dict[int, int] = {}
    for c in raw:
        old_entry = c.get("gl_entry_id")
        new_entry = None
        if old_entry is not None:
            new_entry = entry_map.get(int(old_entry))
            if new_entry is None:
                raise ValueError("报销单关联的总账凭证引用缺失")
        cur = await conn.execute(
            "INSERT INTO expense_claims(tenant_id,claim_no,title,applicant_user_id,"
            "department_id,amount_cents,category,expense_account_id,credit_account_id,"
            "invoice_ref,attachment_name,status,approved_by,approved_at,"
            "rejected_reason,gl_entry_id,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                str(c.get("claim_no") or ""),
                str(c.get("title") or ""),
                int(c.get("applicant_user_id") or 0),
                c.get("department_id"),
                int(c.get("amount_cents") or 0),
                str(c.get("category") or ""),
                int(c.get("expense_account_id") or 0),
                int(c.get("credit_account_id") or 0),
                str(c.get("invoice_ref") or ""),
                str(c.get("attachment_name") or ""),
                str(c.get("status") or "draft"),
                c.get("approved_by"),
                str(c.get("approved_at") or ""),
                str(c.get("rejected_reason") or ""),
                new_entry,
                str(c.get("created_at") or ""),
                str(c.get("updated_at") or ""),
            ),
        )
        claim_map[int(c["id"])] = int(cur.lastrowid)
    return {"expense_claims": len(raw)}, claim_map

async def _restore_payments(
    conn: aiosqlite.Connection,
    data: dict[str, Any],
    tenant_id: int,
    claim_map: dict[int, int],
    payable_map: dict[int, int],
    entry_map: dict[int, int],
    account_map: dict[int, int],
) -> tuple[dict[str, int], dict[int, int]]:
    raw = data.get("payments") or []
    if not isinstance(raw, list) or any(not isinstance(x, dict) for x in raw):
        raise ValueError("payments 备份格式不正确")
    await conn.execute("DELETE FROM payments WHERE tenant_id=?", (int(tenant_id),))
    payment_map: dict[int, int] = {}
    for p in raw:
        old_claim = int(p.get("claim_id") or 0)
        claim_id = claim_map.get(old_claim) if old_claim else 0
        if old_claim and claim_id is None:
            raise ValueError("付款关联的报销单引用缺失")
        old_payable = p.get("payable_id")
        payable_id = None
        if old_payable is not None:
            payable_id = payable_map.get(int(old_payable))
            if payable_id is None:
                raise ValueError("付款关联的应付单引用缺失")
        account_id = account_map.get(int(p.get("bank_account_id") or 0))
        if account_id is None:
            raise ValueError("付款关联的银行科目引用缺失")
        old_entry = p.get("gl_entry_id")
        entry_id = None
        if old_entry is not None:
            entry_id = entry_map.get(int(old_entry))
            if entry_id is None:
                raise ValueError("付款关联的总账凭证引用缺失")
        cur = await conn.execute(
            "INSERT INTO payments(tenant_id,payment_no,claim_id,payable_id,amount_cents,"
            "payee,bank_account_id,method,status,paid_at,gl_entry_id,created_by,note,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                int(tenant_id),
                str(p.get("payment_no") or ""),
                int(claim_id or 0),
                payable_id,
                int(p.get("amount_cents") or 0),
                str(p.get("payee") or ""),
                account_id,
                str(p.get("method") or "bank"),
                str(p.get("status") or "paid"),
                str(p.get("paid_at") or ""),
                entry_id,
                p.get("created_by"),
                str(p.get("note") or ""),
                str(p.get("created_at") or ""),
                str(p.get("updated_at") or ""),
            ),
        )
        payment_map[int(p["id"])] = int(cur.lastrowid)
    return {"payments": len(raw)}, payment_map

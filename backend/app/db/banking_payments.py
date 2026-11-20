"""付款：出纳执行记录（不重复生成总账凭证）。

从 banking.py 拆出。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from ..timeutil import now_str as _now
from ._core import _conn, fetch_all, fetch_one, get_write_lock
from .expenses import expense_get_claim
from .gl import gl_get_account

_PAYMENT_SELECT = (
    "SELECT p.id,p.tenant_id,p.payment_no,p.claim_id,p.payable_id,p.amount_cents,p.payee,"
    "p.bank_account_id,p.method,p.status,p.paid_at,p.gl_entry_id,p.created_by,p.note,"
    "p.created_at,p.updated_at,c.claim_no,c.title AS claim_title,"
    "c.status AS claim_status,ap.payable_no,ap.invoice_no,"
    "ge.entry_no AS gl_entry_no,ge.status AS gl_status,"
    "a.code AS bank_account_code,a.name AS bank_account_name"
    " FROM payments p"
    " LEFT JOIN expense_claims c ON c.id=p.claim_id AND c.tenant_id=p.tenant_id"
    " LEFT JOIN payables ap ON ap.id=p.payable_id AND ap.tenant_id=p.tenant_id"
    " LEFT JOIN gl_entries ge ON ge.id=p.gl_entry_id AND ge.tenant_id=p.tenant_id"
    " LEFT JOIN gl_accounts a ON a.id=p.bank_account_id AND a.tenant_id=p.tenant_id"
)


def _money(row: Any, key: str = "amount_cents") -> dict[str, Any]:
    data = dict(row)
    data["amount"] = round(int(data.get(key) or 0) / 100, 2)
    return data


def _payment(row: Any) -> dict[str, Any]:
    return _money(row)


async def payment_get(tenant_id: int, payment_id: int) -> dict[str, Any] | None:
    row = await fetch_one(
        _PAYMENT_SELECT + " WHERE p.tenant_id=? AND p.id=?",
        (int(tenant_id), int(payment_id)),
    )
    return _payment(row) if row is not None else None


async def payment_list(tenant_id: int) -> list[dict[str, Any]]:
    return [
        _payment(r)
        for r in await fetch_all(
            _PAYMENT_SELECT + " WHERE p.tenant_id=? ORDER BY p.id DESC LIMIT 500",
            (int(tenant_id),),
        )
    ]


async def payment_create(
    tenant_id: int,
    claim_id: int,
    bank_account_id: int,
    created_by: int,
    note: str = "",
) -> dict[str, Any]:
    claim = await expense_get_claim(tenant_id, claim_id)
    if claim is None:
        raise ValueError("报销单不存在")
    if claim["status"] != "approved":
        raise ValueError("只有已通过的报销单可以付款")
    account = await gl_get_account(tenant_id, bank_account_id)
    if account is None or not account["is_active"] or account["type"] != "asset":
        raise ValueError("付款账户必须是启用的资产类科目")
    existing = await fetch_one(
        "SELECT id FROM payments WHERE tenant_id=? AND claim_id=?",
        (int(tenant_id), int(claim_id)),
    )
    if existing is not None:
        raise ValueError("该报销单已经登记过付款")
    now = _now()
    month = datetime.now().strftime("%Y%m")
    conn = await _conn()
    async with get_write_lock():
        await conn.execute("BEGIN IMMEDIATE")
        try:
            row = await (
                await conn.execute(
                    "SELECT COUNT(*) AS n FROM payments"
                    " WHERE tenant_id=? AND payment_no LIKE ?",
                    (int(tenant_id), f"PAY-{month}-%"),
                )
            ).fetchone()
            seq = int(row["n"]) + 1 if row else 1
            payment_no = f"PAY-{month}-{seq:04d}"
            cur = await conn.execute(
                "INSERT INTO payments(tenant_id,payment_no,claim_id,amount_cents,payee,"
                "bank_account_id,method,status,paid_at,created_by,note,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?, 'bank','paid',?,?,?,?,?)",
                (
                    int(tenant_id),
                    payment_no,
                    int(claim_id),
                    int(claim["amount_cents"]),
                    str(claim.get("applicant_name") or claim["title"])[:120],
                    int(bank_account_id),
                    now,
                    int(created_by),
                    str(note or "")[:300],
                    now,
                    now,
                ),
            )
            payment_id = int(cur.lastrowid)
            await conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            await conn.execute("ROLLBACK")
            raise ValueError("付款单号或报销单已被占用") from exc
        except BaseException:
            await conn.execute("ROLLBACK")
            raise
    created = await payment_get(tenant_id, payment_id)
    assert created is not None
    return created



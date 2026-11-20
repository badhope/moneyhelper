"""报销单草稿创建与提交（申请人侧）。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from ..calculations.gl import to_cents
from ..timeutil import now_str as _now
from ._core import _conn, get_write_lock
from .expenses_query import _assert_accounts, _assert_user, expense_get_claim


async def expense_create_claim(
    tenant_id: int,
    applicant_user_id: int,
    title: str,
    amount: Any,
    category: str,
    expense_account_id: int,
    credit_account_id: int,
    invoice_ref: str = "",
    attachment_name: str = "",
) -> dict[str, Any]:
    await _assert_user(applicant_user_id)
    clean_title = str(title or "").strip()[:120]
    if not clean_title:
        raise ValueError("报销事由不能为空")
    amount_cents = to_cents(amount)
    if amount_cents <= 0:
        raise ValueError("报销金额必须大于 0")
    await _assert_accounts(tenant_id, expense_account_id, credit_account_id)
    now = _now()
    month = datetime.now().strftime("%Y%m")
    conn = await _conn()
    async with get_write_lock():
        await conn.execute("BEGIN IMMEDIATE")
        try:
            row = await (
                await conn.execute(
                    "SELECT COUNT(*) AS n FROM expense_claims"
                    " WHERE tenant_id=? AND claim_no LIKE ?",
                    (int(tenant_id), f"BX-{month}-%"),
                )
            ).fetchone()
            seq = int(row["n"]) + 1 if row else 1
            claim_no = f"BX-{month}-{seq:04d}"
            cur = await conn.execute(
                "INSERT INTO expense_claims(tenant_id,claim_no,title,applicant_user_id,"
                "department_id,amount_cents,category,expense_account_id,credit_account_id,"
                "invoice_ref,attachment_name,status,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,'draft',?,?)",
                (
                    int(tenant_id),
                    claim_no,
                    clean_title,
                    int(applicant_user_id),
                    None,
                    amount_cents,
                    str(category or "")[:40],
                    int(expense_account_id),
                    int(credit_account_id),
                    str(invoice_ref or "")[:120],
                    str(attachment_name or "")[:200],
                    now,
                    now,
                ),
            )
            claim_id = int(cur.lastrowid)
            await conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            await conn.execute("ROLLBACK")
            raise ValueError("报销单号冲突，请重试") from exc
        except BaseException:
            await conn.execute("ROLLBACK")
            raise
    created = await expense_get_claim(tenant_id, claim_id)
    assert created is not None
    return created


async def expense_submit_claim(
    tenant_id: int, claim_id: int, applicant_user_id: int
) -> dict[str, Any]:
    claim = await expense_get_claim(tenant_id, claim_id)
    if claim is None:
        raise ValueError("报销单不存在")
    if int(claim["applicant_user_id"]) != int(applicant_user_id):
        raise ValueError("只能提交自己的报销单")
    conn = await _conn()
    cur = await conn.execute(
        "UPDATE expense_claims SET status='submitted',updated_at=?"
        " WHERE tenant_id=? AND id=? AND status='draft'",
        (_now(), int(tenant_id), int(claim_id)),
    )
    await conn.commit()
    if not cur.rowcount:
        raise ValueError("只有草稿报销单可以提交")
    updated = await expense_get_claim(tenant_id, claim_id)
    assert updated is not None
    return updated

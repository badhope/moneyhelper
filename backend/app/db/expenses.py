"""报销单数据层（切片 5b）：草稿 → 提交 → 审核 → 凭证草稿。

审批通过只生成总账草稿，不直接过账；过账仍由会计在 /api/gl 确认。
金额存整数分，凭证行使用精确的元字符串，避免浮点误差。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from ..calculations.gl import to_cents
from ._core import _conn, fetch_all, fetch_one, get_write_lock
from .gl import (
    gl_create_entry,
    gl_delete_draft_entry,
    gl_get_account,
)

_CLAIM_SELECT = (
    "SELECT c.id,c.tenant_id,c.claim_no,c.title,c.applicant_user_id,c.department_id,"
    "c.amount_cents,c.category,c.expense_account_id,c.credit_account_id,"
    "c.invoice_ref,c.attachment_name,c.status,c.approved_by,c.approved_at,"
    "c.rejected_reason,c.gl_entry_id,c.created_at,c.updated_at,"
    "u1.display_name AS applicant_name,u2.display_name AS approver_name,"
    "a1.code AS expense_account_code,a1.name AS expense_account_name,"
    "a2.code AS credit_account_code,a2.name AS credit_account_name,"
    "e.entry_no AS gl_entry_no,e.status AS gl_status"
    " FROM expense_claims c"
    " LEFT JOIN users u1 ON u1.id=c.applicant_user_id"
    " LEFT JOIN users u2 ON u2.id=c.approved_by"
    " LEFT JOIN gl_accounts a1 ON a1.id=c.expense_account_id AND a1.tenant_id=c.tenant_id"
    " LEFT JOIN gl_accounts a2 ON a2.id=c.credit_account_id AND a2.tenant_id=c.tenant_id"
    " LEFT JOIN gl_entries e ON e.id=c.gl_entry_id AND e.tenant_id=c.tenant_id"
)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _yuan(cents: int) -> str:
    return f"{int(cents) // 100}.{int(cents) % 100:02d}"


def _claim(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["amount"] = round(int(data.get("amount_cents") or 0) / 100, 2)
    return data


async def expense_get_claim(tenant_id: int, claim_id: int) -> dict[str, Any] | None:
    row = await fetch_one(
        _CLAIM_SELECT + " WHERE c.tenant_id=? AND c.id=?",
        (int(tenant_id), int(claim_id)),
    )
    return _claim(row) if row is not None else None


async def expense_list_claims(
    tenant_id: int, status: str | None = None
) -> list[dict[str, Any]]:
    sql = _CLAIM_SELECT + " WHERE c.tenant_id=?"
    params: list[Any] = [int(tenant_id)]
    if status:
        sql += " AND c.status=?"
        params.append(str(status))
    sql += " ORDER BY c.id DESC LIMIT 500"
    return [_claim(r) for r in await fetch_all(sql, tuple(params))]


async def _assert_user(user_id: int) -> dict[str, Any]:
    if int(user_id) == 0:
        # 本机/共享口令模式没有 users 行，0 代表实例所有者。
        return {"id": 0, "username": "local", "display_name": "本机用户", "disabled": 0}
    row = await fetch_one(
        "SELECT id,username,display_name,disabled FROM users WHERE id=?",
        (int(user_id),),
    )
    if row is None or int(row["disabled"] or 0) != 0:
        raise ValueError("申请人不存在或已停用")
    return dict(row)


async def _assert_accounts(
    tenant_id: int, expense_account_id: int, credit_account_id: int
) -> None:
    expense = await gl_get_account(tenant_id, expense_account_id)
    if expense is None or not expense["is_active"]:
        raise ValueError("费用科目不存在或已停用")
    if expense["type"] != "expense":
        raise ValueError("借方科目必须是费用类科目")
    credit = await gl_get_account(tenant_id, credit_account_id)
    if credit is None or not credit["is_active"]:
        raise ValueError("贷方科目不存在或已停用")
    if credit["type"] not in ("asset", "liability"):
        raise ValueError("贷方科目必须是资产或负债类科目")


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


async def expense_approve_claim(
    tenant_id: int,
    claim_id: int,
    approver_user_id: int,
    *,
    allow_self_approval: bool = False,
    entry_date: str | None = None,
) -> dict[str, Any]:
    claim = await expense_get_claim(tenant_id, claim_id)
    if claim is None:
        raise ValueError("报销单不存在")
    if claim["status"] != "submitted":
        raise ValueError("只有已提交的报销单可以审核")
    if (
        int(claim["applicant_user_id"]) == int(approver_user_id)
        and not allow_self_approval
    ):
        raise ValueError("申请人不能审批自己的报销单")
    await _assert_accounts(
        tenant_id, int(claim["expense_account_id"]), int(claim["credit_account_id"])
    )
    conn = await _conn()
    # 抢占式状态：避免两个审批人同时通过、重复生成凭证。
    cur = await conn.execute(
        "UPDATE expense_claims SET status='approving',updated_at=?"
        " WHERE tenant_id=? AND id=? AND status='submitted'",
        (_now(), int(tenant_id), int(claim_id)),
    )
    await conn.commit()
    if not cur.rowcount:
        raise ValueError("报销单已被处理")

    amount = _yuan(int(claim["amount_cents"]))
    try:
        entry = await gl_create_entry(
            tenant_id,
            str(entry_date or datetime.now().date().isoformat()),
            f"报销 {claim['claim_no']} {claim['title']}",
            [
                {
                    "account_id": int(claim["expense_account_id"]),
                    "debit": amount,
                    "credit": 0,
                    "memo": claim["category"],
                },
                {
                    "account_id": int(claim["credit_account_id"]),
                    "debit": 0,
                    "credit": amount,
                    "memo": "报销付款",
                },
            ],
            approver_user_id,
        )
    except Exception:
        await conn.execute(
            "UPDATE expense_claims SET status='submitted',updated_at=? WHERE tenant_id=? AND id=?",
            (_now(), int(tenant_id), int(claim_id)),
        )
        await conn.commit()
        raise

    try:
        await conn.execute(
            "UPDATE expense_claims SET status='approved',approved_by=?,approved_at=?,"
            "gl_entry_id=?,updated_at=? WHERE tenant_id=? AND id=?",
            (
                int(approver_user_id),
                _now(),
                int(entry["id"]),
                _now(),
                int(tenant_id),
                int(claim_id),
            ),
        )
        await conn.commit()
    except BaseException:
        await conn.execute(
            "UPDATE expense_claims SET status='submitted',updated_at=? WHERE tenant_id=? AND id=?",
            (_now(), int(tenant_id), int(claim_id)),
        )
        await conn.commit()
        # 不要让已生成的凭证草稿变成孤儿
        try:
            await gl_delete_draft_entry(tenant_id, int(entry["id"]))
        except Exception:  # noqa: BLE001
            pass
        raise
    approved = await expense_get_claim(tenant_id, claim_id)
    assert approved is not None
    return approved


async def expense_reject_claim(
    tenant_id: int,
    claim_id: int,
    approver_user_id: int,
    reason: str = "",
    *,
    allow_self_approval: bool = False,
) -> dict[str, Any]:
    claim = await expense_get_claim(tenant_id, claim_id)
    if claim is None:
        raise ValueError("报销单不存在")
    if claim["status"] != "submitted":
        raise ValueError("只有已提交的报销单可以驳回")
    if (
        int(claim["applicant_user_id"]) == int(approver_user_id)
        and not allow_self_approval
    ):
        raise ValueError("申请人不能审批自己的报销单")
    conn = await _conn()
    cur = await conn.execute(
        "UPDATE expense_claims SET status='rejected',approved_by=?,approved_at=?,"
        "rejected_reason=?,updated_at=? WHERE tenant_id=? AND id=? AND status='submitted'",
        (
            int(approver_user_id),
            _now(),
            str(reason or "")[:300],
            _now(),
            int(tenant_id),
            int(claim_id),
        ),
    )
    await conn.commit()
    if not cur.rowcount:
        raise ValueError("报销单已被处理")
    rejected = await expense_get_claim(tenant_id, claim_id)
    assert rejected is not None
    return rejected

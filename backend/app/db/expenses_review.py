"""报销单审批与驳回（含凭证草稿的生成/回滚）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..money import yuan_str as _yuan
from ..timeutil import now_str as _now
from ._core import _conn
from .expenses_query import _assert_accounts, expense_get_claim
from .gl import gl_create_entry, gl_delete_draft_entry


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

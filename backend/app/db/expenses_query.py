"""报销单查询层：列表/详情读取与申请人、科目校验。"""

from __future__ import annotations

from typing import Any

from ..money import yuan
from ._core import fetch_all, fetch_one
from .gl import gl_get_account

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






def _claim(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["amount"] = yuan(data.get("amount_cents"))
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

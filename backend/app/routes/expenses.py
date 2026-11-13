"""报销单 API（切片 5b）：草稿 → 提交 → 审核 → 凭证草稿。

权限：
- 读/创建/提交：目标租户的有效成员；
- 审核/驳回：目标租户 owner/admin/approver；
- 本机/共享口令模式放行，且允许自审（单用户无法分离申请人/审批人）；
- 企业租户强制申请人≠审批人，审批通过只生成凭证草稿。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from .. import auth, db
from ..db.tenant import current_user_id
from ._scope import tenant_permission_scope

router = APIRouter()


def _bad(msg: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=code)


async def expense_scope(
    tenant_id: int | None = Query(default=None),
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    """读报销单：目标租户的有效成员。"""
    return await tenant_permission_scope(
        tenant_id, user, "expense:read", denied_detail="需要该租户的审核权限"
    )


async def expense_create_scope(
    tenant_id: int | None = Query(default=None),
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    """新建/提交报销单：与读分开计权限点（只读角色不应能建单）。"""
    return await tenant_permission_scope(
        tenant_id, user, "expense:create", denied_detail="需要该租户的审核权限"
    )


async def expense_approve_scope(
    tenant_id: int | None = Query(default=None),
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    """审核/驳回：目标租户 owner/admin/approver。"""
    return await tenant_permission_scope(
        tenant_id, user, "expense:approve", denied_detail="需要该租户的审核权限"
    )


@router.get("/api/expenses")
async def list_expenses(
    status: str | None = None,
    scope: int = Depends(expense_scope),
) -> Any:
    return {"claims": await db.expense_list_claims(scope, status)}


@router.get("/api/expenses/{claim_id}")
async def get_expense(claim_id: int, scope: int = Depends(expense_scope)) -> Any:
    claim = await db.expense_get_claim(scope, claim_id)
    if claim is None:
        return _bad("报销单不存在", 404)
    return claim


@router.post("/api/expenses")
async def create_expense(
    payload: dict[str, Any],
    scope: int = Depends(expense_create_scope),
) -> Any:
    try:
        claim = await db.expense_create_claim(
            scope,
            current_user_id(),
            str((payload or {}).get("title") or ""),
            (payload or {}).get("amount"),
            str((payload or {}).get("category") or ""),
            int((payload or {}).get("expense_account_id") or 0),
            int((payload or {}).get("credit_account_id") or 0),
            str((payload or {}).get("invoice_ref") or ""),
            str((payload or {}).get("attachment_name") or ""),
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "claim": claim}


@router.post("/api/expenses/{claim_id}/submit")
async def submit_expense(
    claim_id: int, scope: int = Depends(expense_create_scope)
) -> Any:
    try:
        claim = await db.expense_submit_claim(scope, claim_id, current_user_id())
    except ValueError as exc:
        return _bad(str(exc))
    return {"ok": True, "claim": claim}


@router.post("/api/expenses/{claim_id}/approve")
async def approve_expense(
    claim_id: int,
    payload: dict[str, Any] | None = None,
    scope: int = Depends(expense_approve_scope),
) -> Any:
    try:
        claim = await db.expense_approve_claim(
            scope,
            claim_id,
            current_user_id(),
            allow_self_approval=scope == 0,
            entry_date=(payload or {}).get("entry_date"),
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "claim": claim}


@router.post("/api/expenses/{claim_id}/reject")
async def reject_expense(
    claim_id: int,
    payload: dict[str, Any] | None = None,
    scope: int = Depends(expense_approve_scope),
) -> Any:
    try:
        claim = await db.expense_reject_claim(
            scope,
            claim_id,
            current_user_id(),
            str((payload or {}).get("reason") or ""),
            allow_self_approval=scope == 0,
        )
    except ValueError as exc:
        return _bad(str(exc))
    return {"ok": True, "claim": claim}

"""付款与银行流水 API（切片 6）。

付款登记与银行匹配是出纳/会计操作，不直接改总账；匹配只做流水与付款的勾稽。
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


async def bank_read_scope(
    tenant_id: int | None = Query(default=None),
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    """读付款/流水/对账：目标租户的有效成员。"""
    return await tenant_permission_scope(tenant_id, user, "payment:read")


async def bank_write_scope(
    tenant_id: int | None = Query(default=None),
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    """登记付款：owner/admin/accountant。"""
    return await tenant_permission_scope(tenant_id, user, "payment:create")


async def bank_txn_read_scope(
    tenant_id: int | None = Query(default=None),
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    """读银行流水：与付款读同口径（当前租户有效成员）。"""
    return await tenant_permission_scope(tenant_id, user, "bank:read")


async def bank_txn_write_scope(
    tenant_id: int | None = Query(default=None),
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    """新增/导入银行流水：owner/admin/accountant。"""
    return await tenant_permission_scope(tenant_id, user, "bank:write")


async def bank_match_scope(
    tenant_id: int | None = Query(default=None),
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    """匹配/取消匹配流水：独立权限点。"""
    return await tenant_permission_scope(tenant_id, user, "bank:match")


async def recon_read_scope(
    tenant_id: int | None = Query(default=None),
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    """读对账记录：目标租户的有效成员。"""
    return await tenant_permission_scope(tenant_id, user, "reconciliation:read")


async def recon_write_scope(
    tenant_id: int | None = Query(default=None),
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    """新建对账会话：owner/admin/accountant。"""
    return await tenant_permission_scope(tenant_id, user, "reconciliation:write")


async def recon_sign_scope(
    tenant_id: int | None = Query(default=None),
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    """签核关账：独立权限点。"""
    return await tenant_permission_scope(tenant_id, user, "reconciliation:sign")


@router.get("/api/payments")
async def list_payments(scope: int = Depends(bank_read_scope)) -> Any:
    return {"payments": await db.payment_list(scope)}


@router.post("/api/payments")
async def create_payment(
    payload: dict[str, Any],
    scope: int = Depends(bank_write_scope),
) -> Any:
    try:
        payment = await db.payment_create(
            scope,
            int((payload or {}).get("claim_id") or 0),
            int((payload or {}).get("bank_account_id") or 0),
            current_user_id(),
            str((payload or {}).get("note") or ""),
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "payment": payment}


@router.get("/api/bank/transactions")
async def list_bank_transactions(
    status: str | None = None,
    bank_account_id: int | None = None,
    scope: int = Depends(bank_txn_read_scope),
) -> Any:
    return {
        "transactions": await db.bank_list(scope, status, bank_account_id)
    }


@router.post("/api/bank/transactions")
async def create_bank_transaction(
    payload: dict[str, Any],
    scope: int = Depends(bank_txn_write_scope),
) -> Any:
    try:
        txn = await db.bank_create(
            scope,
            int((payload or {}).get("bank_account_id") or 0),
            str((payload or {}).get("txn_date") or ""),
            str((payload or {}).get("direction") or ""),
            (payload or {}).get("amount"),
            str((payload or {}).get("counterparty") or ""),
            str((payload or {}).get("memo") or ""),
            str((payload or {}).get("bank_ref") or ""),
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "transaction": txn}


@router.post("/api/bank/import")
async def import_bank_csv(
    payload: dict[str, Any],
    scope: int = Depends(bank_txn_write_scope),
) -> Any:
    try:
        result = await db.bank_import_csv(
            scope,
            int((payload or {}).get("bank_account_id") or 0),
            str((payload or {}).get("csv") or ""),
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, **result}


@router.post("/api/bank/transactions/{txn_id}/match")
async def match_bank_transaction(
    txn_id: int,
    payload: dict[str, Any],
    scope: int = Depends(bank_match_scope),
) -> Any:
    try:
        txn = await db.bank_match(
            scope,
            txn_id,
            int((payload or {}).get("payment_id") or 0),
            current_user_id(),
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "transaction": txn}


@router.post("/api/bank/transactions/{txn_id}/unmatch")
async def unmatch_bank_transaction(
    txn_id: int, scope: int = Depends(bank_match_scope)
) -> Any:
    try:
        txn = await db.bank_unmatch(scope, txn_id)
    except ValueError as exc:
        return _bad(str(exc))
    return {"ok": True, "transaction": txn}


@router.get("/api/bank/summary")
async def bank_summary(
    bank_account_id: int | None = None,
    scope: int = Depends(bank_txn_read_scope),
) -> Any:
    return await db.bank_summary(scope, bank_account_id)


@router.get("/api/bank/reconciliations")
async def list_reconciliations(scope: int = Depends(recon_read_scope)) -> Any:
    return {"reconciliations": await db.reconciliation_list(scope)}


@router.post("/api/bank/reconciliations")
async def create_reconciliation(
    payload: dict[str, Any],
    scope: int = Depends(recon_write_scope),
) -> Any:
    try:
        recon = await db.reconciliation_create(
            scope,
            int((payload or {}).get("bank_account_id") or 0),
            int((payload or {}).get("period_id") or 0),
            (payload or {}).get("statement_balance"),
            current_user_id(),
            str((payload or {}).get("note") or ""),
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "reconciliation": recon}


@router.post("/api/bank/reconciliations/{recon_id}/close")
async def close_reconciliation(
    recon_id: int, scope: int = Depends(recon_sign_scope)
) -> Any:
    try:
        recon = await db.reconciliation_close(
            scope, recon_id, current_user_id()
        )
    except ValueError as exc:
        return _bad(str(exc))
    return {"ok": True, "reconciliation": recon}

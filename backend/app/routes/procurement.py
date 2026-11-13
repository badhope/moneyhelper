"""采购与应付 API（切片 8）：供应商 → 采购单 → 应付单 → 付款。

权限（由权限点字典派生）：
- 读：目标租户有效成员；
- 维护供应商/采购单/应付单：owner/admin/accountant；
- 审核采购单/应付单：owner/admin/approver（会计不能自审）；
- 应付付款：owner/admin/accountant。
本机/共享口令模式按 local 角色放行，仍只能操作当前租户。
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


async def _read_scope(
    tenant_id: int | None = Query(default=None),
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    return await tenant_permission_scope(tenant_id, user, "procurement:read")


async def _payable_read_scope(
    tenant_id: int | None = Query(default=None),
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    return await tenant_permission_scope(tenant_id, user, "payable:read")


async def _write_scope(
    tenant_id: int | None = Query(default=None),
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    return await tenant_permission_scope(tenant_id, user, "procurement:write")


async def _approve_scope(
    tenant_id: int | None = Query(default=None),
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    return await tenant_permission_scope(
        tenant_id, user, "procurement:approve", denied_detail="需要该租户的采购审核权限"
    )


async def _payable_write_scope(
    tenant_id: int | None = Query(default=None),
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    return await tenant_permission_scope(tenant_id, user, "payable:write")


async def _payable_approve_scope(
    tenant_id: int | None = Query(default=None),
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    return await tenant_permission_scope(
        tenant_id, user, "payable:approve", denied_detail="需要该租户的应付审核权限"
    )


async def _payable_pay_scope(
    tenant_id: int | None = Query(default=None),
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    return await tenant_permission_scope(tenant_id, user, "payable:pay")


# ---------------------------------------------------------------------------
# 供应商
# ---------------------------------------------------------------------------


@router.get("/api/procurement/vendors")
async def list_vendors(scope: int = Depends(_read_scope)) -> Any:
    return {"vendors": await db.vendor_list(scope)}


@router.post("/api/procurement/vendors")
async def create_vendor(
    payload: dict[str, Any], scope: int = Depends(_write_scope)
) -> Any:
    try:
        vendor = await db.vendor_create(
            scope,
            str((payload or {}).get("code") or ""),
            str((payload or {}).get("name") or ""),
            str((payload or {}).get("tax_no") or ""),
            str((payload or {}).get("contact") or ""),
            str((payload or {}).get("phone") or ""),
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "vendor": vendor}


# ---------------------------------------------------------------------------
# 采购单
# ---------------------------------------------------------------------------


@router.get("/api/procurement/orders")
async def list_orders(scope: int = Depends(_read_scope)) -> Any:
    return {"orders": await db.po_list(scope)}


@router.post("/api/procurement/orders")
async def create_order(
    payload: dict[str, Any], scope: int = Depends(_write_scope)
) -> Any:
    data = payload or {}
    try:
        po = await db.po_create(
            scope,
            int(data.get("vendor_id") or 0),
            str(data.get("order_date") or ""),
            str(data.get("expected_date") or ""),
            data.get("amount"),
            str(data.get("description") or ""),
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "order": po}


@router.post("/api/procurement/orders/{po_id}/submit")
async def submit_order(po_id: int, scope: int = Depends(_write_scope)) -> Any:
    try:
        po = await db.po_submit(scope, po_id)
    except ValueError as exc:
        return _bad(str(exc))
    return {"ok": True, "order": po}


@router.post("/api/procurement/orders/{po_id}/approve")
async def approve_order(po_id: int, scope: int = Depends(_approve_scope)) -> Any:
    try:
        po = await db.po_approve(scope, po_id, current_user_id())
    except ValueError as exc:
        return _bad(str(exc))
    return {"ok": True, "order": po}


# ---------------------------------------------------------------------------
# 应付单
# ---------------------------------------------------------------------------


@router.get("/api/procurement/payables")
async def list_payables(scope: int = Depends(_payable_read_scope)) -> Any:
    return {"payables": await db.payable_list(scope)}


@router.get("/api/procurement/payables/{payable_id}")
async def get_payable(
    payable_id: int, scope: int = Depends(_payable_read_scope)
) -> Any:
    payable = await db.payable_get(scope, payable_id)
    if payable is None:
        return _bad("应付单不存在", 404)
    return payable


@router.post("/api/procurement/payables")
async def create_payable(
    payload: dict[str, Any], scope: int = Depends(_payable_write_scope)
) -> Any:
    data = payload or {}
    try:
        po_id = data.get("po_id")
        payable = await db.payable_create(
            scope,
            int(data.get("vendor_id") or 0),
            int(po_id) if po_id not in (None, "") else None,
            str(data.get("invoice_no") or ""),
            str(data.get("invoice_date") or ""),
            str(data.get("due_date") or ""),
            data.get("amount"),
            data.get("tax") or 0,
            int(data.get("expense_account_id") or 0),
            int(data.get("payable_account_id") or 0),
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "payable": payable}


@router.post("/api/procurement/payables/{payable_id}/submit")
async def submit_payable(
    payable_id: int, scope: int = Depends(_payable_write_scope)
) -> Any:
    try:
        payable = await db.payable_submit(scope, payable_id)
    except ValueError as exc:
        return _bad(str(exc))
    return {"ok": True, "payable": payable}


@router.post("/api/procurement/payables/{payable_id}/approve")
async def approve_payable(
    payable_id: int, scope: int = Depends(_payable_approve_scope)
) -> Any:
    try:
        payable = await db.payable_approve(scope, payable_id, current_user_id())
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "payable": payable}


@router.post("/api/procurement/payables/{payable_id}/pay")
async def pay_payable(
    payable_id: int,
    payload: dict[str, Any] | None = None,
    scope: int = Depends(_payable_pay_scope),
) -> Any:
    data = payload or {}
    try:
        payable = await db.payable_pay(
            scope,
            payable_id,
            int(data.get("bank_account_id") or 0),
            current_user_id(),
            str(data.get("note") or ""),
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "payable": payable}

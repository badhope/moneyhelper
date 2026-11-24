"""企业预算与资金计划 API（4.19.0）。

权限沿用总账：读 `gl:read`，写 `gl:write`。预算与资金计划都是管理口径，
只写计划表，不生成凭证、不触发付款。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from .. import db
from ..auth import get_current_user
from ..db.tenant import current_user_id
from ..provenance import record_provenance
from ._responses import bad as _bad
from .gl import gl_read_scope, gl_write_scope

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/api/plan/periods")
async def plan_periods(scope: int = Depends(gl_read_scope)) -> Any:
    return {"periods": await db.plan_periods(scope), "source": "gl_periods+plan_tables"}


@router.get("/api/plan/budget")
async def budget_get(period: str = "", name: str = "主预算", scope: int = Depends(gl_read_scope)) -> Any:
    try:
        return await db.budget_plan_get(scope, period, name)
    except ValueError as exc:
        return _bad(str(exc))


@router.put("/api/plan/budget")
async def budget_put(payload: dict[str, Any], scope: int = Depends(gl_write_scope)) -> Any:
    body = payload or {}
    try:
        result = await db.budget_plan_save(
            scope,
            str(body.get("period") or ""),
            body.get("lines") if isinstance(body.get("lines"), list) else [],
            str(body.get("name") or "主预算"),
            str(body.get("note") or ""),
            created_by=current_user_id(),
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    await record_provenance(
        "enterprise_budget_save", "enterprise_budget_plan", str((result.get("plan") or {}).get("id") or ""),
        after={"period": result.get("period"), "lines": len(result.get("lines") or [])}, source="api",
    )
    return {"ok": True, **result}


@router.get("/api/plan/budget/report")
async def budget_report(period: str = "", name: str = "主预算", scope: int = Depends(gl_read_scope)) -> Any:
    try:
        return await db.budget_report(scope, period, name)
    except ValueError as exc:
        return _bad(str(exc))


@router.get("/api/plan/cash")
async def cash_get(period: str = "", name: str = "资金计划", scope: int = Depends(gl_read_scope)) -> Any:
    try:
        return await db.cash_plan_get(scope, period, name)
    except ValueError as exc:
        return _bad(str(exc))


@router.put("/api/plan/cash")
async def cash_put(payload: dict[str, Any], scope: int = Depends(gl_write_scope)) -> Any:
    body = payload or {}
    try:
        result = await db.cash_plan_save(
            scope,
            str(body.get("period") or ""),
            body.get("lines") if isinstance(body.get("lines"), list) else [],
            str(body.get("name") or "资金计划"),
            body.get("opening") or 0,
            body.get("target_min") or 0,
            str(body.get("note") or ""),
            created_by=current_user_id(),
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    await record_provenance(
        "enterprise_cash_plan_save", "enterprise_cash_plan", str((result.get("plan") or {}).get("id") or ""),
        after={"period": result.get("period"), "lines": len(result.get("lines") or [])}, source="api",
    )
    return {"ok": True, **result}


@router.get("/api/plan/cash/report")
async def cash_report(period: str = "", name: str = "资金计划", scope: int = Depends(gl_read_scope)) -> Any:
    try:
        return await db.cash_report(scope, period, name)
    except ValueError as exc:
        return _bad(str(exc))

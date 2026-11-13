"""复式总账 API（切片 4）：科目、期间、凭证、过账、反冲、试算表。

权限：
- 读：当前租户的任意有效成员；
- 写：当前租户的 owner/admin/accountant；
- 本机/共享口令模式放行；不接现有单式流水。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from .. import auth, authz, authz_guard, db
from ..db.tenant import current_tenant_id, current_user_id

router = APIRouter()


def _bad(msg: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=code)


async def _require_role(
    user: dict[str, Any] | None,
    permission_id: str,
) -> int:
    """总账权限闸：按权限点字典校验，并旁路记录一次影子判定。

    允许的角色集合由字典派生（`authz.roles_with`），不在这里手写角色列表。
    """
    tenant_id = current_tenant_id()
    from ..db.org import org_role

    uid = int((user or {}).get("id") or 0)
    if user is None or uid == 0:
        # 本机无账号模式 / 共享口令：实例所有者
        await authz_guard.record(
            tenant_id=tenant_id,
            user=user,
            role=authz_guard.LOCAL_ROLE,
            permission_id=permission_id,
            allowed=True,
            reason="本机/共享口令",
        )
        return tenant_id
    role = await org_role(tenant_id, uid)
    if role is None:
        await authz_guard.record(
            tenant_id=tenant_id,
            user=user,
            role=None,
            permission_id=permission_id,
            allowed=False,
            reason="非该租户成员",
        )
        raise HTTPException(status_code=403, detail="无权访问该租户")
    if not authz.allows(role, permission_id):
        await authz_guard.record(
            tenant_id=tenant_id,
            user=user,
            role=role,
            permission_id=permission_id,
            allowed=False,
            reason=f"角色 {role} 无 {permission_id}",
        )
        raise HTTPException(status_code=403, detail="需要该租户的财务写权限")
    await authz_guard.record(
        tenant_id=tenant_id,
        user=user,
        role=role,
        permission_id=permission_id,
        allowed=True,
        reason=f"角色 {role}",
    )
    return tenant_id


async def gl_read_scope(
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    return await _require_role(user, "gl:read")


async def gl_write_scope(
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    return await _require_role(user, "gl:write")


async def gl_post_scope(
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    """过账与反冲：与维护草稿分开计权限点（职责分离）。"""
    return await _require_role(user, "gl:post")


async def gl_close_scope(
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> int:
    """关账：独立权限点。"""
    return await _require_role(user, "gl:close")


@router.get("/api/gl/accounts")
async def list_accounts(scope: int = Depends(gl_read_scope)) -> Any:
    return {"accounts": await db.gl_list_accounts(scope)}


@router.post("/api/gl/accounts")
async def create_account(
    payload: dict[str, Any],
    scope: int = Depends(gl_write_scope),
) -> Any:
    try:
        account = await db.gl_create_account(
            scope,
            str((payload or {}).get("code") or ""),
            str((payload or {}).get("name") or ""),
            str((payload or {}).get("type") or ""),
            (payload or {}).get("parent_id"),
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "account": account}


@router.get("/api/gl/periods")
async def list_periods(scope: int = Depends(gl_read_scope)) -> Any:
    return {"periods": await db.gl_list_periods(scope)}


@router.post("/api/gl/periods")
async def create_period(
    payload: dict[str, Any],
    scope: int = Depends(gl_write_scope),
) -> Any:
    try:
        period = await db.gl_create_period(
            scope,
            int((payload or {}).get("year") or 0),
            int((payload or {}).get("month") or 0),
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "period": period}


@router.post("/api/gl/periods/{period_id}/close")
async def close_period(
    period_id: int,
    scope: int = Depends(gl_close_scope),
) -> Any:
    try:
        period = await db.gl_close_period(scope, period_id)
    except ValueError as exc:
        return _bad(str(exc))
    return {"ok": True, "period": period}


@router.get("/api/gl/entries")
async def list_entries(
    period_id: int | None = None,
    limit: int = 200,
    scope: int = Depends(gl_read_scope),
) -> Any:
    return {"entries": await db.gl_list_entries(scope, period_id, limit)}


@router.post("/api/gl/entries")
async def create_entry(
    payload: dict[str, Any],
    scope: int = Depends(gl_write_scope),
) -> Any:
    try:
        entry = await db.gl_create_entry(
            scope,
            str((payload or {}).get("entry_date") or ""),
            str((payload or {}).get("description") or ""),
            (payload or {}).get("lines"),
            current_user_id(),
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "entry": entry}


@router.get("/api/gl/entries/{entry_id}")
async def get_entry(entry_id: int, scope: int = Depends(gl_read_scope)) -> Any:
    entry = await db.gl_get_entry(scope, entry_id)
    if entry is None:
        return _bad("凭证不存在", 404)
    return entry


@router.delete("/api/gl/entries/{entry_id}")
async def delete_draft_entry(
    entry_id: int, scope: int = Depends(gl_write_scope)
) -> Any:
    try:
        await db.gl_delete_draft_entry(scope, entry_id)
    except ValueError as exc:
        return _bad(str(exc))
    return {"ok": True}


@router.post("/api/gl/entries/{entry_id}/post")
async def post_entry(entry_id: int, scope: int = Depends(gl_post_scope)) -> Any:
    try:
        entry = await db.gl_post_entry(scope, entry_id)
    except ValueError as exc:
        return _bad(str(exc))
    return {"ok": True, "entry": entry}


@router.post("/api/gl/entries/{entry_id}/reverse")
async def reverse_entry(
    entry_id: int,
    payload: dict[str, Any] | None = None,
    scope: int = Depends(gl_post_scope),
) -> Any:
    try:
        entry = await db.gl_reverse_entry(
            scope,
            entry_id,
            (payload or {}).get("entry_date"),
            (payload or {}).get("description"),
            current_user_id(),
        )
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    return {"ok": True, "entry": entry}


@router.get("/api/gl/trial-balance")
async def trial_balance(
    period_id: int,
    scope: int = Depends(gl_read_scope),
) -> Any:
    try:
        return await db.gl_trial_balance(scope, period_id)
    except ValueError as exc:
        return _bad(str(exc))

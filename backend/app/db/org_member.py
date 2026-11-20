"""企业组织：成员增删改与用户校验。"""

from __future__ import annotations

from typing import Any

from ..timeutil import now_str as _now
from ._core import _conn, fetch_one
from .org import _UNSET, _role, _status
from .org_dept import _assert_tenant, _owner_count, _resolve_refs, get_member


async def _assert_user(user_id: int) -> dict[str, Any]:
    row = await fetch_one(
        "SELECT id,username,display_name,disabled FROM users WHERE id=?",
        (int(user_id),),
    )
    if row is None or int(row["disabled"] or 0) != 0:
        raise ValueError("用户不存在或已停用")
    return dict(row)

async def org_add_member(
    tenant_id: int,
    user_id: int,
    role: str = "member",
    department_id: Any = None,
    position_id: Any = None,
) -> dict[str, Any]:
    await _assert_tenant(tenant_id)
    await _assert_user(user_id)
    new_role = _role(role)
    dept, pos = await _resolve_refs(tenant_id, department_id, position_id)
    existing = await get_member(tenant_id, user_id)
    if (
        existing
        and existing.get("role") == "owner"
        and new_role != "owner"
        and await _owner_count(tenant_id) <= 1
    ):
        raise ValueError("不能降级唯一的 owner")
    conn = await _conn()
    await conn.execute(
        "INSERT INTO org_memberships(tenant_id,user_id,role,department_id,position_id,status,created_at)"
        " VALUES(?,?,?,?,?,'active',?)"
        " ON CONFLICT(tenant_id,user_id) DO UPDATE SET"
        " role=excluded.role,department_id=excluded.department_id,"
        " position_id=excluded.position_id,status='active'",
        (int(tenant_id), int(user_id), new_role, dept, pos, _now()),
    )
    await conn.commit()
    member = await get_member(tenant_id, user_id)
    assert member is not None
    return member

async def org_update_member(
    tenant_id: int,
    user_id: int,
    *,
    role: Any = None,
    department_id: Any = _UNSET,
    position_id: Any = _UNSET,
    status: Any = None,
) -> dict[str, Any]:
    existing = await get_member(tenant_id, user_id)
    if existing is None:
        raise ValueError("成员不存在")
    new_role = existing["role"] if role is None else _role(role)
    new_status = existing["status"] if status is None else _status(status)
    if (
        existing.get("role") == "owner"
        and (new_role != "owner" or new_status != "active")
        and await _owner_count(tenant_id) <= 1
    ):
        raise ValueError("不能停用或降级唯一的 owner")
    if department_id is _UNSET and position_id is _UNSET:
        dept = existing["department_id"]
        pos = existing["position_id"]
    else:
        dept_in = existing["department_id"] if department_id is _UNSET else department_id
        pos_in = existing["position_id"] if position_id is _UNSET else position_id
        dept, pos = await _resolve_refs(tenant_id, dept_in, pos_in)
    conn = await _conn()
    await conn.execute(
        "UPDATE org_memberships SET role=?,department_id=?,position_id=?,status=?"
        " WHERE tenant_id=? AND user_id=?",
        (new_role, dept, pos, new_status, int(tenant_id), int(user_id)),
    )
    await conn.commit()
    updated = await get_member(tenant_id, user_id)
    assert updated is not None
    return updated

async def org_remove_member(tenant_id: int, user_id: int) -> None:
    existing = await get_member(tenant_id, user_id)
    if existing is None:
        raise ValueError("成员不存在")
    if existing.get("role") == "owner" and await _owner_count(tenant_id) <= 1:
        raise ValueError("不能移除唯一的 owner")
    conn = await _conn()
    await conn.execute(
        "DELETE FROM org_memberships WHERE tenant_id=? AND user_id=?",
        (int(tenant_id), int(user_id)),
    )
    await conn.commit()

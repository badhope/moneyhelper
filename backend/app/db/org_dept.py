"""企业组织：部门与岗位的校验与增删改。"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..timeutil import now_str as _now
from ._core import _conn, fetch_one
from ._core import row_dict as _row
from .org import _UNSET, _status, _text
from .org_tenant import get_tenant


async def get_department(tenant_id: int, dept_id: int) -> dict[str, Any] | None:
    return _row(
        await fetch_one(
            "SELECT id,tenant_id,name,parent_id,code,status,created_at"
            " FROM org_departments WHERE tenant_id=? AND id=?",
            (int(tenant_id), int(dept_id)),
        )
    )

async def get_position(tenant_id: int, pos_id: int) -> dict[str, Any] | None:
    return _row(
        await fetch_one(
            "SELECT id,tenant_id,department_id,name,code,role_hint,status,created_at"
            " FROM org_positions WHERE tenant_id=? AND id=?",
            (int(tenant_id), int(pos_id)),
        )
    )

async def get_member(tenant_id: int, user_id: int) -> dict[str, Any] | None:
    return _row(
        await fetch_one(
            "SELECT m.id,m.tenant_id,m.user_id,m.role,m.department_id,m.position_id,"
            "m.status,m.created_at,u.username,u.display_name,u.disabled"
            " FROM org_memberships m LEFT JOIN users u ON u.id=m.user_id"
            " WHERE m.tenant_id=? AND m.user_id=?",
            (int(tenant_id), int(user_id)),
        )
    )

async def _assert_tenant(tenant_id: int) -> dict[str, Any]:
    tenant = await get_tenant(tenant_id)
    if tenant is None:
        raise ValueError("租户不存在")
    return tenant

async def _assert_department(tenant_id: int, dept_id: int) -> dict[str, Any]:
    dept = await get_department(tenant_id, dept_id)
    if dept is None:
        raise ValueError("部门不存在或不属于当前租户")
    return dept

async def _assert_position(tenant_id: int, pos_id: int) -> dict[str, Any]:
    pos = await get_position(tenant_id, pos_id)
    if pos is None:
        raise ValueError("岗位不存在或不属于当前租户")
    return pos

async def _assert_no_cycle(tenant_id: int, dept_id: int, parent_id: int | None) -> None:
    seen: set[int] = set()
    cur = parent_id
    while cur is not None:
        if int(cur) == int(dept_id):
            raise ValueError("部门层级不能成环")
        if int(cur) in seen:
            raise ValueError("部门层级存在环")
        seen.add(int(cur))
        row = await fetch_one(
            "SELECT parent_id FROM org_departments WHERE tenant_id=? AND id=?",
            (int(tenant_id), int(cur)),
        )
        if row is None:
            raise ValueError("上级部门不存在")
        cur = row["parent_id"]

async def _resolve_refs(
    tenant_id: int, department_id: Any, position_id: Any
) -> tuple[int | None, int | None]:
    dept: int | None = None
    if department_id not in (None, ""):
        dept = int(department_id)
        await _assert_department(tenant_id, dept)
    pos: int | None = None
    if position_id not in (None, ""):
        pos = int(position_id)
        row = await _assert_position(tenant_id, pos)
        pos_dept = row.get("department_id")
        if dept is None and pos_dept is not None:
            dept = int(pos_dept)
        elif dept is not None and pos_dept is not None and int(pos_dept) != dept:
            raise ValueError("岗位与部门不匹配")
    return dept, pos

async def _owner_count(tenant_id: int) -> int:
    row = await fetch_one(
        "SELECT COUNT(*) AS n FROM org_memberships"
        " WHERE tenant_id=? AND role='owner' AND status='active'",
        (int(tenant_id),),
    )
    return int(row["n"]) if row else 0

async def org_create_department(
    tenant_id: int,
    name: str,
    parent_id: int | None = None,
    code: str = "",
) -> dict[str, Any]:
    await _assert_tenant(tenant_id)
    clean_name = _text(name, 60)
    parent = None
    if parent_id not in (None, ""):
        parent = int(parent_id)
        await _assert_department(tenant_id, parent)
    conn = await _conn()
    try:
        cur = await conn.execute(
            "INSERT INTO org_departments(tenant_id,name,parent_id,code,status,created_at)"
            " VALUES(?,?,?,?,'active',?)",
            (int(tenant_id), clean_name, parent, _text(code, 20, required=False), _now()),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("部门名称已存在") from exc
    await conn.commit()
    created = await get_department(tenant_id, int(cur.lastrowid))
    assert created is not None
    return created

async def org_update_department(
    tenant_id: int,
    dept_id: int,
    *,
    name: Any = None,
    parent_id: Any = _UNSET,
    code: Any = None,
    status: Any = None,
) -> dict[str, Any]:
    existing = await _assert_department(tenant_id, dept_id)
    new_name = existing["name"] if name is None else _text(name, 60)
    new_code = existing["code"] if code is None else _text(code, 20, required=False)
    new_status = existing["status"] if status is None else _status(status)
    new_parent = existing["parent_id"] if parent_id is _UNSET else parent_id
    if new_parent not in (None, ""):
        new_parent = int(new_parent)
        if new_parent == int(dept_id):
            raise ValueError("部门不能把自己设为上级")
        await _assert_department(tenant_id, new_parent)
        await _assert_no_cycle(tenant_id, dept_id, new_parent)
    else:
        new_parent = None
    conn = await _conn()
    try:
        await conn.execute(
            "UPDATE org_departments SET name=?,parent_id=?,code=?,status=?"
            " WHERE tenant_id=? AND id=?",
            (new_name, new_parent, new_code, new_status, int(tenant_id), int(dept_id)),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("部门名称已存在") from exc
    await conn.commit()
    updated = await get_department(tenant_id, dept_id)
    assert updated is not None
    return updated

async def org_delete_department(tenant_id: int, dept_id: int) -> None:
    await _assert_department(tenant_id, dept_id)
    pos = await fetch_one(
        "SELECT COUNT(*) AS n FROM org_positions WHERE tenant_id=? AND department_id=?",
        (int(tenant_id), int(dept_id)),
    )
    if pos and int(pos["n"]) > 0:
        raise ValueError("部门下仍有岗位，先移除或改挂岗位")
    mem = await fetch_one(
        "SELECT COUNT(*) AS n FROM org_memberships WHERE tenant_id=? AND department_id=?",
        (int(tenant_id), int(dept_id)),
    )
    if mem and int(mem["n"]) > 0:
        raise ValueError("部门下仍有成员，先调整成员归属")
    conn = await _conn()
    await conn.execute(
        "DELETE FROM org_departments WHERE tenant_id=? AND id=?",
        (int(tenant_id), int(dept_id)),
    )
    await conn.commit()

async def org_create_position(
    tenant_id: int,
    name: str,
    department_id: int | None = None,
    code: str = "",
    role_hint: str = "",
) -> dict[str, Any]:
    await _assert_tenant(tenant_id)
    dept, _ = await _resolve_refs(tenant_id, department_id, None)
    conn = await _conn()
    try:
        cur = await conn.execute(
            "INSERT INTO org_positions(tenant_id,department_id,name,code,role_hint,status,created_at)"
            " VALUES(?,?,?,?,?,'active',?)",
            (
                int(tenant_id),
                dept,
                _text(name, 60),
                _text(code, 20, required=False),
                _text(role_hint, 30, required=False),
                _now(),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("岗位名称已存在") from exc
    await conn.commit()
    created = await get_position(tenant_id, int(cur.lastrowid))
    assert created is not None
    return created

async def org_update_position(
    tenant_id: int,
    pos_id: int,
    *,
    name: Any = None,
    department_id: Any = _UNSET,
    code: Any = None,
    role_hint: Any = None,
    status: Any = None,
) -> dict[str, Any]:
    existing = await _assert_position(tenant_id, pos_id)
    new_name = existing["name"] if name is None else _text(name, 60)
    new_code = existing["code"] if code is None else _text(code, 20, required=False)
    new_hint = (
        existing["role_hint"] if role_hint is None else _text(role_hint, 30, required=False)
    )
    new_status = existing["status"] if status is None else _status(status)
    if department_id is _UNSET:
        new_dept = existing["department_id"]
    elif department_id in (None, ""):
        new_dept = None
    else:
        new_dept = int(department_id)
        await _assert_department(tenant_id, new_dept)
    conn = await _conn()
    try:
        await conn.execute(
            "UPDATE org_positions SET department_id=?,name=?,code=?,role_hint=?,status=?"
            " WHERE tenant_id=? AND id=?",
            (
                new_dept,
                new_name,
                new_code,
                new_hint,
                new_status,
                int(tenant_id),
                int(pos_id),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("岗位名称已存在") from exc
    await conn.commit()
    updated = await get_position(tenant_id, pos_id)
    assert updated is not None
    return updated

async def org_delete_position(tenant_id: int, pos_id: int) -> None:
    await _assert_position(tenant_id, pos_id)
    mem = await fetch_one(
        "SELECT COUNT(*) AS n FROM org_memberships WHERE tenant_id=? AND position_id=?",
        (int(tenant_id), int(pos_id)),
    )
    if mem and int(mem["n"]) > 0:
        raise ValueError("岗位下仍有成员，先调整成员归属")
    conn = await _conn()
    await conn.execute(
        "DELETE FROM org_positions WHERE tenant_id=? AND id=?",
        (int(tenant_id), int(pos_id)),
    )
    await conn.commit()

"""企业组织影子模型（切片 1）。

只建立租户/成员/部门/岗位事实，不改变现有 `user_id` 鉴权与账本解析：

- 租户 0 = 本机账本；
- 每个现有用户 = 一个个人租户（id 与 user_id 对齐）+ owner 成员；
- 部门/岗位/成员均按 tenant_id 隔离；
- 暂不声明外键，等 current_user_id -> tenant_id 切换时再补。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from ._core import _conn, fetch_all, fetch_one

ORG_ROLES = ("owner", "admin", "accountant", "approver", "viewer", "member")
ORG_STATUSES = ("active", "archived")
_UNSET = object()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _text(value: Any, limit: int = 60, *, required: bool = True) -> str:
    s = str(value or "").strip()
    if not s and required:
        raise ValueError("名称不能为空")
    return s[:limit]


def _row(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _status(value: Any) -> str:
    s = str(value or "").strip().lower()
    if s not in ORG_STATUSES:
        raise ValueError("状态只能是 active / archived")
    return s


def _role(value: Any) -> str:
    s = str(value or "").strip().lower()
    if s not in ORG_ROLES:
        raise ValueError(f"角色只能是 {'/'.join(ORG_ROLES)}")
    return s


# ---------------------------------------------------------------------------
# 回填与个人租户
# ---------------------------------------------------------------------------


async def ensure_personal_tenant(
    conn: Any,
    user_id: int,
    username: str,
    display_name: str,
    created_at: str,
) -> None:
    """为一个用户建立个人租户与 owner 成员（init 回填与 user_create 共用）。

    不提交事务，由调用方决定；若同 id 已是企业租户则不强行挂靠。
    """
    row = await (await conn.execute("SELECT kind FROM tenants WHERE id=?", (user_id,))).fetchone()
    if row is not None and str(row["kind"]) != "personal":
        return
    name = _text(display_name or username or f"user-{user_id}", 80)
    await conn.execute(
        "INSERT OR IGNORE INTO tenants(id,name,kind,owner_user_id,status,created_at)"
        " VALUES(?,?,'personal',?,'active',?)",
        (user_id, name, user_id, created_at or _now()),
    )
    await conn.execute(
        "INSERT OR IGNORE INTO org_memberships(tenant_id,user_id,role,status,created_at)"
        " VALUES(?,?,'owner','active',?)",
        (user_id, user_id, created_at or _now()),
    )


async def backfill_org_shadow(conn: Any | None = None) -> dict[str, int]:
    """把本地账本与现有用户回填成租户/成员；可重复执行（幂等）。"""
    c = conn or await _conn()
    now = _now()
    await c.execute(
        "INSERT OR IGNORE INTO tenants(id,name,kind,owner_user_id,status,created_at)"
        " VALUES(0,'本机账本','local',0,'active',?)",
        (now,),
    )
    cur = await c.execute(
        "SELECT id,username,display_name,created_at FROM users ORDER BY id"
    )
    users = await cur.fetchall()
    for u in users:
        await ensure_personal_tenant(
            c,
            int(u["id"]),
            str(u["username"] or ""),
            str(u["display_name"] or ""),
            str(u["created_at"] or now),
        )
    tenants = await (await c.execute("SELECT COUNT(*) AS n FROM tenants")).fetchone()
    members = await (
        await c.execute("SELECT COUNT(*) AS n FROM org_memberships")
    ).fetchone()
    return {
        "tenants": int(tenants["n"]) if tenants else 0,
        "memberships": int(members["n"]) if members else 0,
    }


async def get_tenant(tenant_id: int) -> dict[str, Any] | None:
    return _row(
        await fetch_one(
            "SELECT id,name,kind,owner_user_id,status,created_at FROM tenants WHERE id=?",
            (int(tenant_id),),
        )
    )


async def resolve_tenant_id(user_id: int) -> int:
    """把登录用户映射到租户 id（切片 2 兼容层 + 切片 7b 显式切换）。

    优先级：
    1. 用户显式选择的工作租户（users.active_tenant_id），且仍是有效成员；
    2. 个人租户（id == user_id）；
    3. 有效成员资格里角色最重的一个；
    4. 都没有则保持 user_id（由后续回填兜底）。

    现有账本仍用 current_user_id()；本函数只服务企业域（组织/总账/报销/付款/对账）。
    """
    uid = int(user_id or 0)
    if uid <= 0:
        return 0
    active = await get_active_tenant(uid)
    if active is not None:
        return active
    personal = await fetch_one(
        "SELECT id FROM tenants WHERE id=? AND kind='personal' AND status='active'",
        (uid,),
    )
    if personal is not None:
        return uid
    row = await fetch_one(
        "SELECT tenant_id FROM org_memberships"
        " WHERE user_id=? AND status='active'"
        " ORDER BY CASE role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, tenant_id"
        " LIMIT 1",
        (uid,),
    )
    return int(row["tenant_id"]) if row is not None else uid


async def get_active_tenant(user_id: int) -> int | None:
    """用户显式选择的工作租户。

    没有选过、或选择已失效（成员资格被撤/停用、租户停用）都返回 None——
    失效的选择必须回落旧逻辑，不能让一个过期指针把用户带进看不见的租户。
    """
    uid = int(user_id or 0)
    if uid <= 0:
        return None
    row = await fetch_one("SELECT active_tenant_id FROM users WHERE id=?", (uid,))
    if row is None or row["active_tenant_id"] is None:
        return None
    tenant_id = int(row["active_tenant_id"])
    if tenant_id <= 0:
        return None
    if await org_role(tenant_id, uid) is None:
        return None
    return tenant_id


async def set_active_tenant(user_id: int, tenant_id: int) -> int:
    """设置用户当前工作的租户；必须是仍然有效的成员资格。

    tenant_id <= 0 表示"取消显式选择"，回到默认（个人租户优先）。
    返回落库后的租户 id（取消时返回 0）。
    """
    uid = int(user_id or 0)
    if uid <= 0:
        raise ValueError("本机模式没有可切换的账号")
    target = int(tenant_id or 0)
    if target <= 0:
        await _write_active_tenant(uid, None)
        return 0
    if await org_role(target, uid) is None:
        raise ValueError("无权切换到该租户")
    await _write_active_tenant(uid, target)
    return target


async def _write_active_tenant(user_id: int, tenant_id: int | None) -> None:
    conn = await _conn()
    await conn.execute(
        "UPDATE users SET active_tenant_id=? WHERE id=?",
        (tenant_id, int(user_id)),
    )
    await conn.commit()


async def org_role(tenant_id: int, user_id: int) -> str | None:
    row = await fetch_one(
        "SELECT role FROM org_memberships"
        " WHERE tenant_id=? AND user_id=? AND status='active'",
        (int(tenant_id), int(user_id)),
    )
    return str(row["role"]) if row is not None else None


async def list_user_tenants(user_id: int) -> list[dict[str, Any]]:
    """当前用户可进入的租户（个人 + 有效成员资格）；本机模式只返回租户 0。

    每项带 `active` 标记：是否为当前正在工作的租户（切片 7b 全局切换）。
    """
    uid = int(user_id or 0)
    if uid <= 0:
        tenant = await get_tenant(0)
        if tenant is None:
            return []
        return [{**tenant, "role": "owner", "active": True}]
    active = await get_active_tenant(uid)
    rows = await fetch_all(
        "SELECT t.id,t.name,t.kind,t.status,m.role"
        " FROM tenants t"
        " JOIN org_memberships m ON m.tenant_id=t.id"
        " WHERE m.user_id=? AND m.status='active' AND t.status='active'"
        " ORDER BY CASE t.kind WHEN 'personal' THEN 0 ELSE 1 END, t.id",
        (uid,),
    )
    resolved = active if active is not None else await resolve_tenant_id(uid)
    for row in rows:
        row["active"] = int(row["id"]) == int(resolved)
    return rows


# ---------------------------------------------------------------------------
# 读
# ---------------------------------------------------------------------------


async def org_overview(tenant_id: int) -> dict[str, Any]:
    tenant = await get_tenant(tenant_id)
    departments = await fetch_all(
        "SELECT id,tenant_id,name,parent_id,code,status,created_at"
        " FROM org_departments WHERE tenant_id=? ORDER BY id",
        (int(tenant_id),),
    )
    positions = await fetch_all(
        "SELECT id,tenant_id,department_id,name,code,role_hint,status,created_at"
        " FROM org_positions WHERE tenant_id=? ORDER BY id",
        (int(tenant_id),),
    )
    members = await fetch_all(
        "SELECT m.id,m.tenant_id,m.user_id,m.role,m.department_id,m.position_id,"
        "m.status,m.created_at,u.username,u.display_name,u.disabled"
        " FROM org_memberships m LEFT JOIN users u ON u.id=m.user_id"
        " WHERE m.tenant_id=? ORDER BY m.id",
        (int(tenant_id),),
    )
    return {
        "tenant": tenant,
        "departments": departments,
        "positions": positions,
        "members": members,
        "counts": {
            "departments": len(departments),
            "positions": len(positions),
            "members": len(members),
            "active_members": sum(1 for m in members if m.get("status") == "active"),
        },
    }


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


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 部门
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 岗位
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 成员
# ---------------------------------------------------------------------------


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

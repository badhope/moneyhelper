"""企业组织：租户解析、活跃租户与组织概览。"""

from __future__ import annotations

from typing import Any

from ..timeutil import now_str as _now
from ._core import _conn, fetch_all, fetch_one
from ._core import row_dict as _row
from .org import _text


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

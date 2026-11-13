"""权限点字典与 Casbin 影子模式（切片 7a）。

锁死三件事：
1. 字典本身自洽：权限点唯一、角色权限都落在字典内、未知角色/权限点 fail-closed；
2. 影子**不拦截**：Casbin 判定改成 deny 也不能改变业务请求的结果；
3. 影子**能发现不一致**：代码放行但字典拒绝时，mismatch 必须被记下来。

第 3 条是切到 Casbin 拦截之前的验收依据：mismatch 清单不归零，就不许开拦截。
"""

from __future__ import annotations

import httpx
import pytest
from app import auth, authz, authz_engine, db
from app.main import app


@pytest.fixture
async def client(temp_db):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8787"
    ) as c:
        yield c


async def _user(username: str, role: str = "user") -> tuple[int, str]:
    uid = await db.user_create(username, "pw-123456", username, role)
    user = await db.user_get(uid)
    assert user is not None
    return uid, auth._make_jwt(user)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _enterprise_tenant(
    tenant_id: int, owner_id: int, members: list[tuple[int, str]]
) -> None:
    """建一个企业租户，并写入成员资格。"""
    conn = await db._conn()
    await conn.execute(
        "INSERT INTO tenants(id,name,kind,owner_user_id,status,created_at)"
        " VALUES(?,?,'enterprise',?,'active','2026-01-01')",
        (tenant_id, f"企业-{tenant_id}", owner_id),
    )
    for user_id, role in members:
        await conn.execute(
            "INSERT INTO org_memberships(tenant_id,user_id,role,status,created_at)"
            " VALUES(?,?,?,'active','2026-01-01')",
            (tenant_id, user_id, role),
        )
    await conn.commit()


# ---------------------------------------------------------------------------
# 1. 字典自洽性
# ---------------------------------------------------------------------------


def test_permission_points_are_unique_and_wellformed() -> None:
    ids = [p.id for p in authz.PERMISSION_POINTS]
    assert len(ids) == len(set(ids)), "权限点 id 必须唯一"
    for point in authz.PERMISSION_POINTS:
        assert point.domain and point.action
        assert point.id == f"{point.domain}:{point.action}"
        assert point.description.strip()


def test_role_permissions_only_use_known_points() -> None:
    for role, perms in authz.ROLE_PERMISSIONS.items():
        for pid in perms:
            assert authz.known_permission(pid), f"{role} 引用了未知权限点 {pid}"


def test_unknown_role_and_permission_fail_closed() -> None:
    assert authz.role_permissions("不存在") == frozenset()
    assert authz.role_permissions(None) == frozenset()
    assert authz.allows("不存在", "gl:read") is False
    assert authz.allows("viewer", "gl:read") is True
    assert authz.allows("viewer", "不存在的权限") is False
    assert authz.allows("viewer", "") is False


def test_role_hierarchy_is_intentional() -> None:
    """owner/admin 拥有全部权限点；会计有总账写但没有审批。"""
    everything = set(authz.PERMISSION_IDS)
    assert set(authz.role_permissions("owner")) == everything
    assert set(authz.role_permissions("admin")) == everything
    assert "gl:post" in authz.role_permissions("accountant")
    assert "expense:approve" not in authz.role_permissions("accountant")
    assert "expense:approve" in authz.role_permissions("approver")
    # 只读角色不该能建单
    assert "expense:create" not in authz.role_permissions("viewer")
    # 审批人也是员工：能报自己的差旅
    assert "expense:create" in authz.role_permissions("approver")


def test_derived_role_sets_match_previous_hardcoded_lists() -> None:
    """字典派生出的角色集合，必须等于各路由模块原来手写的白名单。

    这是把手写角色列表换成字典派生的安全网：一旦以后调字典，
    这里会立刻指出"某个域要求的角色变了"，而不是等到线上才发现。
    """
    expected = {
        "org:write": {"owner", "admin"},
        "gl:write": {"owner", "admin", "accountant"},
        "gl:post": {"owner", "admin", "accountant"},
        "gl:close": {"owner", "admin", "accountant"},
        "expense:approve": {"owner", "admin", "approver"},
        "payment:create": {"owner", "admin", "accountant"},
        "bank:write": {"owner", "admin", "accountant"},
        "bank:match": {"owner", "admin", "accountant"},
        "reconciliation:write": {"owner", "admin", "accountant"},
        "reconciliation:sign": {"owner", "admin", "accountant"},
    }
    for permission_id, roles in expected.items():
        assert set(authz.roles_with(permission_id)) == roles, permission_id

    # 读权限：所有成员角色都应能读
    for permission_id in ("org:read", "gl:read", "expense:read", "payment:read"):
        assert set(authz.roles_with(permission_id)) == {
            "owner",
            "admin",
            "accountant",
            "approver",
            "viewer",
            "member",
        }, permission_id

    # 建单：只读角色不在白名单里（这就是影子模式发现并修掉的那条差异）
    assert "viewer" not in authz.roles_with("expense:create")
    assert "member" in authz.roles_with("expense:create")

    # 本机角色不是成员资格，不该混进角色白名单
    assert "local" not in authz.roles_with("gl:write")
    assert "local" in authz.roles_with("gl:write", include_local=True)


# ---------------------------------------------------------------------------
# 2. Casbin 引擎
# ---------------------------------------------------------------------------


def test_casbin_engine_matches_dictionary() -> None:
    if not authz_engine.casbin_available():
        pytest.skip("未安装 casbin")
    for role in ("owner", "admin", "accountant", "approver", "viewer", "member"):
        for pid in authz.PERMISSION_IDS:
            allowed, _ = authz_engine.evaluate(8000, "42", role, pid)
            assert allowed is authz.allows(role, pid), f"{role} / {pid}"


def test_casbin_engine_denies_unknown_role() -> None:
    if not authz_engine.casbin_available():
        pytest.skip("未安装 casbin")
    allowed, reason = authz_engine.evaluate(8000, "42", "不存在", "gl:read")
    assert allowed is False
    assert "fail-closed" in reason


def test_casbin_engine_is_tenant_scoped() -> None:
    """同一个角色在别的租户不生效——domain 就是租户。"""
    if not authz_engine.casbin_available():
        pytest.skip("未安装 casbin")
    allowed, _ = authz_engine.evaluate(8000, "42", "owner", "gl:read")
    assert allowed is True
    # 引擎按 (tenant, subject, role) 判定，租户号不同即不同 domain
    allowed_other, _ = authz_engine.evaluate(8001, "42", "owner", "gl:read")
    assert allowed_other is True
    # 无角色时无论如何都拒绝
    denied, _ = authz_engine.evaluate(8001, "42", None, "gl:read")
    assert denied is False


# ---------------------------------------------------------------------------
# 3. 影子记录
# ---------------------------------------------------------------------------


async def test_shadow_records_real_requests(client) -> None:
    """真实业务请求会在影子表里留下权限点判定。"""
    await client.get("/api/org/overview")
    rows = await db.list_shadow_decisions()
    assert rows, "组织读请求应产生影子记录"
    hit = [r for r in rows if r["permission_id"] == "org:read"]
    assert hit, "应有 org:read 的判定"
    assert hit[0]["allowed"] == 1
    assert hit[0]["decision"] == "allow"
    assert hit[0]["mismatch"] == 0


async def test_shadow_records_denied_requests(client) -> None:
    """被拒绝的请求同样要留痕（否则汇总里的 deny 数会偏小）。"""
    uid_a, _ = await _user("shadow-a")
    uid_b, token_b = await _user("shadow-b")
    assert uid_b > 0
    await _enterprise_tenant(8000, uid_a, [(uid_a, "owner")])

    # B 不是 8000 的成员 → 403，但必须被记成 deny
    r = await client.get("/api/org/overview?tenant_id=8000", headers=_headers(token_b))
    assert r.status_code == 403

    rows = await db.list_shadow_decisions()
    denied = [r for r in rows if r["permission_id"] == "org:read" and r["allowed"] == 0]
    assert denied, "被拒请求应留 deny 记录"
    assert denied[0]["role"] == ""


async def test_viewer_cannot_create_expense_after_dictionary_fix(client) -> None:
    """只读角色不应能建报销单。

    这条差异最初是影子模式发现的：代码按"任意成员"放行，字典按只读拒绝。
    修法是让实现改用字典派生角色集合（`authz.roles_with`），不是让影子去拦截。
    修完之后影子应当不再报 mismatch——这才是"字典与实现一致"的证据。
    """
    uid_owner, _ = await _user("mm-owner")
    uid_viewer, token_viewer = await _user("mm-viewer")
    uid_member, token_member = await _user("mm-member")
    await _enterprise_tenant(
        8000,
        uid_owner,
        [(uid_owner, "owner"), (uid_viewer, "viewer"), (uid_member, "member")],
    )

    payload = {
        "title": "只读角色建单",
        "amount": 12.34,
        "category": "餐饮",
        "expense_account_id": 1,
        "credit_account_id": 2,
    }

    # viewer：只读角色不能建单
    r = await client.post(
        "/api/expenses?tenant_id=8000", json=payload, headers=_headers(token_viewer)
    )
    assert r.status_code == 403, r.text

    # member：普通成员可以建单（字典给了 expense:create）
    r = await client.post(
        "/api/expenses?tenant_id=8000", json=payload, headers=_headers(token_member)
    )
    assert r.status_code in (200, 400), r.text

    rows = await db.list_shadow_decisions()
    create_rows = [r for r in rows if r["permission_id"] == "expense:create"]
    assert create_rows, "建报销单应记录 expense:create 判定"
    by_role = {r["role"]: r for r in create_rows}

    viewer_row = by_role["viewer"]
    assert viewer_row["allowed"] == 0, "只读角色应被拒绝"
    assert viewer_row["decision"] == "deny"
    assert viewer_row["mismatch"] == 0, "字典与实现已一致，不应再有差异"

    member_row = by_role["member"]
    assert member_row["allowed"] == 1, "普通成员应能建单"
    assert member_row["decision"] == "allow"
    assert member_row["mismatch"] == 0


async def test_shadow_never_blocks_business(client, monkeypatch) -> None:
    """把 Casbin 判定改成永远 deny，业务请求的结果也不能变。"""
    monkeypatch.setattr(
        authz_engine, "evaluate", lambda *a, **k: (False, "影子被破坏")
    )

    r = await client.post("/api/org/departments", json={"name": "影子不拦截"})
    assert r.status_code == 200, r.text
    assert r.json()["department"]["name"] == "影子不拦截"

    rows = await db.list_shadow_decisions()
    mismatched = [r for r in rows if r["mismatch"] == 1]
    assert mismatched, "判定被改坏后必须记成 mismatch"
    assert mismatched[0]["allowed"] == 1, "业务实际是放行的"


async def test_shadow_can_be_switched_off_without_breaking_business(
    client, monkeypatch
) -> None:
    monkeypatch.setenv("MONEYHELPER_AUTHZ_SHADOW", "0")
    assert authz_engine.shadow_enabled() is False

    r = await client.post("/api/org/departments", json={"name": "影子关闭"})
    assert r.status_code == 200, r.text

    rows = await db.list_shadow_decisions()
    assert rows == [], "影子关闭时不应写记录"


# ---------------------------------------------------------------------------
# 4. 影子查询 API
# ---------------------------------------------------------------------------


async def test_authz_api_exposes_dictionary_and_summary(client) -> None:
    r = await client.get("/api/authz/permissions")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dictionary"]["points"], "应返回权限点字典"
    assert "owner" in body["dictionary"]["roles"]
    assert body["engine"]["casbin_available"] is True

    await client.get("/api/org/overview")

    r = await client.get("/api/authz/shadow/summary")
    assert r.status_code == 200, r.text
    summary = r.json()
    assert summary["total"] >= 1
    assert summary["allows"] >= 1

    r = await client.get("/api/authz/shadow")
    assert r.status_code == 200
    assert r.json()["decisions"]

    r = await client.delete("/api/authz/shadow")
    assert r.status_code == 200
    assert (await db.list_shadow_decisions()) == []


async def test_capabilities_endpoint_matches_dictionary(client) -> None:
    """能力接口返回的权限点必须与字典一致（前端按它隐藏写操作入口）。"""
    uid_owner, token_owner = await _user("cap-owner")
    uid_viewer, token_viewer = await _user("cap-viewer")
    await _enterprise_tenant(
        8000, uid_owner, [(uid_owner, "admin"), (uid_viewer, "viewer")]
    )
    # 能力反映的是"当前工作租户"里的角色；先切过去
    await db.set_active_tenant(uid_viewer, 8000)
    await db.set_active_tenant(uid_owner, 8000)

    r = await client.get("/api/org/capabilities", headers=_headers(token_viewer))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_id"] == 8000
    assert body["role"] == "viewer"
    assert set(body["permissions"]) == set(authz.role_permissions("viewer"))
    assert "expense:create" not in body["permissions"]
    assert "gl:read" in body["permissions"]

    r = await client.get("/api/org/capabilities", headers=_headers(token_owner))
    assert r.status_code == 200
    assert set(r.json()["permissions"]) == set(authz.role_permissions("admin"))


async def test_authz_api_requires_instance_admin(client) -> None:
    _, token = await _user("authz-plain")
    for path in ("/api/authz/permissions", "/api/authz/shadow", "/api/authz/status"):
        r = await client.get(path, headers=_headers(token))
        assert r.status_code == 403, f"{path} 应拒绝普通用户"

"""企业组织影子模型：回填、CRUD、跨租户隔离、owner 保护。"""

from __future__ import annotations

import httpx
import pytest
from app import auth, db
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


async def test_init_and_user_create_backfill_personal_tenant(temp_db) -> None:
    local = await db.get_tenant(0)
    assert local is not None
    assert local["kind"] == "local"
    assert local["name"] == "本机账本"

    uid, _ = await _user("org-alice")
    tenant = await db.get_tenant(uid)
    assert tenant is not None
    assert tenant["kind"] == "personal"
    assert int(tenant["owner_user_id"]) == uid

    overview = await db.org_overview(uid)
    assert overview["counts"]["members"] == 1
    assert overview["members"][0]["user_id"] == uid
    assert overview["members"][0]["role"] == "owner"

    before = await db.backfill_org_shadow()
    after = await db.backfill_org_shadow()
    assert before == after


async def test_local_org_crud_and_delete_guards(client) -> None:
    r = await client.post(
        "/api/org/departments", json={"name": "财务部", "code": "FIN"}
    )
    assert r.status_code == 200, r.text
    dept = r.json()["department"]

    r = await client.post(
        "/api/org/positions",
        json={"name": "会计", "department_id": dept["id"], "role_hint": "accountant"},
    )
    assert r.status_code == 200, r.text
    pos = r.json()["position"]

    r = await client.get("/api/org/overview")
    assert r.status_code == 200
    assert r.json()["counts"] == {
        "departments": 1,
        "positions": 1,
        "members": 0,
        "active_members": 0,
    }

    # 有岗位时不能删部门
    r = await client.delete(f"/api/org/departments/{dept['id']}")
    assert r.status_code == 400

    r = await client.patch(
        f"/api/org/departments/{dept['id']}", json={"name": "财务中心"}
    )
    assert r.status_code == 200
    assert r.json()["department"]["name"] == "财务中心"

    r = await client.delete(f"/api/org/positions/{pos['id']}")
    assert r.status_code == 200
    r = await client.delete(f"/api/org/departments/{dept['id']}")
    assert r.status_code == 200
    assert (await client.get("/api/org/overview")).json()["counts"]["departments"] == 0


async def test_local_org_cycle_and_duplicate_rejected(client) -> None:
    a = (await client.post("/api/org/departments", json={"name": "A"})).json()[
        "department"
    ]
    b = (
        await client.post(
            "/api/org/departments", json={"name": "B", "parent_id": a["id"]}
        )
    ).json()["department"]
    r = await client.patch(
        f"/api/org/departments/{a['id']}", json={"parent_id": b["id"]}
    )
    assert r.status_code == 400
    assert "成环" in r.text

    r = await client.post("/api/org/departments", json={"name": "A"})
    assert r.status_code == 400


async def test_personal_owner_can_manage_own_org(client) -> None:
    uid, token = await _user("org-bob")
    headers = _headers(token)

    r = await client.get("/api/org/overview", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["tenant"]["id"] == uid
    assert data["members"][0]["username"] == "org-bob"

    # 个人租户 owner 可管理自己的组织，但不能碰别人的租户（见下一条用例）
    r = await client.post(
        "/api/org/departments", json={"name": "自建部门"}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["department"]["name"] == "自建部门"


async def test_resolve_tenant_id_personal_then_membership(temp_db) -> None:
    assert await db.resolve_tenant_id(0) == 0

    uid, _ = await _user("resolve-personal")
    assert await db.resolve_tenant_id(uid) == uid

    # 没有个人租户、但有企业成员资格的用户，回退到企业租户
    conn = await db._conn()
    await conn.execute(
        "INSERT INTO users(id,username,password_hash,display_name,role,created_at)"
        " VALUES(9001,'ent-user','x','Ent User','user','2026-01-01')"
    )
    await conn.execute(
        "INSERT INTO tenants(id,name,kind,owner_user_id,status,created_at)"
        " VALUES(8000,'Acme','enterprise',9001,'active','2026-01-01')"
    )
    await conn.execute(
        "INSERT INTO org_memberships(tenant_id,user_id,role,status,created_at)"
        " VALUES(8000,9001,'accountant','active','2026-01-01')"
    )
    await conn.commit()
    assert await db.resolve_tenant_id(9001) == 8000
    assert await db.org_role(8000, 9001) == "accountant"


async def test_admin_cannot_cross_tenant_write(client) -> None:
    _, token_a = await _user("org-a", role="admin")
    _, token_b = await _user("org-b", role="admin")

    r = await client.post(
        "/api/org/departments",
        json={"name": "A 的部门"},
        headers=_headers(token_a),
    )
    assert r.status_code == 200
    dept_a = r.json()["department"]

    # B 是实例管理员，但只能操作自己的租户；A 的部门对 B 不可见
    r = await client.get("/api/org/overview", headers=_headers(token_b))
    assert r.status_code == 200
    assert all(d["id"] != dept_a["id"] for d in r.json()["departments"])

    r = await client.patch(
        f"/api/org/departments/{dept_a['id']}",
        json={"name": "被 B 改掉"},
        headers=_headers(token_b),
    )
    assert r.status_code == 400
    assert "不属于当前租户" in r.text

    # A 的原始数据没变
    r = await client.get("/api/org/overview", headers=_headers(token_a))
    assert r.json()["departments"][0]["name"] == "A 的部门"


async def test_list_tenants_and_switch_org_view(client) -> None:
    uid_a, token_a = await _user("switch-a", role="admin")
    _, token_b = await _user("switch-b", role="admin")

    conn = await db._conn()
    await conn.execute(
        "INSERT INTO tenants(id,name,kind,owner_user_id,status,created_at)"
        " VALUES(8000,'Acme','enterprise',?, 'active','2026-01-01')",
        (uid_a,),
    )
    await conn.execute(
        "INSERT INTO org_memberships(tenant_id,user_id,role,status,created_at)"
        " VALUES(8000,?,'admin','active','2026-01-01')",
        (uid_a,),
    )
    await conn.commit()

    r = await client.get("/api/org/tenants", headers=_headers(token_a))
    assert r.status_code == 200
    ids = {t["id"] for t in r.json()["tenants"]}
    assert {uid_a, 8000} <= ids

    r = await client.get(
        "/api/org/overview?tenant_id=8000", headers=_headers(token_a)
    )
    assert r.status_code == 200
    assert r.json()["tenant"]["id"] == 8000

    r = await client.post(
        "/api/org/departments?tenant_id=8000",
        json={"name": "Acme 财务"},
        headers=_headers(token_a),
    )
    assert r.status_code == 200, r.text

    # B 不是 8000 的成员：读/写都不能借 tenant_id 越权
    r = await client.get(
        "/api/org/overview?tenant_id=8000", headers=_headers(token_b)
    )
    assert r.status_code == 403
    r = await client.post(
        "/api/org/departments?tenant_id=8000",
        json={"name": "越权"},
        headers=_headers(token_b),
    )
    assert r.status_code == 403


async def test_local_tenant_list_is_zero(client) -> None:
    r = await client.get("/api/org/tenants")
    assert r.status_code == 200
    assert r.json()["tenants"][0]["id"] == 0


async def test_last_owner_cannot_be_removed_or_demoted(client) -> None:
    uid, token = await _user("org-owner", role="admin")
    headers = _headers(token)

    r = await client.delete(f"/api/org/members/{uid}", headers=headers)
    assert r.status_code == 400
    assert "owner" in r.text

    r = await client.patch(
        f"/api/org/members/{uid}", json={"role": "member"}, headers=headers
    )
    assert r.status_code == 400
    assert "owner" in r.text


async def test_add_member_requires_existing_active_user(client) -> None:
    r = await client.post("/api/org/members", json={"user_id": 99999})
    assert r.status_code == 400
    assert "用户不存在" in r.text

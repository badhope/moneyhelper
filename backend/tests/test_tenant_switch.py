"""全局租户切换（切片 7b）。

要锁死的三件事：
1. 显式选择优先于"个人租户优先"的旧映射——否则企业租户永远进不去；
2. 切换只作用于企业域，个人流水（记账/持仓/总览）仍按登录用户归属；
3. 选择失效（成员资格被撤、租户停用）必须自动回落，不能把人带进看不见的租户。
"""

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


async def _enterprise_tenant(
    tenant_id: int, owner_id: int, members: list[tuple[int, str]]
) -> None:
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
# 映射层
# ---------------------------------------------------------------------------


async def test_resolve_tenant_prefers_explicit_selection(temp_db) -> None:
    uid, _ = await _user("sw-owner")
    await _enterprise_tenant(8000, uid, [(uid, "admin")])

    # 没选过时：个人租户优先（旧的兼容映射）
    assert await db.resolve_tenant_id(uid) == uid

    # 选过企业租户之后：显式选择优先
    assert await db.set_active_tenant(uid, 8000) == 8000
    assert await db.get_active_tenant(uid) == 8000
    assert await db.resolve_tenant_id(uid) == 8000

    # 取消选择：回到默认
    assert await db.set_active_tenant(uid, 0) == 0
    assert await db.get_active_tenant(uid) is None
    assert await db.resolve_tenant_id(uid) == uid


async def test_set_active_tenant_rejects_non_member(temp_db) -> None:
    uid, _ = await _user("sw-outsider")
    owner, _ = await _user("sw-insider")
    await _enterprise_tenant(8000, owner, [(owner, "owner")])

    with pytest.raises(ValueError):
        await db.set_active_tenant(uid, 8000)
    assert await db.get_active_tenant(uid) is None


async def test_revoked_membership_invalidates_selection(temp_db) -> None:
    """成员资格被撤后，显式选择必须失效并回落，不能把人留在旧租户。"""
    uid, _ = await _user("sw-revoked")
    owner, _ = await _user("sw-owner2")
    await _enterprise_tenant(8000, owner, [(owner, "owner"), (uid, "member")])

    assert await db.set_active_tenant(uid, 8000) == 8000
    assert await db.resolve_tenant_id(uid) == 8000

    conn = await db._conn()
    await conn.execute(
        "UPDATE org_memberships SET status='archived' WHERE tenant_id=8000 AND user_id=?",
        (uid,),
    )
    await conn.commit()

    assert await db.get_active_tenant(uid) is None
    assert await db.resolve_tenant_id(uid) == uid


# ---------------------------------------------------------------------------
# API 层
# ---------------------------------------------------------------------------


async def test_switch_tenant_api(client) -> None:
    uid, token = await _user("sw-api")
    await _enterprise_tenant(8000, uid, [(uid, "admin")])

    r = await client.get("/api/org/tenants", headers=_headers(token))
    assert r.status_code == 200
    tenants = r.json()["tenants"]
    assert {t["id"] for t in tenants} == {uid, 8000}
    # 默认激活的是个人租户
    active = [t for t in tenants if t["active"]]
    assert len(active) == 1
    assert active[0]["id"] == uid

    r = await client.post(
        "/api/org/active-tenant", json={"tenant_id": 8000}, headers=_headers(token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["active_tenant_id"] == 8000

    r = await client.get("/api/org/active-tenant", headers=_headers(token))
    assert r.status_code == 200
    assert r.json()["active_tenant_id"] == 8000
    assert r.json()["explicit"] is True

    r = await client.get("/api/org/tenants", headers=_headers(token))
    tenants = r.json()["tenants"]
    active = [t for t in tenants if t["active"]]
    assert len(active) == 1
    assert active[0]["id"] == 8000


async def test_switch_to_tenant_without_membership_rejected(client) -> None:
    uid, token = await _user("sw-denied")
    assert uid > 0
    owner, _ = await _user("sw-owner3")
    await _enterprise_tenant(8000, owner, [(owner, "owner")])

    r = await client.post(
        "/api/org/active-tenant", json={"tenant_id": 8000}, headers=_headers(token)
    )
    assert r.status_code == 400
    assert "无权" in r.text


async def test_switch_affects_enterprise_domain_only(client) -> None:
    """切到企业租户后，企业域读的是企业租户；个人流水仍是自己的。"""
    uid, token = await _user("sw-scope")
    await _enterprise_tenant(8000, uid, [(uid, "admin")])

    # 个人租户下建一笔流水
    r = await client.post(
        "/api/transactions",
        json={"date": "2026-11-12", "item": "个人流水", "category": "餐饮", "amount": -10},
        headers=_headers(token),
    )
    assert r.status_code == 200, r.text

    r = await client.post(
        "/api/org/active-tenant", json={"tenant_id": 8000}, headers=_headers(token)
    )
    assert r.status_code == 200, r.text

    # 企业域：组织总览落在企业租户
    r = await client.get("/api/org/overview", headers=_headers(token))
    assert r.status_code == 200, r.text
    assert r.json()["tenant"]["id"] == 8000

    # 企业域：总账科目落在企业租户
    r = await client.post(
        "/api/gl/accounts",
        json={"code": "1001", "name": "库存现金", "type": "asset"},
        headers=_headers(token),
    )
    assert r.status_code == 200, r.text
    r = await client.get("/api/gl/accounts", headers=_headers(token))
    assert r.status_code == 200
    codes = {a["code"] for a in r.json()["accounts"]}
    assert "1001" in codes

    # 个人流水不受影响：仍属于登录用户自己的账本
    r = await client.get("/api/transactions", headers=_headers(token))
    assert r.status_code == 200
    items = {t["item"] for t in r.json()["transactions"]}
    assert "个人流水" in items


async def test_local_mode_has_no_tenant_to_switch(client) -> None:
    r = await client.get("/api/org/active-tenant")
    assert r.status_code == 200
    assert r.json()["active_tenant_id"] == 0

    r = await client.post("/api/org/active-tenant", json={"tenant_id": 8000})
    assert r.status_code == 403

"""Casbin 拦截模式（切片 7d）：默认关闭、开启后真正拦截、故障时降级。

三条底线：
- 默认关闭 → 行为与影子模式完全一致（不改变现有部署）；
- 开启且 Casbin 拒绝 → 403（真正拦截，不是再记一条）；
- Casbin 不可用 → 回落字典判定（不能因为引擎故障把系统锁死）。
"""

from __future__ import annotations

import pytest
from app import authz_engine, authz_guard


def test_enforce_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv("MONEYHELPER_AUTHZ_ENFORCE", raising=False)
    assert authz_engine.enforce_enabled() is False
    assert authz_engine.enforce_decision(0, "1", "admin", "gl:write") is None


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_enforce_on_values(monkeypatch, value: str) -> None:
    monkeypatch.setenv("MONEYHELPER_AUTHZ_ENFORCE", value)
    assert authz_engine.enforce_enabled() is True


async def test_enforce_allows_when_casbin_allows(monkeypatch) -> None:
    monkeypatch.setenv("MONEYHELPER_AUTHZ_ENFORCE", "1")
    out = await authz_guard.enforce(
        tenant_id=0, user={"id": 0}, role="local", permission_id="gl:write",
        allowed_by_code=True,
    )
    assert out is True


async def test_enforce_denies_when_role_lacks_permission(monkeypatch) -> None:
    """viewer 没有 gl:write：代码判定通过也必须被 Casbin 拦住。"""
    monkeypatch.setenv("MONEYHELPER_AUTHZ_ENFORCE", "1")
    out = await authz_guard.enforce(
        tenant_id=0, user={"id": 5}, role="viewer", permission_id="gl:write",
        allowed_by_code=True,
    )
    assert out is False


async def test_enforce_does_not_loosen_code_denial(monkeypatch) -> None:
    """Casbin 允许但代码拒绝时，仍以代码为准（不放宽）。"""
    monkeypatch.setenv("MONEYHELPER_AUTHZ_ENFORCE", "1")
    out = await authz_guard.enforce(
        tenant_id=0, user={"id": 5}, role="admin", permission_id="gl:write",
        allowed_by_code=False,
    )
    assert out is False


async def test_enforce_degrades_when_casbin_unavailable(monkeypatch) -> None:
    """casbin 不可用时必须回落字典判定，不能一律拒绝（否则引擎故障=全站 403）。"""
    monkeypatch.setenv("MONEYHELPER_AUTHZ_ENFORCE", "1")
    monkeypatch.setattr(authz_engine, "_casbin", None)
    assert authz_engine.enforce_decision(0, "5", "admin", "gl:write") is None
    out = await authz_guard.enforce(
        tenant_id=0, user={"id": 5}, role="admin", permission_id="gl:write",
        allowed_by_code=True,
    )
    assert out is True


async def test_enforce_denies_unknown_permission(monkeypatch) -> None:
    monkeypatch.setenv("MONEYHELPER_AUTHZ_ENFORCE", "1")
    out = await authz_guard.enforce(
        tenant_id=0, user={"id": 5}, role="admin", permission_id="nope:whatever",
        allowed_by_code=True,
    )
    assert out is False


async def test_enforce_mode_blocks_real_request(monkeypatch) -> None:
    """端到端：开启拦截后，viewer 调 GL 写接口必须 403（不是"记一条但放行"）。"""
    import httpx
    from app import auth, db
    from app.main import app

    # 建立账号 + 企业租户 + viewer 成员
    uid = await db.user_create("enf-viewer", "pw-123456", "enf-viewer", "user")
    user = await db.user_get(uid)
    token = auth._make_jwt(user)
    conn = await db._conn()
    # user_create 已建个人租户 owner 成员，这里把角色改成 viewer
    await conn.execute(
        "UPDATE org_memberships SET role='viewer' WHERE tenant_id=? AND user_id=?",
        (uid, uid),
    )
    await conn.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as c:
        headers = {"Authorization": f"Bearer {token}"}

        # 关闭拦截：字典判定已拒绝 viewer 写 GL → 403（与切片 7a 一致）
        monkeypatch.delenv("MONEYHELPER_AUTHZ_ENFORCE", raising=False)
        r = await c.post(
            "/api/gl/accounts?tenant_id=" + str(uid),
            json={"code": "1001", "name": "现金", "type": "asset"},
            headers=headers,
        )
        assert r.status_code == 403

        # 开启拦截：仍 403，且原因是字典/Casbin 拒绝
        monkeypatch.setenv("MONEYHELPER_AUTHZ_ENFORCE", "1")
        r2 = await c.post(
            "/api/gl/accounts?tenant_id=" + str(uid),
            json={"code": "1001", "name": "现金", "type": "asset"},
            headers=headers,
        )
        assert r2.status_code == 403


async def test_enforce_mode_allows_admin_request(monkeypatch) -> None:
    """开启拦截后，admin 的合法写操作不能被误伤。"""
    import httpx
    from app import auth, db
    from app.main import app

    uid = await db.user_create("enf-admin", "pw-123456", "enf-admin", "user")
    user = await db.user_get(uid)
    token = auth._make_jwt(user)
    conn = await db._conn()
    await conn.execute(
        "UPDATE org_memberships SET role='admin' WHERE tenant_id=? AND user_id=?",
        (uid, uid),
    )
    await conn.commit()

    monkeypatch.setenv("MONEYHELPER_AUTHZ_ENFORCE", "1")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as c:
        r = await c.post(
            "/api/gl/accounts?tenant_id=" + str(uid),
            json={"code": "1001", "name": "现金", "type": "asset"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text

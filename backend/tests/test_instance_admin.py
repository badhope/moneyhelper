"""实例级权限边界：账号停用、MCP 管理、审计清空、备份恢复。

这些用例锁的是"签名有效不等于有权"：
- 停用/删除账号的旧 JWT 必须在统一鉴权闸失效（不依赖路由是否写了 require_user）；
- MCP 配置/审计清空/备份恢复是实例级操作，普通租户不能做；
- 单机无账号模式仍可使用（本机所有者），但一旦有账号体系就必须登录。
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


async def _make_user(username: str, role: str = "user") -> tuple[int, str]:
    conn = await db._conn()
    await conn.execute(
        "INSERT INTO users(username, password_hash, display_name, role, created_at)"
        " VALUES(?,?,?,?,datetime('now'))",
        (username, "x", username, role),
    )
    await conn.commit()
    user = await db.user_get_by_username(username)
    assert user is not None
    return int(user["id"]), auth._make_jwt(user)


async def _disable(user_id: int) -> None:
    conn = await db._conn()
    await conn.execute("UPDATE users SET disabled=1 WHERE id=?", (user_id,))
    await conn.commit()


async def test_disabled_user_jwt_rejected_on_plain_route(client) -> None:
    """停用账号的旧令牌不能再读 /api/dashboard（该路由没有 require_user）。"""
    uid, token = await _make_user("disabled-user")
    await _disable(uid)

    r = await client.get("/api/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401, r.text
    assert "停用" in r.text or "登录" in r.text


async def test_all_users_disabled_still_requires_login(client) -> None:
    """全部账号停用后不能退回"无账号本机模式"。"""
    uid, _ = await _make_user("all-disabled")
    await _disable(uid)

    r = await client.get("/api/dashboard")
    assert r.status_code == 401, r.text


async def test_local_mode_allows_instance_admin(client) -> None:
    """空实例（无账号、无口令）仍是本机所有者模式。"""
    assert await db.user_count() == 0
    r = await client.get("/api/mcp/servers")
    assert r.status_code == 200, r.text


async def test_normal_user_cannot_manage_mcp_or_clear_audit(client) -> None:
    _, token = await _make_user("normal-user")
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.get("/api/mcp/servers", headers=headers)
    assert r.status_code == 403, r.text

    r = await client.put(
        "/api/mcp/servers",
        json={"servers": [{"name": "a", "url": "https://a.example/mcp"}]},
        headers=headers,
    )
    assert r.status_code == 403, r.text

    r = await client.post("/api/audit/clear", headers=headers)
    assert r.status_code == 403, r.text

    r = await client.post("/api/import/backup", json={}, headers=headers)
    assert r.status_code == 403, r.text


async def test_audit_clear_is_disabled_by_default(client) -> None:
    _, token = await _make_user("admin-no-clear", role="admin")
    r = await client.post(
        "/api/audit/clear", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403, r.text
    assert "默认不可清空" in r.text


async def test_admin_can_clear_audit_and_event_is_recorded(client, monkeypatch) -> None:
    monkeypatch.setenv("MONEYHELPER_ALLOW_AUDIT_CLEAR", "1")
    uid, token = await _make_user("admin-user", role="admin")
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.post("/api/audit/clear", headers=headers)
    assert r.status_code == 200, r.text

    # 清空本身也要留下审计记录，且 actor 是稳定用户身份而不是客户端 IP。
    conn = await db._conn()
    cur = await conn.execute(
        "SELECT actor, user_id FROM audit_logs WHERE path='/api/audit/clear'"
        " ORDER BY id DESC LIMIT 1"
    )
    row = await cur.fetchone()
    assert row is not None
    assert row["actor"] == f"user:{uid}"
    assert int(row["user_id"]) == uid


async def test_admin_can_read_mcp_servers(client) -> None:
    _, token = await _make_user("admin-mcp", role="admin")
    r = await client.get(
        "/api/mcp/servers", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200, r.text

"""HTTP 级多租户隔离：两个真实 JWT 用户通过 API 读写，数据必须互不可见。

与 test_tenant_isolation.py 的区别：那一组直接调数据层验证 SQL 过滤；
这一组走真实 HTTP 链路（中间件解析 JWT → 写入租户上下文 → 路由 → 数据层），
验证"登录用户看到的只有自己的数据"这一端到端承诺。
"""

from __future__ import annotations

from app import auth, db
from httpx import AsyncClient


async def _make_user(username: str) -> tuple[int, str]:
    """创建用户并返回 (user_id, jwt)。

    直接插入用户行而不走 user_create：本组测试只关心租户隔离，
    不验证口令哈希（passlib 与 bcrypt>=4 的版本噪声会干扰，另有用例覆盖）。
    """
    conn = await db._conn()
    await conn.execute(
        "INSERT INTO users(username, password_hash, display_name, role, created_at)"
        " VALUES(?,?,?,?,datetime('now'))",
        (username, "x", username, "user"),
    )
    await conn.commit()
    user = await db.user_get_by_username(username)
    assert user is not None
    token = auth._make_jwt(user)  # noqa: SLF001 — 测试直接签发，跳过登录限流
    return int(user["id"]), token


async def _add_position(c: AsyncClient, token: str, symbol: str, name: str, shares: int) -> None:
    r = await c.post(
        "/api/positions",
        json={"symbol": symbol, "name": name, "shares": shares, "cost": 10, "last": 12},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text


async def _positions(c: AsyncClient, token: str) -> list[dict]:
    """持仓列表走 /api/dashboard（没有独立的 GET /api/positions）。"""
    r = await c.get("/api/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json().get("positions") or []


async def test_two_users_see_only_their_positions(client: AsyncClient) -> None:
    _, token_a = await _make_user("alice")
    _, token_b = await _make_user("bob")

    # 同一代码两人都能持有（复合主键，不再互相覆盖）
    await _add_position(client, token_a, "600519", "茅台的A", 100)
    await _add_position(client, token_b, "600519", "茅台的B", 5)

    a = await _positions(client, token_a)
    b = await _positions(client, token_b)
    assert [(p["name"], p["shares"]) for p in a] == [("茅台的A", 100)]
    assert [(p["name"], p["shares"]) for p in b] == [("茅台的B", 5)]


async def test_user_cannot_see_other_transactions(client: AsyncClient) -> None:
    _, token_a = await _make_user("carol")
    _, token_b = await _make_user("dave")

    await client.post(
        "/api/transactions",
        json={"date": "2026-10-01", "item": "carol的午餐", "category": "餐饮", "amount": -30},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    await client.post(
        "/api/transactions",
        json={"date": "2026-10-02", "item": "dave的打车", "category": "交通", "amount": -50},
        headers={"Authorization": f"Bearer {token_b}"},
    )

    ra = await client.get("/api/transactions", headers={"Authorization": f"Bearer {token_a}"})
    rb = await client.get("/api/transactions", headers={"Authorization": f"Bearer {token_b}"})
    items_a = {t["item"] for t in (ra.json().get("transactions") or ra.json())}
    items_b = {t["item"] for t in (rb.json().get("transactions") or rb.json())}
    assert "carol的午餐" in items_a and "dave的打车" not in items_a
    assert "dave的打车" in items_b and "carol的午餐" not in items_b


async def test_goals_isolated(client: AsyncClient) -> None:
    _, token_a = await _make_user("erin")
    _, token_b = await _make_user("frank")

    await client.post(
        "/api/goals",
        json={"name": "买房", "target": 100000, "saved": 1000},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    def _names(payload) -> set[str]:
        rows = payload.get("goals") if isinstance(payload, dict) else payload
        return {str(g.get("name")) for g in (rows or []) if isinstance(g, dict)}

    ta = (await client.get("/api/goals", headers={"Authorization": f"Bearer {token_a}"})).json()
    tb = (await client.get("/api/goals", headers={"Authorization": f"Bearer {token_b}"})).json()
    names_a = _names(ta)
    names_b = _names(tb)
    assert "买房" in names_a
    assert "买房" not in names_b, "B 看到了 A 的目标"


async def test_no_token_rejected_once_users_exist(client: AsyncClient) -> None:
    """已启用账号体系的实例：无令牌一律 401（fail-closed）。

    回归：旧实现对「未设置 API_TOKEN」完全放行，未登录请求会落在默认租户 0，
    而默认租户里的历史数据可被任意匿名请求读写——注册了用户也绕不过去。
    """
    _, token_a = await _make_user("grace")
    await _add_position(client, token_a, "000001", "平安A", 7)

    anon = await client.get("/api/dashboard")
    assert anon.status_code == 401
    assert "登录" in anon.json().get("error", "")

    # 带合法 JWT 仍能正常读取自己的数据
    rows = await _positions(client, token_a)
    assert any(p.get("name") == "平安A" for p in rows)


async def test_no_token_allowed_when_no_users(client: AsyncClient) -> None:
    """零账号的本机单用户模式：保持免登录（否则首次使用无法进入）。"""
    anon = await client.get("/api/dashboard")
    assert anon.status_code == 200


# ---------------------------------------------------------------------------
# 管理员边界（方案 B：只读概览，无权看他人明细）
# ---------------------------------------------------------------------------


async def _make_admin(username: str) -> tuple[int, str]:
    conn = await db._conn()
    await conn.execute(
        "INSERT INTO users(username, password_hash, display_name, role, created_at)"
        " VALUES(?,?,?,?,datetime('now'))",
        (username, "x", username, "admin"),
    )
    await conn.commit()
    user = await db.user_get_by_username(username)
    return int(user["id"]), auth._make_jwt(user)  # noqa: SLF001


async def test_admin_cannot_read_other_tenant_detail(client: AsyncClient) -> None:
    """管理员看别人的持仓列表，只能看到自己的（租户隔离优先于角色）。"""
    _, token_user = await _make_user("normal_user")
    _, token_admin = await _make_admin("boss")

    await _add_position(client, token_user, "600519", "普通用户持仓", 10)

    admin_rows = await _positions(client, token_admin)
    assert not any(p.get("name") == "普通用户持仓" for p in admin_rows), (
        "管理员读到了其他租户的持仓明细"
    )


async def test_admin_overview_shows_counts_not_details(client: AsyncClient) -> None:
    """管理员概览只给条数，不给金额/名称。"""
    uid, token_user = await _make_user("member_a")
    _, token_admin = await _make_admin("boss2")
    await _add_position(client, token_user, "000001", "平安银行", 3)

    r = await client.get(
        "/api/auth/tenants-overview",
        headers={"Authorization": f"Bearer {token_admin}"},
    )
    assert r.status_code == 200
    tenants = {t["user_id"]: t for t in r.json()["tenants"]}
    assert uid in tenants
    assert tenants[uid]["counts"]["positions"] >= 1
    # 关键：概览里不能出现任何业务明细字段
    blob = r.text
    assert "平安银行" not in blob, "概览泄漏了持仓名称"
    assert "600519" not in blob


async def test_non_admin_gets_403_on_admin_endpoints(client: AsyncClient) -> None:
    _, token_user = await _make_user("plain_joe")
    for path in ("/api/auth/users", "/api/auth/tenants-overview"):
        r = await client.get(path, headers={"Authorization": f"Bearer {token_user}"})
        assert r.status_code == 403, f"{path} 未拒绝普通用户"


async def test_anonymous_gets_401_on_admin_endpoints(client: AsyncClient) -> None:
    for path in ("/api/auth/users", "/api/auth/tenants-overview"):
        r = await client.get(path)
        assert r.status_code == 401, f"{path} 未拒绝未登录请求"

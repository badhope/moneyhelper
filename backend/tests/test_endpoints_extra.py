"""两个新薄端点的测试：GET /api/subscriptions + GET /api/undoables + delete_memory_by_kind 辅助。

为什么要绕过 TestClient 的 lifespan：`with TestClient(app)` 会跑完整 lifespan，
其中包括 MCP 子应用的 task group 启停。全量运行时（前面已有几十个用例动过
asyncio 循环）该 task group 偶发在退出阶段抛 ExceptionGroup，
导致测试在 `__exit__` 里失败——断言其实已经通过了。

这两个用例只验证「路由返回什么」，与 MCP 生命周期无关，
因此直接用 httpx.ASGITransport（不触发 lifespan），既快又不受无关状态影响。
"""

from __future__ import annotations

import pytest
from app import db


@pytest.mark.anyio
async def test_list_subscriptions_endpoint_via_app(temp_db):
    import httpx

    from app import main

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as c:
        r = await c.get("/api/subscriptions")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "subscriptions" in data
        assert isinstance(data["subscriptions"], list)


@pytest.mark.anyio
async def test_undoables_endpoint_returns_snapshot_labels(temp_db):
    import httpx

    from app import main

    await db.add_transaction("2026-10-05", "测试流水", "测试", -10.0)
    await db.add_subscription({"name": "sub1", "monthly": 30.0, "due_day": "10"})

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as c:
        r = await c.get("/api/undoables?limit=5")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "items" in body
        # 至少订阅 add 会有一条快照
        ents = [it["entity"] for it in body["items"]]
        assert "subscription" in ents or "transaction" in ents


@pytest.mark.anyio
async def test_delete_memory_by_kind(temp_db):
    await db.add_memory("kind-A record 1", kind="kind-A")
    await db.add_memory("kind-A record 2", kind="kind-A")
    await db.add_memory("kind-B record", kind="kind-B")

    res = await db.delete_memory_by_kind("kind-A")
    assert res["ok"] is True
    assert res["deleted"] == 2

    leftover = await db.fetch_all("SELECT kind FROM user_memory")
    assert all(r["kind"] == "kind-B" for r in leftover)

    # kind 为空不删
    bad = await db.delete_memory_by_kind("")
    assert bad["ok"] is False

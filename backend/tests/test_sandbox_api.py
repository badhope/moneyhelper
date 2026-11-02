"""反事实沙盒 API 测试。"""

from __future__ import annotations

import httpx
import pytest
from app import db, main


@pytest.fixture(autouse=True)
async def _temp_db(temp_db):
    yield


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac


async def test_sandbox_base_shape(client) -> None:
    r = await client.get("/api/strategy/sandbox/base")
    assert r.status_code == 200
    body = r.json()
    for key in ("monthly_income", "monthly_expense", "cash", "essential_monthly", "dca_monthly"):
        assert key in body


async def test_sandbox_save_more(client) -> None:
    await db.add_transaction("2026-10-01", "工资", "收入", 20000)
    await db.add_transaction("2026-10-05", "房租", "居住", -5000)
    r = await client.get("/api/strategy/sandbox?kind=save_more&amount=2000")
    body = r.json()
    assert r.status_code == 200
    assert body["available"] is True
    assert body["after"]["monthly_net"] > body["before"]["monthly_net"]


async def test_sandbox_less_spend(client) -> None:
    await db.add_transaction("2026-10-01", "工资", "收入", 20000)
    await db.add_transaction("2026-10-06", "外卖", "餐饮", -2000)
    base = (await client.get("/api/strategy/sandbox/base?category=餐饮")).json()
    r = await client.get("/api/strategy/sandbox?kind=less_spend&percent=10&category=餐饮")
    body = r.json()
    assert body["available"] is True
    # 种子数据本身也有餐饮支出，断言按实际类目支出的 10% 计算
    assert body["detail"]["cut"] == round(base["target_category_expense"] * 0.1, 2)


async def test_sandbox_rejects_unknown_kind(client) -> None:
    r = await client.get("/api/strategy/sandbox?kind=nope")
    assert r.status_code == 400

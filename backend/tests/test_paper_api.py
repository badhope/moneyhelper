"""团队模拟盘 API 集成测试（v4.2）：开户 → 下单 → 排行 → 详情 → 删除 全链路。"""

from __future__ import annotations

import httpx
import pytest
from app import main


@pytest.fixture(autouse=True)
async def _temp_db(temp_db):
    yield


@pytest.fixture
async def client(_temp_db):
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac


async def test_paper_full_flow(client) -> None:
    # 开户
    r = await client.post("/api/paper/accounts", json={"name": "主力户", "initial_cash": 100000})
    assert r.status_code == 200
    aid = r.json()["account"]["account_id"]
    assert aid

    # 空列表排行
    r = await client.get("/api/paper/accounts")
    assert r.status_code == 200
    assert r.json()["summary"]["account_count"] == 1
    assert r.json()["items"][0]["return_pct"] == 0.0

    # 买入 200 股 @100（整手）
    r = await client.post(
        f"/api/paper/accounts/{aid}/trades",
        json={"symbol": "600519", "side": "buy", "price": 100.0, "shares": 200, "name": "贵州茅台"},
    )
    assert r.status_code == 200
    est = r.json()["estimate"]
    assert est["position_count"] == 1
    assert est["holdings"][0]["symbol"] == "600519"
    assert est["cash"] == pytest.approx(100000 - 20000 - 5.0, abs=0.01)

    # 非整手被拒
    r = await client.post(
        f"/api/paper/accounts/{aid}/trades",
        json={"symbol": "600519", "side": "buy", "price": 100.0, "shares": 150},
    )
    assert r.status_code == 400
    assert "整手" in r.json()["detail"]

    # 现金不足被拒
    r = await client.post(
        f"/api/paper/accounts/{aid}/trades",
        json={"symbol": "000001", "side": "buy", "price": 100.0, "shares": 1000},
    )
    assert r.status_code == 400
    assert "现金不足" in r.json()["detail"]

    # 卖出 100 股
    r = await client.post(
        f"/api/paper/accounts/{aid}/trades",
        json={"symbol": "600519", "side": "sell", "price": 120.0, "shares": 100},
    )
    assert r.status_code == 200
    est = r.json()["estimate"]
    assert est["holdings"][0]["shares"] == pytest.approx(100)
    assert est["equity"] > 100000  # 浮盈

    # 卖出超仓被拒
    r = await client.post(
        f"/api/paper/accounts/{aid}/trades",
        json={"symbol": "600519", "side": "sell", "price": 120.0, "shares": 500},
    )
    assert r.status_code == 400
    assert "持仓不足" in r.json()["detail"]

    # 详情：净值曲线 + 交易记录
    r = await client.get(f"/api/paper/accounts/{aid}")
    assert r.status_code == 200
    d = r.json()
    assert d["account"]["position_count"] == 1
    assert len(d["curve"]["dates"]) >= 1
    assert d["curve"]["equity"][-1] == pytest.approx(d["account"]["equity"] / 100000, abs=1e-4)
    assert len(d["trades"]) == 2

    # 手动快照幂等
    r = await client.post(f"/api/paper/accounts/{aid}/snapshot")
    assert r.status_code == 200
    assert r.json()["snapshotted"] is True

    # 排行有数据
    r = await client.get("/api/paper/accounts")
    assert r.status_code == 200
    items = r.json()["items"]
    assert items[0]["account_id"] == aid
    assert items[0]["return_pct"] > 0
    assert r.json()["summary"]["active_positions"] == 1

    # 删除
    r = await client.delete(f"/api/paper/accounts/{aid}")
    assert r.status_code == 200
    r = await client.get(f"/api/paper/accounts/{aid}")
    assert r.status_code == 404


async def test_paper_bad_inputs(client) -> None:
    r = await client.post("/api/paper/accounts", json={"name": "", "initial_cash": 100})
    assert r.status_code == 400  # 初始资金 < 1000

    # 非法代码
    r = await client.post("/api/paper/accounts", json={"name": "x", "initial_cash": 10000})
    aid = r.json()["account"]["account_id"]
    r = await client.post(
        f"/api/paper/accounts/{aid}/trades",
        json={"symbol": "abc", "side": "buy", "price": 1.0, "shares": 100},
    )
    assert r.status_code == 400

    # 不存在账户
    r = await client.post(
        "/api/paper/accounts/nope/trades",
        json={"symbol": "600519", "side": "buy", "price": 1.0, "shares": 100},
    )
    assert r.status_code == 404

"""策略 API 集成测试：真实 FastAPI + 临时库，行情用构造好的 K 线（无网络）。

覆盖点不是"返回 200"，而是：
- 无持仓 / 无行情时的降级契约（available=false + reason，不抛 500）
- 目标配置保存后能读回、租户隔离生效
- 定投计划 CRUD 与参数校验
- 风险端点确实返回了算出来的指标（含回测口径标注）
"""

from __future__ import annotations

import httpx
import pytest
from app import db, main
from app import quotes as quotes_mod


@pytest.fixture(autouse=True)
async def _temp_db(temp_db):
    yield


def _fake_kline(points: int = 260, start: float = 100.0, step: float = 0.3):
    """构造确定性日线：每日 +0.3%，用于验证指标链路而非网络。

    日期必须覆盖到今天：定投回测按"计划开始日 → 最后一个有价格的交易日"逐期买入，
    若构造的日期全在过去，计划开始后就一期都买不到（这是正确行为，但测不到主路径）。
    """
    from datetime import date, timedelta

    out = []
    px = start
    today = date.today()
    for i in range(points):
        d = (today - timedelta(days=points - 1 - i)).isoformat()
        out.append({"date": d, "close": px, "open": px, "high": px, "low": px, "volume": 1000})
        px *= 1 + step / 100
    return out


@pytest.fixture
async def client(monkeypatch):
    async def _kline(symbol, period="daily", limit=120):
        if symbol == "CASH":
            return None
        return {"symbol": symbol, "period": period, "points": _fake_kline(), "source": "test"}

    async def _idx(symbol, limit=750):
        return {"symbol": symbol, "name": "测试基准", "points": _fake_kline(), "source": "test"}

    async def _quote(symbol):
        return {"symbol": symbol, "price": 150.0, "change": 1.0, "change_pct": 0.7, "source": "test"}

    monkeypatch.setattr(quotes_mod, "kline", _kline)
    monkeypatch.setattr(quotes_mod, "index_kline", _idx)
    monkeypatch.setattr(quotes_mod, "quote_now", _quote)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac


async def test_risk_endpoint_returns_metrics(client):
    r = await client.get("/api/strategy/risk?days=300")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["basis"] == "backtest"
    assert "backtest" in body["basis_note"] or "回溯" in body["basis_note"]
    assert len(body["equity_curve"]) > 20
    m = body["metrics"]
    assert m["observations"] > 20
    assert m["total_return_pct"] is not None
    assert m["max_drawdown_pct"] is not None
    assert body["benchmark_name"] == "沪深300"


async def test_risk_endpoint_rejects_unknown_benchmark(client):
    r = await client.get("/api/strategy/risk?benchmark=xx999999")
    assert r.status_code == 400


async def test_risk_endpoint_degrades_without_holdings(client):
    await db.delete_position("600519")
    await db.delete_position("510300")
    await db.delete_position("110011")
    await db.delete_position("CASH")
    r = await client.get("/api/strategy/risk")
    assert r.status_code == 200
    assert r.json()["available"] is False
    assert r.json()["reason"]


async def test_risk_endpoint_degrades_when_kline_fails(client, monkeypatch):
    async def _none(symbol, period="daily", limit=120):
        return None

    monkeypatch.setattr(quotes_mod, "kline", _none)
    r = await client.get("/api/strategy/risk")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["diagnostics"]["resolved"] == 0


async def test_allocation_save_and_read(client):
    payload = {
        "targets": [
            {"symbol": "600519", "name": "贵州茅台", "target_pct": 30},
            {"symbol": "510300", "name": "沪深300ETF", "target_pct": 50},
            {"symbol": "CASH", "name": "现金", "target_pct": 20},
        ]
    }
    r = await client.put("/api/strategy/allocation", json=payload)
    assert r.status_code == 200
    assert r.json()["total_pct"] == pytest.approx(100)
    assert r.json()["warning"] is None

    r2 = await client.get("/api/strategy/allocation")
    body = r2.json()
    assert body["available"] is True
    assert len(body["targets"]) == 3
    plan = body["plan"]
    assert plan["total_value"] > 0
    # 茅台种子持仓 100 股 @ 1680 = 16.8 万，目标 30% → 明显超配，必须建议卖出
    assert any(i["symbol"] == "600519" and i["action"] == "sell" for i in plan["items"])


async def test_allocation_warns_when_sum_not_100(client):
    r = await client.put(
        "/api/strategy/allocation",
        json={"targets": [{"symbol": "600519", "name": "茅台", "target_pct": 25}]},
    )
    assert r.status_code == 200
    assert "建议调整为 100%" in (r.json()["warning"] or "")


async def test_allocation_rejects_bad_payload(client):
    r = await client.put("/api/strategy/allocation", json={"targets": "oops"})
    assert r.status_code == 400


async def test_allocation_ignores_invalid_rows(client):
    r = await client.put(
        "/api/strategy/allocation",
        json={
            "targets": [
                {"symbol": "", "target_pct": 10},
                {"symbol": "600519", "name": "茅台", "target_pct": 150},
                {"symbol": "510300", "name": "沪深300", "target_pct": 20},
            ]
        },
    )
    assert r.status_code == 200
    syms = [t["symbol"] for t in r.json()["targets"]]
    assert syms == ["510300"]


async def test_allocation_empty_when_no_targets(client):
    r = await client.get("/api/strategy/allocation")
    assert r.status_code == 200
    assert r.json()["available"] is False


async def test_valuation_endpoint(client):
    r = await client.get("/api/strategy/valuation")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert len(body["items"]) >= 3
    for item in body["items"]:
        assert 0 <= item["percentile"] <= 100
        assert item["zone"] in {"cheap", "low", "fair", "high", "expensive"}
        assert item["observations"] > 0


async def test_valuation_filters_symbols(client):
    r = await client.get("/api/strategy/valuation?symbols=600519")
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["symbol"] for i in items] == ["600519"]


async def test_dca_crud(client):
    r = await client.post(
        "/api/strategy/dca",
        json={
            "symbol": "510300",
            "name": "沪深300ETF",
            "amount": 3000,
            "frequency": "monthly",
            "day": 10,
            "start_date": "2026-01-01",
        },
    )
    assert r.status_code == 200
    plan = r.json()["plan"]
    plan_id = plan["id"]
    assert plan["amount"] == pytest.approx(3000)

    lst = await client.get("/api/strategy/dca")
    assert lst.status_code == 200
    items = lst.json()["items"]
    assert any(i["id"] == plan_id for i in items)
    row = next(i for i in items if i["id"] == plan_id)
    assert row["stats"]["periods"] > 0
    assert row["next_run"] is not None

    d = await client.delete(f"/api/strategy/dca/{plan_id}")
    assert d.status_code == 200
    lst2 = await client.get("/api/strategy/dca")
    assert all(i["id"] != plan_id for i in lst2.json()["items"])


async def test_dca_rejects_bad_amount(client):
    r = await client.post("/api/strategy/dca", json={"symbol": "510300", "amount": 0})
    assert r.status_code == 400
    r2 = await client.post("/api/strategy/dca", json={"symbol": "", "amount": 100})
    assert r2.status_code == 400


async def test_dca_delete_missing(client):
    r = await client.delete("/api/strategy/dca/nope")
    assert r.status_code == 404


async def test_dca_empty_list(client):
    r = await client.get("/api/strategy/dca")
    assert r.status_code == 200
    assert r.json()["available"] is False
    assert r.json()["items"] == []


async def test_fire_endpoint(client):
    r = await client.get("/api/strategy/fire")
    assert r.status_code == 200
    body = r.json()
    assert body["target_principal"] >= 0
    assert body["withdrawal_rate_pct"] == pytest.approx(4.0)
    assert "progress_pct" in body


async def test_fire_custom_params(client):
    r = await client.get("/api/strategy/fire?withdrawal_rate=3&expected_return=6")
    assert r.status_code == 200
    body = r.json()
    assert body["withdrawal_rate_pct"] == pytest.approx(3.0)
    assert body["expected_return_pct"] == pytest.approx(6.0)


async def test_fire_rejects_out_of_range(client):
    assert (await client.get("/api/strategy/fire?withdrawal_rate=99")).status_code == 422
    assert (await client.get("/api/strategy/fire?expected_return=-99")).status_code == 422


async def test_allocation_targets_are_tenant_scoped(client):
    """保存目标后切到另一租户，不应看到上一条。"""
    await client.put(
        "/api/strategy/allocation",
        json={"targets": [{"symbol": "600519", "name": "茅台", "target_pct": 100}]},
    )
    from app.db import tenant

    token = tenant.set_current_user_id(999)
    try:
        rows = await db.list_allocation_targets()
        assert rows == []
    finally:
        tenant.reset_current_user_id(token)

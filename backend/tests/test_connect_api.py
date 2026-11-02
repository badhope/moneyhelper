"""连接中心 HTTP 集成测试：真实 FastAPI + 临时库，外部行情全部 mock。

覆盖契约：
- 目录端点返回分组与统计，连接器条目带 connections
- 建连接 → 同步（公开源）→ 任务记录可查
- 书签回传走免登录通道（配对码），入账成功且码只能用一次
- 交易意图：paper 成交、live 只出交接单
- 收件箱扫描端点
"""

from __future__ import annotations

import httpx
import pytest
from app import main
from app.connect import marketdata


@pytest.fixture(autouse=True)
async def _temp_db(temp_db):
    yield


@pytest.fixture
async def client(monkeypatch):
    async def _fund(codes):
        return {
            "items": [
                {
                    "code": "110011",
                    "name": "易方达",
                    "nav": 3.91,
                    "acc_nav": 5.70,
                    "change_pct": -0.52,
                    "date": "2026-10-28",
                    "source": "test",
                }
            ],
            "missing": [],
            "source": "test",
            "fetched_at": "2026-10-28T15:00:00+08:00",
            "note": "",
        }

    async def _movers(kind="gainers", limit=20):
        return {
            "items": [
                {
                    "symbol": "600519",
                    "name": "贵州茅台",
                    "price": 1500.0,
                    "change_pct": 1.2,
                    "amount": 1e8,
                    "turnover_pct": 0.5,
                }
            ],
            "kind": kind,
            "source": "test",
            "fetched_at": "2026-10-28T15:00:00+08:00",
            "note": "",
        }

    async def _indices():
        return {
            "items": [
                {"symbol": "sh000001", "name": "上证指数", "price": 3681.47, "change": 33.17, "change_pct": 0.91}
            ],
            "source": "test",
            "fetched_at": "2026-10-28T15:00:00+08:00",
            "note": "",
        }

    async def _status():
        return {"items": [{"id": "eastmoney_quote", "ok": True, "detail": "test"}], "checked_at": "2026-10-28T15:00:00+08:00"}

    monkeypatch.setattr(marketdata, "fund_nav", _fund)
    monkeypatch.setattr(marketdata, "market_movers", _movers)
    monkeypatch.setattr(marketdata, "index_snapshot", _indices)
    monkeypatch.setattr(marketdata, "source_status", _status)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac


async def test_catalog_groups_and_counts(client) -> None:
    r = await client.get("/api/connect/catalog")
    assert r.status_code == 200
    body = r.json()
    assert body["counts"]["total"] >= 20
    assert any(g["key"] == "broker" for g in body["groups"])
    pay = next(g for g in body["groups"] if g["key"] == "pay")
    alipay = next(i for i in pay["items"] if i["id"] == "alipay")
    assert alipay["kind"] == "browser_login"
    assert alipay["connections"] == []


async def test_sources_status_and_live_data(client) -> None:
    st = await client.get("/api/connect/sources/status")
    assert st.status_code == 200 and st.json()["items"]
    idx = await client.get("/api/connect/indices")
    assert idx.json()["items"][0]["symbol"] == "sh000001"
    mv = await client.get("/api/connect/movers?kind=gainers")
    assert mv.json()["items"][0]["symbol"] == "600519"
    nav = await client.get("/api/connect/fund/nav?codes=110011")
    assert nav.json()["items"][0]["code"] == "110011"


async def test_connection_lifecycle_and_sync(client) -> None:
    created = await client.post("/api/connect/connections", json={"connector_id": "eastmoney_fund", "label": "我的基金"})
    assert created.status_code == 200
    cid = created.json()["id"]

    sync = await client.post(f"/api/connect/connections/{cid}/sync", json={"lang": "zh"})
    assert sync.status_code == 200
    body = sync.json()
    assert body["status"] == "done"
    assert body["result"]["fund_nav"]["items"][0]["code"] == "110011"

    jobs = await client.get("/api/connect/jobs")
    assert jobs.status_code == 200 and any(j["id"] == body["id"] for j in jobs.json()["items"])

    deleted = await client.delete(f"/api/connect/connections/{cid}")
    assert deleted.status_code == 200


async def test_unknown_connector_returns_400(client) -> None:
    r = await client.post("/api/connect/connections", json={"connector_id": "nope"})
    assert r.status_code == 400


async def test_bookmarklet_endpoint(client) -> None:
    r = await client.get("/api/connect/pairing/alipay/bookmarklet?lang=zh")
    assert r.status_code == 200
    body = r.json()
    assert body["pairing"]["connector_id"] == "alipay"
    assert "/api/connect/ingest" in body["bookmarklet"]


async def test_ingest_is_single_use(client) -> None:
    issued = await client.get("/api/connect/pairing/alipay/bookmarklet")
    code = issued.json()["pairing"]["code"]

    payload = {
        "code": code,
        "connector_id": "alipay",
        "title": "我的账单",
        "text": "2026-10-01 星巴克咖啡 -35.50\n2026-10-02 工资 +12000.00",
    }
    first = await client.post("/api/connect/ingest", json=payload)
    assert first.status_code == 200
    assert first.json()["imported"] == 2

    second = await client.post("/api/connect/ingest", json=payload)
    assert second.status_code == 403

    txs = await client.get("/api/transactions")
    items = txs.json()["transactions"] if isinstance(txs.json(), dict) else txs.json()
    assert any(t["item"] == "星巴克咖啡" for t in items)


async def test_paper_intent_api(client) -> None:
    # 自动开户的模拟盘默认 10 万，按 100 股整手下一笔 5 万的单，确保资金充足
    created = await client.post(
        "/api/connect/intents",
        json={"symbol": "000001", "name": "平安银行", "side": "buy", "price": 500, "shares": 100, "mode": "paper"},
    )
    assert created.status_code == 200
    iid = created.json()["id"]

    # 用接口自带的模拟盘账户（不存在时自动开一个）
    ex = await client.post(f"/api/connect/intents/{iid}/execute", json={})
    assert ex.status_code == 200
    body = ex.json()
    assert body["ok"] is True
    assert body["intent"]["status"] == "executed"
    assert body["fee"] == 12.5  # 50000 * 0.025%


async def test_live_intent_api_handoff(client) -> None:
    await client.post("/api/connect/connections", json={"connector_id": "eastmoney_sec"})
    created = await client.post(
        "/api/connect/intents",
        json={
            "symbol": "600519",
            "side": "buy",
            "price": 1500,
            "shares": 100,
            "mode": "live",
            "connector_id": "eastmoney_sec",
        },
    )
    iid = created.json()["id"]
    ex = await client.post(f"/api/connect/intents/{iid}/execute", json={})
    body = ex.json()
    assert body["ok"] is True
    assert body["handoff"]["mode"] == "live"
    assert "handoff_url" in body["handoff"]


async def test_inbox_scan_api(client) -> None:
    from app.connect import service as connect_service

    root = connect_service.inbox_dir()
    sample = root / "wechat-test.csv"
    sample.write_text(
        "交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态\n"
        "2026-09-01 10:00:00,商户消费,便利店,饮料,支出,¥6.00,零钱,支付成功\n",
        encoding="utf-8",
    )
    try:
        r = await client.post("/api/connect/inbox/scan")
        assert r.status_code == 200
        assert r.json()["imported"] == 1
    finally:
        for p in (root / "done").glob("*wechat-test.csv"):
            p.unlink()

"""投研 / 财报 API 集成测试（v4.0）：走真实 FastAPI 应用，行情 K 线打桩，全程无网络。"""

from __future__ import annotations

import httpx
import pytest
from app import main
from app import quotes as quotes_mod

# 一组稳定的合成日线（100 根，缓慢上行 + 小幅波动），供技术分析与回测使用
_FAKE_KLINE = {
    "symbol": "600519",
    "period": "daily",
    "points": [
        {
            "date": f"2026-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}",
            "open": 1500.0 + i * 0.5,
            "close": 1500.0 + i * 0.5 + (i % 5) * 0.2,
            "high": 1500.0 + i * 0.5 + 5.0,
            "low": 1500.0 + i * 0.5 - 5.0,
            "volume": 3_000_000 + i * 1000,
            "pct_change": 0.2,
        }
        for i in range(100)
    ],
    "source": "eastmoney",
    "fetched_at": "2026-01-01T00:00:00+08:00",
}


@pytest.fixture(autouse=True)
async def _temp_db(temp_db):
    yield


@pytest.fixture
async def client(_temp_db, monkeypatch):
    async def _fake_kline(symbol, period="daily", limit=120):
        pts = _FAKE_KLINE["points"][-limit:]
        return {"symbol": symbol, "period": period, "points": pts, "source": "eastmoney"}

    monkeypatch.setattr(quotes_mod, "kline", _fake_kline)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac


_STATEMENT_PAYLOAD = {
    "company": "API 测试公司",
    "currency": "CNY",
    "periods": [
        {
            "period": "2024-12-31",
            "balance_sheet": {
                "total_assets": 2_000_000.0,
                "total_liabilities": 1_000_000.0,
                "total_equity": 1_000_000.0,
                "current_assets": 800_000.0,
                "current_liabilities": 500_000.0,
                "inventory": 200_000.0,
                "accounts_receivable": 150_000.0,
            },
            "income_statement": {
                "revenue": 1_000_000.0,
                "gross_profit": 400_000.0,
                "operating_profit": 150_000.0,
                "net_profit": 100_000.0,
                "ebit": 160_000.0,
                "interest_expense": 20_000.0,
            },
            "cashflow_statement": {"operating_cashflow": 80_000.0},
        }
    ],
}


async def test_research_analyze(client) -> None:
    r = await client.get("/api/research/analyze?symbol=600519")
    assert r.status_code == 200
    d = r.json()
    assert d["available"] is True
    assert d["technical"]["point_count"] == 100
    assert d["technical"]["last"]["close"] is not None
    assert isinstance(d["technical"]["signals"], list)
    assert "收盘" in d["trend_text"]


async def test_research_backtest_ma(client) -> None:
    r = await client.get("/api/research/backtest?symbol=600519&strategy=ma_cross")
    assert r.status_code == 200
    d = r.json()
    assert d["available"] is True
    assert d["result"]["strategy"] == "ma_cross"
    assert d["result"]["curve"]["strategy"]


async def test_research_backtest_dca(client) -> None:
    r = await client.get("/api/research/backtest?symbol=600519&strategy=dca&invest_amount=500&freq_days=5")
    assert r.status_code == 200
    d = r.json()
    assert d["available"] is True
    assert d["result"]["total_invested"] > 0


async def test_research_bad_symbol(client) -> None:
    r = await client.get("/api/research/analyze?symbol=abc")
    assert r.status_code == 400


async def test_research_forecast(client) -> None:
    r = await client.get("/api/research/forecast?symbol=600519&days=10")
    assert r.status_code == 200
    d = r.json()
    assert d["available"] is True
    f = d["forecast"]
    assert f["horizon"] == 10
    assert len(f["dates"]) == 100 + 10
    assert f["bias"] in ("up", "down", "neutral")
    # 区间带：未来段中值落在 p5 与 p95 之间（未来段从 index 100 开始）
    assert f["p5"][105] <= f["median"][105] <= f["p95"][105]
    assert "不构成投资建议" in d["text"]


async def test_statements_analyze(client) -> None:
    r = await client.post("/api/statements/analyze", json=_STATEMENT_PAYLOAD)
    assert r.status_code == 200
    d = r.json()
    assert d["company"] == "API 测试公司"
    assert d["period_count"] == 1
    assert d["latest"]["roe_pct"] == pytest.approx(10.0)
    assert "不构成投资建议" in d["report_text"]


async def test_statements_crud(client) -> None:
    # 保存 → 列表 → 详情 → 删除
    r = await client.post("/api/statements", json=_STATEMENT_PAYLOAD)
    assert r.status_code == 200
    sid = r.json()["id"]
    assert sid

    r = await client.get("/api/statements")
    assert r.status_code == 200
    assert r.json()["total"] == 1

    r = await client.get(f"/api/statements/{sid}")
    assert r.status_code == 200
    assert r.json()["company"] == "API 测试公司"

    r = await client.delete(f"/api/statements/{sid}")
    assert r.status_code == 200
    assert r.json()["deleted"] == sid

    r = await client.get(f"/api/statements/{sid}")
    assert r.status_code == 404


async def test_statements_invalid(client) -> None:
    r = await client.post("/api/statements/analyze", json={"periods": []})
    assert r.status_code == 400

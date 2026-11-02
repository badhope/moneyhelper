"""v4.5 深化 HTTP 集成测试：腾讯行情（mock）/ 市场温度（mock）/ 预交易风控 /
条件单 / 发票 / 持仓对账 / 财税计算 / 现金流。

外部行情一律 monkeypatch，测试不触网。
"""

from __future__ import annotations

import httpx
import pytest
from app import main
from app.connect import quote_tencent


@pytest.fixture(autouse=True)
async def _temp_db(temp_db):
    yield


def _fake_quote(symbol: str = "600519") -> dict:
    return {
        "symbol": symbol,
        "name": "贵州茅台",
        "price": 1347.33,
        "prev_close": 1330.75,
        "change": 16.58,
        "change_pct": 1.25,
        "pe_ttm": 20.68,
        "pb": 6.7,
        "total_mv_yi": 16842.72,
        "float_mv_yi": 16842.0,
        "turnover_pct": 0.11,
        "volume_ratio": 1.84,
        "amplitude_pct": 1.5,
        "limit_up": 1463.83,
        "limit_down": 1197.68,
        "amount": 92146.0,
        "source": "tencent",
    }


@pytest.fixture
async def client(monkeypatch):
    async def _quote(symbol: str):
        return _fake_quote(symbol)

    async def _batch(symbols):
        return {s: _fake_quote(s) for s in symbols}

    async def _profile(symbol: str):
        q = _fake_quote(symbol)
        q["valuation"] = {
            "pe_ttm": q["pe_ttm"],
            "pb": q["pb"],
            "total_mv_yi": q["total_mv_yi"],
            "float_mv_yi": q["float_mv_yi"],
            "pe_note": "",
        }
        q["activity"] = {
            "turnover_pct": q["turnover_pct"],
            "volume_ratio": q["volume_ratio"],
            "amplitude_pct": q["amplitude_pct"],
            "amount_wan": q["amount"],
        }
        return q

    async def _breadth():
        return {
            "available": True,
            "up": 1115,
            "down": 4128,
            "flat": 98,
            "total": 5341,
            "limit_up": 47,
            "limit_down": 52,
            "strong": 94,
            "up_ratio_pct": 20.9,
            "temperature": 24.9,
            "mood": "cold",
            "checked_at": "2026-10-29T10:00:00+08:00",
        }

    async def _minute(symbol: str):
        return {"symbol": symbol, "points": [{"time": "09:30", "price": 1349.99, "volume": 1, "amount": 1}], "source": "tencent"}

    async def _kline(symbol, period="daily", limit=120):
        return {"symbol": symbol, "period": period, "points": [{"date": "2026-10-28", "open": 1, "close": 1, "high": 1, "low": 1, "volume": 1}], "source": "tencent"}

    monkeypatch.setattr(quote_tencent, "quote", _quote)
    monkeypatch.setattr(quote_tencent, "quotes_batch", _batch)
    monkeypatch.setattr(quote_tencent, "profile", _profile)
    monkeypatch.setattr(quote_tencent, "market_breadth", _breadth)
    monkeypatch.setattr(quote_tencent, "minute", _minute)
    monkeypatch.setattr(quote_tencent, "kline", _kline)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac


# ---------------------------------------------------------------------------
# 行情深化
# ---------------------------------------------------------------------------


async def test_market_breadth_api(client) -> None:
    r = await client.get("/api/connect/market/breadth")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["mood"] == "cold"
    assert body["temperature"] < 30


async def test_stock_profile_api(client) -> None:
    r = await client.get("/api/connect/stock/600519/profile")
    assert r.status_code == 200
    body = r.json()
    assert body["pe_ttm"] == 20.68
    assert body["valuation"]["total_mv_yi"] == 16842.72
    assert body["limit_up"] == 1463.83


async def test_stock_minute_and_kline_api(client) -> None:
    m = await client.get("/api/connect/stock/600519/minute")
    assert m.status_code == 200 and m.json()["points"]
    k = await client.get("/api/connect/kline?symbol=600519")
    assert k.status_code == 200 and k.json()["source"] == "tencent"


# ---------------------------------------------------------------------------
# 预交易风控
# ---------------------------------------------------------------------------


async def test_risk_settings_defaults_and_update(client) -> None:
    r = await client.get("/api/connect/risk/settings")
    assert r.status_code == 200
    assert r.json()["daily_limit"] == 200000.0

    upd = await client.put("/api/connect/risk/settings", json={"daily_limit": 100000, "deviation_pct": 2})
    assert upd.status_code == 200
    assert upd.json()["daily_limit"] == 100000.0
    assert upd.json()["deviation_pct"] == 2.0

    bad = await client.put("/api/connect/risk/settings", json={"concentration_pct": 0})
    assert bad.status_code == 400


async def test_risk_check_blocks_non_lot(client) -> None:
    # 先设置现金持仓，保证有可用资金
    await client.post(
        "/api/positions",
        json={"symbol": "CASH", "name": "现金", "kind": "现金", "shares": 1, "cost": 500000, "last": 500000},
    )
    r = await client.post(
        "/api/connect/risk/check",
        json={"symbol": "600519", "side": "buy", "price": 1347.33, "shares": 150},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert any(b["id"] == "lot" for b in body["blocking"])
    assert body["quote"]["name"] == "贵州茅台"


async def test_risk_check_passes_clean_order(client) -> None:
    await client.post(
        "/api/positions",
        json={"symbol": "CASH", "name": "现金", "kind": "现金", "shares": 1, "cost": 500000, "last": 500000},
    )
    r = await client.post(
        "/api/connect/risk/check",
        json={"symbol": "600519", "side": "buy", "price": 1347.33, "shares": 100},
    )
    body = r.json()
    assert body["ok"] is True
    assert body["blocking"] == []


async def test_rebalance_orders_api_with_items(client) -> None:
    r = await client.post(
        "/api/connect/rebalance/orders",
        json={
            "items": [
                {"symbol": "600519", "name": "茅台", "action": "buy", "amount": 200000, "price": 1347.33},
                {"symbol": "000001", "name": "平安", "action": "sell", "amount": 50000, "price": 11.44},
            ],
            "available_cash": 100000,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["sells"]) == 1
    assert body["buys"][0]["shares"] == 100  # 整手
    assert body["cash_after"] >= 0


# ---------------------------------------------------------------------------
# 条件单
# ---------------------------------------------------------------------------


async def test_conditional_order_lifecycle_api(client) -> None:
    created = await client.post(
        "/api/connect/conditionals",
        json={
            "symbol": "600519",
            "side": "buy",
            "trigger_type": "price_below",
            "trigger_value": 1300,
            "price": 1300,
            "shares": 100,
            "mode": "paper",
        },
    )
    assert created.status_code == 200
    cid = created.json()["id"]

    listed = await client.get("/api/connect/conditionals?status=watching")
    assert any(c["id"] == cid for c in listed.json()["items"])

    # 行情 1347 > 1300，跌破条件不成立
    ev = await client.post("/api/connect/conditionals/evaluate")
    assert ev.status_code == 200
    assert ev.json()["triggered"] == []

    # 改成跌破 1400 → 应触发并生成待确认意图
    await client.post(
        "/api/connect/conditionals",
        json={
            "symbol": "600519",
            "side": "buy",
            "trigger_type": "price_below",
            "trigger_value": 1400,
            "price": 1400,
            "shares": 100,
            "mode": "paper",
        },
    )
    ev2 = await client.post("/api/connect/conditionals/evaluate")
    body = ev2.json()
    assert len(body["triggered"]) == 1
    assert body["triggered"][0]["intent"]["status"] == "awaiting_confirm"

    deleted = await client.delete(f"/api/connect/conditionals/{cid}")
    assert deleted.status_code == 200


async def test_conditional_validation_api(client) -> None:
    r = await client.post("/api/connect/conditionals", json={"symbol": "abcd", "side": "buy"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 发票
# ---------------------------------------------------------------------------


async def test_invoice_text_api_and_dedup(client) -> None:
    text = "发票代码 011002100311\n发票号码 12345678\n开票日期 2026年10月15日\n价税合计 106.00\n"
    first = await client.post("/api/connect/invoices/text", json={"text": text})
    assert first.status_code == 200
    body = first.json()
    assert body["parsed"]["invoice_number"] == "12345678"
    assert body["duplicate"] is False

    second = await client.post("/api/connect/invoices/text", json={"text": text})
    assert second.json()["duplicate"] is True

    listed = await client.get("/api/connect/invoices")
    assert listed.json()["summary"]["count"] == 1
    assert listed.json()["summary"]["total_amount"] == 106.0


async def test_invoice_empty_rejected(client) -> None:
    r = await client.post("/api/connect/invoices/text", json={"text": "  "})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 持仓对账
# ---------------------------------------------------------------------------


HOLDINGS_CSV = """证券代码,证券名称,持仓数量,可用数量,成本价,现价,市值,浮动盈亏
600519,贵州茅台,100,100,1680.00,1347.33,134733.00,-33267.00
510300,沪深300ETF,8000,8000,3.85,4.06,32480.00,1680.00
"""


async def test_holdings_import_preview_only(client) -> None:
    r = await client.post("/api/connect/import/holdings", json={"content": HOLDINGS_CSV})
    body = r.json()
    assert body["count"] == 2
    assert body.get("applied") is None


async def test_holdings_import_apply_creates_positions(client) -> None:
    r = await client.post(
        "/api/connect/import/holdings",
        json={"content": HOLDINGS_CSV, "apply": True, "file_name": "h.csv"},
    )
    body = r.json()
    assert body["applied"] == 2

    dash = await client.get("/api/dashboard")
    symbols = {p["symbol"] for p in dash.json()["positions"]}
    assert {"600519", "510300"}.issubset(symbols)

    hist = await client.get("/api/connect/import/holdings/history")
    assert hist.json()["items"]
    # 同内容重复导入标记 duplicate
    again = await client.post(
        "/api/connect/import/holdings",
        json={"content": HOLDINGS_CSV, "apply": True, "file_name": "h.csv"},
    )
    assert again.json()["record"]["duplicate"] is True


# ---------------------------------------------------------------------------
# 财税计算
# ---------------------------------------------------------------------------


async def test_vat_api(client) -> None:
    r = await client.post("/api/finance/tax/vat", json={"sales": 1000, "purchases": 500, "rate": 0.13})
    body = r.json()
    assert body["vat_payable"] == 65.0
    assert body["total"] == 72.8


async def test_cit_api(client) -> None:
    r = await client.post(
        "/api/finance/tax/cit",
        json={"revenue": 2_000_000, "cost": 1_200_000, "expenses": 300_000, "category": "small_micro"},
    )
    assert r.json()["tax_payable"] == 25_000.0


async def test_iit_and_payroll_api(client) -> None:
    iit = await client.post(
        "/api/finance/tax/iit",
        json={"monthly_salary": 30000, "social_insurance": 4000, "housing_fund": 1000, "special_additional": 2000},
    )
    assert iit.json()["current_withholding"] == 540.0

    pr = await client.post(
        "/api/finance/tax/payroll",
        json={"gross_salary": 30000, "social_base": 30000, "housing_base": 30000, "special_additional": 2000},
    )
    body = pr.json()
    assert body["employee_total"] == 6750.0
    assert body["net_pay"] == pytest.approx(30000 - 6750 - body["income_tax"], abs=0.01)


async def test_tax_summary_api(client) -> None:
    r = await client.post("/api/finance/tax/summary", json={"revenue": 1_000_000, "cost": 400_000, "expenses": 200_000})
    body = r.json()
    assert body["vat"]["vat_payable"] == 78_000.0
    assert 0 < body["tax_burden_pct"] < 100


async def test_month_end_api(client) -> None:
    r = await client.get("/api/finance/month-end/2026-10?completed=bank_recon")
    body = r.json()
    assert body["done"] == 1
    assert body["total"] == 12
    bad = await client.get("/api/finance/month-end/2026-10-01")
    assert bad.status_code == 400


# ---------------------------------------------------------------------------
# 现金流 / 订阅 / 异常（走真实账本）
# ---------------------------------------------------------------------------


async def test_forecast_insufficient_data(client) -> None:
    r = await client.get("/api/finance/cashflow/forecast")
    body = r.json()
    # seed 账本只有本月流水，不足两个月 → 明确返回不可预测
    assert body["available"] is False
    assert "不足" in body["reason"]


async def test_subscription_and_anomaly_endpoints(client) -> None:
    subs = await client.get("/api/finance/subscriptions/detect")
    assert subs.status_code == 200
    assert "items" in subs.json()

    anom = await client.get("/api/finance/anomalies")
    assert anom.status_code == 200
    assert "items" in anom.json()

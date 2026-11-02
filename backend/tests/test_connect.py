"""连接中心测试：目录 / 连接 CRUD / 配对码 / 交易意图 / 收件箱 / 页面抽取。

外部行情一律 monkeypatch，测试不触网（与仓库既有约定一致）。
重点验证：
- 未知连接器被拒绝（防脏数据）
- 配对码一次性、会过期、跨租户不可用
- 交易意图在模拟盘按 A 股整手/费用口径成交，且状态流转正确
- 收件箱扫描能把支付宝 CSV 入账，并把文件归档
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from app import connect as hub
from app import db
from app.connect import marketdata, store
from app.connect import service as connect_service
from app.routes import connect as connect_routes


@pytest.fixture(autouse=True)
async def _temp_db(temp_db):
    yield


# ---------------------------------------------------------------------------
# 目录
# ---------------------------------------------------------------------------


def test_catalog_shape_and_categories() -> None:
    cat = hub.grouped_catalog()
    assert cat["counts"]["total"] == len(hub.CONNECTORS)
    assert cat["counts"]["auto"] > 0
    keys = [g["key"] for g in cat["groups"]]
    assert "market" in keys and "broker" in keys and "pay" in keys
    # 每个连接器都必须有明确的接入方式与自动化档位
    for c in hub.CONNECTORS:
        assert c["kind"] in hub.catalog.KINDS
        assert c["automation"] in hub.catalog.AUTOMATION
        assert c["capabilities"], c["id"]


def test_connector_lookup_returns_copy() -> None:
    hit = hub.get_connector("alipay")
    assert hit and hit["name"] == "支付宝"
    hit["name"] = "改坏"
    assert hub.get_connector("alipay")["name"] == "支付宝"
    assert hub.get_connector("nope") is None


# ---------------------------------------------------------------------------
# 连接 CRUD
# ---------------------------------------------------------------------------


async def test_create_connection_rejects_unknown_connector() -> None:
    with pytest.raises(ValueError):
        await store.create_connection("not_a_real_connector")


async def test_create_and_delete_connection() -> None:
    conn = await store.create_connection("alipay", "我的支付宝", "8888")
    assert conn["status"] == "unconfigured"
    assert conn["kind"] == "browser_login"
    listed = await store.list_connections()
    assert [c["id"] for c in listed] == [conn["id"]]

    # 同名重复被拒绝
    with pytest.raises(ValueError):
        await store.create_connection("alipay", "我的支付宝")

    assert await store.delete_connection(conn["id"]) is True
    assert await store.list_connections() == []


async def test_update_connection_status_validation() -> None:
    conn = await store.create_connection("cmb", "招行工资卡", "1234")
    updated = await store.update_connection(conn["id"], {"status": "connected", "last_error": ""})
    assert updated["status"] == "connected"
    with pytest.raises(ValueError):
        await store.update_connection(conn["id"], {"status": "whatever"})


# ---------------------------------------------------------------------------
# 配对码
# ---------------------------------------------------------------------------


async def test_pairing_code_is_single_use() -> None:
    issued = await store.issue_pairing_code("alipay")
    assert issued["ttl_minutes"] == 10
    redeemed = await store.redeem_pairing_code(issued["code"], "alipay")
    assert redeemed["connector_id"] == "alipay"
    with pytest.raises(ValueError, match="已被使用"):
        await store.redeem_pairing_code(issued["code"], "alipay")


async def test_pairing_code_connector_mismatch_and_expiry() -> None:
    issued = await store.issue_pairing_code("alipay")
    with pytest.raises(ValueError, match="不匹配"):
        await store.redeem_pairing_code(issued["code"], "cmb")

    expired = await store.issue_pairing_code("alipay")
    conn = await db._conn()
    past = (datetime.now().astimezone() - timedelta(minutes=1)).isoformat(timespec="seconds")
    await conn.execute(
        "UPDATE connect_pairings SET expires_at=? WHERE user_id=? AND code=?",
        (past, 0, expired["code"]),
    )
    await conn.commit()
    with pytest.raises(ValueError, match="过期"):
        await store.redeem_pairing_code(expired["code"], "alipay")


async def test_pairing_code_unknown() -> None:
    with pytest.raises(ValueError, match="不存在"):
        await store.redeem_pairing_code("NOSUCHCODE")


# ---------------------------------------------------------------------------
# 交易意图
# ---------------------------------------------------------------------------


async def test_create_intent_validation() -> None:
    with pytest.raises(ValueError):
        await store.create_intent({"symbol": "600519", "side": "hold", "price": 1, "shares": 1})
    with pytest.raises(ValueError):
        await store.create_intent({"symbol": "600519", "side": "buy", "price": 0, "shares": 1})
    with pytest.raises(ValueError):
        await store.create_intent({"symbol": "600519", "side": "buy", "price": 1, "shares": 1, "mode": "x"})
    # 不支持交易的连接器被拒绝
    with pytest.raises(ValueError, match="不支持交易"):
        await store.create_intent(
            {
                "symbol": "600519",
                "side": "buy",
                "price": 1,
                "shares": 100,
                "connector_id": "invoice_check",
            }
        )


async def test_paper_intent_executes_and_moves_cash() -> None:
    acc = await db.open_account("测试账户", 200000)
    intent = await store.create_intent(
        {
            "symbol": "600519",
            "name": "贵州茅台",
            "side": "buy",
            "price": 1500,
            "shares": 100,
            "mode": "paper",
        }
    )
    assert intent["status"] == "awaiting_confirm"
    res = await connect_service.execute_trade_intent(intent["id"], {"account_id": acc["account_id"]})
    assert res["ok"] is True
    assert res["fee"] == 37.5  # 150000 * 0.025%，高于最低 5 元
    est = res["estimate"]
    # 现金减少 = 成交额 + 手续费；equity 含持仓市值，按成交价估值所以只少手续费
    assert est["cash"] == pytest.approx(200000 - 150000 - 37.5, abs=0.01)
    assert est["equity"] == pytest.approx(200000 - 37.5, abs=0.01)
    # 状态只能执行一次
    with pytest.raises(ValueError, match="不可执行"):
        await connect_service.execute_trade_intent(intent["id"], {"account_id": acc["account_id"]})


async def test_paper_intent_rejects_oversell() -> None:
    acc = await db.open_account("测试账户2", 100000)
    intent = await store.create_intent(
        {"symbol": "000001", "side": "sell", "price": 10, "shares": 100, "mode": "paper"}
    )
    res = await connect_service.execute_trade_intent(intent["id"], {"account_id": acc["account_id"]})
    assert res["ok"] is False
    assert res["intent"]["status"] == "rejected"


async def test_live_intent_returns_handoff_without_trading() -> None:
    await store.create_connection("eastmoney_sec", "东财证券", "0001")
    intent = await store.create_intent(
        {
            "symbol": "600519",
            "side": "buy",
            "price": 1500,
            "shares": 100,
            "mode": "live",
            "connector_id": "eastmoney_sec",
        }
    )
    res = await connect_service.execute_trade_intent(intent["id"])
    assert res["ok"] is True
    assert res["handoff"]["mode"] == "live"
    assert "18.cn" in res["handoff"]["handoff_url"]
    # 实盘不下单：状态仍在待确认，等用户回填
    assert res["intent"]["status"] == "awaiting_confirm"


async def test_reject_intent() -> None:
    intent = await store.create_intent(
        {"symbol": "600519", "side": "buy", "price": 1500, "shares": 100, "mode": "paper"}
    )
    rejected = await store.update_intent(intent["id"], "rejected", note="用户取消")
    assert rejected["status"] == "rejected"
    with pytest.raises(ValueError):
        await store.update_intent(intent["id"], "bogus")


# ---------------------------------------------------------------------------
# 行情（全部 mock，不触网）
# ---------------------------------------------------------------------------


async def test_fund_nav_parses_and_reports_missing(monkeypatch) -> None:
    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "Datas": [
                    {"FCODE": "110011", "SHORTNAME": "易方达", "NAV": "3.91", "ACCNAV": "5.70", "NAVCHGRT": "-0.52", "PDATE": "2026-10-28"}
                ]
            }

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            return _Resp()

    monkeypatch.setattr(marketdata.httpx, "AsyncClient", lambda *a, **kw: _Client())
    marketdata._fund_nav_cache.clear()
    out = await marketdata.fund_nav(["110011", "999999"])
    assert out["items"][0]["nav"] == 3.91
    assert out["missing"] == ["999999"]


async def test_market_movers_falls_back_to_sina(monkeypatch) -> None:
    async def _east(*a, **kw):
        return []

    async def _sina(*a, **kw):
        return [{"symbol": "600519", "name": "贵州茅台", "price": 1500.0, "change_pct": 1.2, "amount": 1e8, "turnover_pct": 0.5}]

    monkeypatch.setattr(marketdata, "_movers_eastmoney", _east)
    monkeypatch.setattr(marketdata, "_movers_sina", _sina)
    marketdata._movers_cache.clear()
    out = await marketdata.market_movers("gainers", 5)
    assert out["source"] == "sina"
    assert out["items"][0]["symbol"] == "600519"


# ---------------------------------------------------------------------------
# 收件箱
# ---------------------------------------------------------------------------


ALIPAY_CSV = """支付宝交易记录明细查询
账号:[test@example.com]
起始日期:[2026-09-01 00:00:00]    终止日期:[2026-09-30 23:59:59]
---------------------------------交易记录明细列表------------------------------------
交易时间,交易分类,交易对方,对方账号,商品说明,收/支,金额,收/付款方式,交易状态,交易订单号,商家订单号,备注
2026-09-03 12:00:00,餐饮美食,某餐厅,,午餐,支出,35.00,余额宝,交易成功,202609031200,,
2026-09-05 09:00:00,转账红包,某公司,,工资,收入,12000.00,银行卡,交易成功,202609050900,,
"""


async def test_import_text_dedupes_against_existing() -> None:
    first = await connect_service.import_text(ALIPAY_CSV, source="alipay", filename="a.csv")
    assert first["imported"] == 2
    second = await connect_service.import_text(ALIPAY_CSV, source="alipay", filename="a.csv")
    assert second["imported"] == 0
    assert second["duplicated"] == 2


async def test_scan_inbox_imports_and_archives() -> None:
    root = connect_service.inbox_dir()
    sample = root / "alipay-2026-09.csv"
    sample.write_text(ALIPAY_CSV, encoding="utf-8")
    try:
        out = await connect_service.scan_import_inbox()
        assert out["imported"] == 2
        assert not sample.exists()
        assert (root / "done").exists()
        assert any(n.endswith("alipay-2026-09.csv") for n in [p.name for p in (root / "done").iterdir()])
    finally:
        for p in (root / "done").glob("*alipay-2026-09.csv"):
            p.unlink()


async def test_scan_inbox_empty() -> None:
    out = await connect_service.scan_import_inbox()
    assert out["ok"] is True
    assert out["imported"] == 0


# ---------------------------------------------------------------------------
# 页面文本抽取
# ---------------------------------------------------------------------------


def test_extract_rows_from_page_text() -> None:
    text = """我的账单
2026-10-01 星巴克咖啡 -35.50
2026-10-02 工资 +12000.00
这个月一共花了 35.5 元
"""
    rows = connect_routes._extract_rows(text)
    assert len(rows) == 2
    assert rows[0]["amount"] == -35.5
    assert rows[1]["amount"] == 12000.0
    assert rows[0]["date"] == "2026-10-01"


def test_extract_rows_empty() -> None:
    assert connect_routes._extract_rows("没有日期的普通文本\n只有一行") == []


# ---------------------------------------------------------------------------
# 书签脚本
# ---------------------------------------------------------------------------


def test_bookmarklet_contains_endpoint_and_code_but_no_secret() -> None:
    script = connect_service.build_bookmarklet("http://127.0.0.1:8788", "ABC123", "alipay")
    assert "javascript:" in script
    assert "/api/connect/ingest" in script
    assert "ABC123" in script
    # 绝不包含 cookie / localStorage 读取
    assert "cookie" not in script.lower()
    assert "localStorage" not in script

"""行情层单测：secid 映射与价格解析（纯函数），以及快照模式路径。"""

from __future__ import annotations

import pytest
from app import quotes


@pytest.fixture(autouse=True)
async def _clean_quotes_cache():
    """每个用例后清空行情缓存：quotes 缓存 TTL 30s，跨用例共享会让
    后跑用例命中先跑用例写入的价（600519 等热门代码），造成断言互扰。"""
    yield
    await quotes.invalidate_quotes_cache()


@pytest.mark.parametrize(
    ("symbol", "secid"),
    [
        ("600519", "1.600519"),
        ("688981", "1.688981"),
        ("000001", "0.000001"),
        ("300750", "0.300750"),
        ("510300", "1.510300"),
        ("159915", "0.159915"),
        ("161725", "0.161725"),
    ],
)
def test_to_secid_mapped(symbol: str, secid: str) -> None:
    assert quotes._to_secid(symbol) == secid


@pytest.mark.parametrize("symbol", ["CASH", "XXXX", "", "12345"])
def test_to_secid_unmappable(symbol: str) -> None:
    assert quotes._to_secid(symbol) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (1253.8, 1253.8),
        (15, 15.0),
        ("46.13", 46.13),
        (None, None),
        ("-", None),
        ("", None),
        (True, None),
        (0, None),
    ],
)
def test_parse_price(raw, expected) -> None:
    assert quotes._parse_price(raw) == expected


async def test_live_quotes_snapshot_mode(monkeypatch) -> None:
    """snapshot 模式不走网络，直接用库内 last，且来源标注为快照。"""
    async def _settings():
        return {"quote_source_mode": "snapshot"}
    monkeypatch.setattr(quotes.db, "get_settings", _settings)
    positions = [
        {"symbol": "600519", "kind": "股票", "last": 1521.0},
        {"symbol": "CASH", "kind": "现金", "last": 55000.0},
    ]
    out = await quotes.live_quotes(positions)
    assert out == {"600519": 1521.0, "CASH": 55000.0}
    assert quotes.last_source() == "snapshot"


async def test_live_quotes_falls_back_to_snapshot(monkeypatch) -> None:
    """auto 模式东财与新浪都失败 → 降级快照价，且来源标注为快照。"""
    async def _settings():
        return {"quote_source_mode": "auto"}
    monkeypatch.setattr(quotes.db, "get_settings", _settings)
    async def _fail(_symbols):
        return {}
    monkeypatch.setattr(quotes, "_eastmoney_quotes", _fail)
    monkeypatch.setattr(quotes, "_sina_quotes", _fail)
    positions = [
        {"symbol": "600519", "kind": "股票", "last": 1521.0},
        {"symbol": "CASH", "kind": "现金", "last": 55000.0},
    ]
    out = await quotes.live_quotes(positions)
    assert out == {"600519": 1521.0, "CASH": 55000.0}
    assert quotes.last_source() == "snapshot"


async def test_live_quotes_falls_back_to_sina(monkeypatch) -> None:
    """auto 模式东财失败、新浪成功 → 用新浪实时价，来源标注为 sina。"""
    async def _settings():
        return {"quote_source_mode": "auto"}
    monkeypatch.setattr(quotes.db, "get_settings", _settings)
    async def _fail(_symbols):
        return {}
    async def _sina_ok(_symbols):
        return {"000858": 1530.0}
    monkeypatch.setattr(quotes, "_eastmoney_quotes", _fail)
    monkeypatch.setattr(quotes, "_sina_quotes", _sina_ok)
    positions = [
        {"symbol": "000858", "kind": "股票", "last": 1521.0},
        {"symbol": "CASH", "kind": "现金", "last": 55000.0},
    ]
    out = await quotes.live_quotes(positions)
    assert out["000858"] == 1530.0
    assert quotes.last_source() == "sina"


async def test_live_quotes_eastmoney_marks_source(monkeypatch) -> None:
    """auto 模式东财成功 → 使用实时价，来源标注为 eastmoney。"""
    async def _settings():
        return {"quote_source_mode": "auto"}
    monkeypatch.setattr(quotes.db, "get_settings", _settings)
    async def _ok(_symbols):
        return {"000001": 11.5}
    monkeypatch.setattr(quotes, "_eastmoney_quotes", _ok)
    positions = [
        {"symbol": "000001", "kind": "股票", "last": 11.0},
        {"symbol": "CASH", "kind": "现金", "last": 55000.0},
    ]
    out = await quotes.live_quotes(positions)
    assert out["000001"] == 11.5
    assert quotes.last_source() == "eastmoney"


async def test_quote_now_sina_zero_price_falls_back_to_prev(monkeypatch) -> None:
    """盘前/非交易时段新浪现价为 0.000（被 _parse_price 判无效）→
    用昨收兜底显示（涨跌 0），避免「无法获取行情」假失败。"""
    raw = 'var hq_str_sh600519="贵州茅台,0.000,1235.580,0.000,0.000,0.000,0.000,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,0,0.000,2026-09-30,09:07:26,00,"'

    class _FakeResp:
        status_code = 200
        content = raw.encode("gbk")

        def raise_for_status(self) -> None:
            return None

    class _FakeClient:
        def __init__(self, *_a, **_k) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a) -> None:
            return None

        async def get(self, _url, headers=None):
            return _FakeResp()

    monkeypatch.setattr(quotes, "_to_secid", lambda _s: None)  # 跳过东财分支
    monkeypatch.setattr(quotes, "_to_sina", lambda _s: "sh600519")
    monkeypatch.setattr(quotes.httpx, "AsyncClient", _FakeClient)

    out = await quotes.quote_now("600519")
    assert out is not None
    assert out["price"] == 1235.58
    assert out["change"] == 0.0
    assert out["change_pct"] == 0.0
    assert out["source"] == "sina"


# ---------------------------------------------------------------------------
# K 线（东财 push2his）：日/周/月，前复权，失败降级为 None
# ---------------------------------------------------------------------------


def test_kline_period_to_klt() -> None:
    assert quotes.KLT["daily"] == 101
    assert quotes.KLT["weekly"] == 102
    assert quotes.KLT["monthly"] == 103


def test_parse_kline_rows() -> None:
    """kline 字符串数组 → 结构化点；坏行跳过而不是整体失败。"""
    raw = [
        "2026-09-24,1520.00,1530.00,1535.00,1515.00,12345,1.23,0.66,1.32,10.00,0.05",
        "2026-09-25,1530.00,1545.12,1548.00,1528.00,23456,1.50,0.99,1.88,20.12,0.08",
        "坏行",
    ]
    pts = quotes._parse_kline_rows(raw)
    assert len(pts) == 2
    assert pts[0]["date"] == "2026-09-24"
    assert pts[0]["close"] == 1530.00
    assert pts[0]["high"] == 1535.00
    assert pts[0]["pct_change"] == 1.32
    assert pts[1]["close"] == 1545.12


async def test_kline_degrades_on_error(monkeypatch) -> None:
    """网络/解析失败 → 返回 None（调用方据此跳过图表），绝不抛错。"""
    async def _boom(_sid, _klt, _limit):
        raise RuntimeError("network down")
    monkeypatch.setattr(quotes, "_fetch_kline", _boom)
    assert await quotes.kline("600519") is None


async def test_kline_unmappable_symbol_returns_none(monkeypatch) -> None:
    """现金/场外基金没有 K 线 → None，不发请求。"""
    async def _never(*_a, **_k):
        raise AssertionError("不该发请求")
    monkeypatch.setattr(quotes, "_fetch_kline", _never)
    assert await quotes.kline("CASH") is None


async def test_kline_returns_points_and_caches(monkeypatch) -> None:
    calls = {"n": 0}

    async def _ok(_sid, _klt, _limit):
        calls["n"] += 1
        return ["2026-09-25,1530.00,1545.12,1548.00,1528.00,23456,1.50,0.99,1.88,20.12,0.08"]

    monkeypatch.setattr(quotes, "_fetch_kline", _ok)
    await quotes.invalidate_quotes_cache()
    a = await quotes.kline("600519", "daily", limit=5)
    await quotes.kline("600519", "daily", limit=5)
    assert a is not None and a["symbol"] == "600519"
    assert a["period"] == "daily"
    assert a["points"][0]["close"] == 1545.12
    assert calls["n"] == 1, "同参数 300s 内应命中缓存"


async def test_sina_indices_skip_zero_price_auction(monkeypatch) -> None:
    """集合竞价/停牌时段新浪返回现价 0：必须跳过，不能算出 -100% 假涨跌。"""
    from app import quotes

    class _Resp:
        def raise_for_status(self):
            return None

        @property
        def text(self):
            zero = "0,0.000," * 15
            return (
                f'var hq_str_sz399001="深证成指,0.000,11138.198,0.000,0.000,0.000,{zero}'
                f'2026-10-30,09:04:18,00,";\n'
                f'var hq_str_sh000001="上证指数,3655.00,3651.41,3651.41,3655.00,3648.00,{zero}'
                f'2026-10-30,09:30:00,00,";\n'
            )

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            return _Resp()

    monkeypatch.setattr(quotes.httpx, "AsyncClient", lambda *a, **kw: _Client())
    monkeypatch.setattr(quotes._indices_cache, "get", lambda k: None, raising=False)
    out = await quotes._sina_indices()
    names = {i["symbol"]: i for i in out}
    # 现价 0 的档位被跳过，不出现 -100% 假涨跌
    assert "sz399001" not in names
    assert names["sh000001"]["price"] == 3651.41

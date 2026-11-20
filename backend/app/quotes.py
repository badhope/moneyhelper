"""行情层门面：异步、可插拔、失败降级。

- 快照/批量行情/单股报价在本文件；指数行情在 `quotes_indices.py`，今日盈亏在
  `quotes_pnl.py`，K 线在 `quotes_kline.py`；数据源适配在 `quotes_sources.py`。
- 被回归测试 monkeypatch 注入的主函数（live_quotes / quote_now / kline）与数据源
  helper 均从本模块同名导出，补丁口径不变。
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any

import httpx
from cachetools import TTLCache

from . import db
from .quotes_indices import (  # noqa: F401,E402
    INDICES,
    _indices_cache,
    _sina_indices,
    indices_quotes,
)
from .quotes_kline import (  # noqa: F401,E402
    _KLINE_FIELDS,
    KLINE_URL,
    KLINE_URL_HTTP,
    KLT,
    _fetch_kline,
    _kline_cache,
    _parse_kline_rows,
)
from .quotes_pnl import _today_pnl_cache, portfolio_today_pnl  # noqa: F401,E402
from .quotes_sources import (  # noqa: F401,E402
    _SINA_HEADERS,
    _UA,
    EASTMONEY_URL,
    SINA_URL,
    _eastmoney_quotes,
    _num,
    _parse_price,
    _sina_prev_close,
    _sina_quotes,
    _to_secid,
    _to_sina,
)

_live_cache = TTLCache[str, tuple[dict[str, float], str]](maxsize=256, ttl=30.0)

_offline: ContextVar[bool] = ContextVar("quotes_offline", default=False)

@contextmanager
def snapshot_only():
    """上下文管理器：期间所有行情取快照价，不发任何网络请求。

    用途：CLI 默认行为、离线自检、单元测试里不想 mock 的场合。
    """
    token = _offline.set(True)
    try:
        yield
    finally:
        _offline.reset(token)

_last_source = "snapshot"

def last_source() -> str:
    """最近一次取价实际生效的来源：eastmoney | sina | snapshot。"""
    return _last_source

def _snapshot(positions: list[dict[str, Any]]) -> dict[str, float]:
    return {p["symbol"]: float(p["last"]) for p in positions}

async def live_quotes(positions: list[dict[str, Any]]) -> dict[str, float]:
    """按设置取行情：auto/eastmoney → 东财（失败降级新浪 → 快照）；snapshot → 快照价。

    只对非现金标的请求实时价；现金直接用库里价格。
    每次调用都会更新 last_source()，供来源标注使用。
    """
    global _last_source
    if _offline.get():
        _last_source = "snapshot"
        return _snapshot(positions)
    mode = (await db.get_settings()).get("quote_source_mode", "auto")
    symbols = [p["symbol"] for p in positions if p["kind"] != "现金"]
    if mode == "snapshot" or not symbols:
        _last_source = "snapshot"
        return _snapshot(positions)

    key = ",".join(sorted(symbols))
    cached = _live_cache.get(key)
    if cached is not None:
        _last_source = cached[1]
        return cached[0]

    got = await _eastmoney_quotes(symbols)
    if got:
        _last_source = "eastmoney"
    else:
        got = await _sina_quotes(symbols)
        _last_source = "sina" if got else "snapshot"
        if not got:
            got = _snapshot(positions)
    _live_cache[key] = (got, _last_source)
    return got

_quote_cache = TTLCache[str, dict[str, Any] | None](maxsize=128, ttl=30.0)

SINGLE_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"

async def quote_now(symbol: str) -> dict[str, Any] | None:
    """单只标的最新行情：{symbol, name, price, change, change_pct, source}；不可用返回 None。

    name 由调用方（自选库）提供后覆盖；这里只保证价格与涨跌。
    """
    key = symbol.strip().upper()
    cached = _quote_cache.get(key)
    if cached is not None:
        return cached

    out: dict[str, Any] | None = None
    secid = _to_secid(key)
    if secid:
        params = {
            "fltt": "2",
            "invt": "2",
            "fields": "f43,f44,f45,f46,f57,f58,f60,f169,f170",
            "secid": secid,
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        }
        headers = {"User-Agent": _UA}
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(SINGLE_QUOTE_URL, params=params, headers=headers)
                resp.raise_for_status()
                data = ((resp.json() or {}).get("data") or {})
            price = _parse_price(data.get("f43"))
            if price is not None:
                out = {
                    "symbol": key,
                    "name": data.get("f58") or "",
                    "price": price,
                    "change": _num(data.get("f169")),
                    "change_pct": _num(data.get("f170")),
                    "source": "eastmoney",
                }
        except Exception:  # noqa: BLE001 — 单股报价失败降级
            out = None

    if out is None:
        sina_code = _to_sina(key)
        if sina_code:
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    resp = await client.get(SINA_URL + sina_code, headers=_SINA_HEADERS)
                    resp.raise_for_status()
                    text = resp.content.decode("gbk", errors="ignore")
                m = re.search(rf'var hq_str_{re.escape(sina_code)}="([^"]*)"', text)
                if m:
                    parts = m.group(1).split(",")
                    if len(parts) >= 4:
                        price = _parse_price(parts[3])
                        prev = _parse_price(parts[2])
                        # 盘前/非交易时段现价为 0.000（_parse_price 判无效）：
                        # 用昨收兜底显示（涨跌 0），避免「无法获取行情」假失败
                        if price is None and prev is not None:
                            price = prev
                        if price is not None:
                            out = {
                                "symbol": key,
                                "name": parts[0],
                                "price": price,
                                "change": round(price - prev, 3) if prev is not None else None,
                                "change_pct": round((price - prev) / prev * 100, 2) if prev not in (None, 0) else 0.0,
                                "source": "sina",
                            }
            except Exception:  # noqa: BLE001
                out = None

    _quote_cache[key] = out
    return out

_ALL_CACHES: tuple[TTLCache[Any, Any], ...] = (
    _live_cache,
    _kline_cache,
    _indices_cache,
    _today_pnl_cache,
    _quote_cache,
)

async def invalidate_quotes_cache() -> None:
    for _c in _ALL_CACHES:
        _c.clear()

async def kline(
    symbol: str, period: str = "daily", limit: int = 120
) -> dict[str, Any] | None:
    """取 K 线：{symbol, period, points, source}；不可用或失败一律 None。

    与实时行情同源（东财），但**不进总览请求**——只在用户点开某只标的时按需拉，
    300s 缓存，避免拖慢首屏。
    """
    secid = _to_secid(symbol)
    klt = KLT.get(period, KLT["daily"])
    if not secid:
        return None
    key = (secid, period, max(1, min(limit, 1000)))
    cached = _kline_cache.get(key)
    if cached is not None:
        return cached
    try:
        rows = await _fetch_kline(secid, klt, key[2])
    except Exception:  # noqa: BLE001 — K 线失败不影响任何其他功能
        return None
    points = _parse_kline_rows(rows)
    if not points:
        return None
    out: dict[str, Any] = {
        "symbol": symbol,
        "period": period,
        "points": points[-key[2] :],
        "source": "eastmoney",
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    _kline_cache[key] = out
    return out

async def index_kline(symbol: str, limit: int = 750) -> dict[str, Any] | None:
    """基准指数日线。symbol 形如 sh000300（见 INDICES）。不可用返回 None。"""
    meta = INDICES.get(symbol)
    if not meta:
        return None
    secid = meta[0]
    key = (f"idx:{secid}", "daily", max(1, min(limit, 1000)))
    cached = _kline_cache.get(key)
    if cached is not None:
        return cached
    try:
        rows = await _fetch_kline(secid, KLT["daily"], key[2])
    except Exception:  # noqa: BLE001 — 基准失败只影响对比指标，不影响主流程
        return None
    points = _parse_kline_rows(rows)
    if not points:
        return None
    out: dict[str, Any] = {
        "symbol": symbol,
        "name": meta[1],
        "period": "daily",
        "points": points[-key[2] :],
        "source": "eastmoney",
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    _kline_cache[key] = out
    return out

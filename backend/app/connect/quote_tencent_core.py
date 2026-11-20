"""腾讯行情基座：字段表、缓存、批量拉取与单只快照。"""

from __future__ import annotations

from typing import Any

import httpx
from cachetools import TTLCache

from .. import symbols

_UA = "Mozilla/5.0 (moneyhelper)"

QT_URL = "https://qt.gtimg.cn/q="
MINUTE_URL = "https://web.ifzq.gtimg.cn/appstock/app/minute/query"
KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

# 腾讯行情字段下标（0 起，已用 sh600519 实测核对）
_TENCENT_FIELDS = {
    "name": 1,
    "code": 2,
    "price": 3,
    "prev_close": 4,
    "open": 5,
    "volume_hand": 6,      # 成交量（手）
    "outer": 7,
    "inner": 8,
    "bid1": 9,
    "ask1": 19,
    "time": 30,
    "change": 31,
    "change_pct": 32,
    "high": 33,
    "low": 34,
    "amount_wan": 37,      # 成交额（万元）
    "turnover_pct": 38,    # 换手率 %
    "pe_ttm": 39,
    "amplitude_pct": 43,   # 振幅 %
    "float_mv": 44,        # 流通市值（亿元）
    "total_mv": 45,        # 总市值（亿元）
    "pb": 46,
    "limit_up": 47,
    "limit_down": 48,
    "volume_ratio": 49,    # 量比
    "avg_price": 51,
}

_quote_cache: TTLCache[str, dict[str, Any] | None] = TTLCache(maxsize=512, ttl=20.0)
_minute_cache: TTLCache[str, dict[str, Any] | None] = TTLCache(maxsize=128, ttl=60.0)
_tx_kline_cache: TTLCache[str, dict[str, Any] | None] = TTLCache(maxsize=256, ttl=300.0)
_breadth_cache: TTLCache[str, dict[str, Any] | None] = TTLCache(maxsize=4, ttl=60.0)




to_tencent = symbols.to_tencent


def _num(raw: Any) -> float | None:
    try:
        v = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _parse_quote_body(body: str) -> dict[str, Any] | None:
    parts = body.split("~")
    if len(parts) < 50:
        return None
    price = _num(parts[_TENCENT_FIELDS["price"]])
    if price is None or price <= 0:
        return None
    prev = _num(parts[_TENCENT_FIELDS["prev_close"]])
    change_pct = _num(parts[_TENCENT_FIELDS["change_pct"]])
    # 腾讯在停牌/盘前偶尔给 0：用昨收兜底算涨跌幅，但仍标 stale
    if change_pct is None and prev and prev > 0:
        change_pct = round((price / prev - 1) * 100, 2)
    return {
        "symbol": parts[_TENCENT_FIELDS["code"]],
        "name": parts[_TENCENT_FIELDS["name"]].strip(),
        "price": price,
        "prev_close": prev,
        "open": _num(parts[_TENCENT_FIELDS["open"]]),
        "high": _num(parts[_TENCENT_FIELDS["high"]]),
        "low": _num(parts[_TENCENT_FIELDS["low"]]),
        "change": _num(parts[_TENCENT_FIELDS["change"]]),
        "change_pct": change_pct,
        "volume_hand": _num(parts[_TENCENT_FIELDS["volume_hand"]]),
        "amount": _num(parts[_TENCENT_FIELDS["amount_wan"]]),  # 万元
        "turnover_pct": _num(parts[_TENCENT_FIELDS["turnover_pct"]]),
        "pe_ttm": _num(parts[_TENCENT_FIELDS["pe_ttm"]]),
        "pb": _num(parts[_TENCENT_FIELDS["pb"]]),
        "amplitude_pct": _num(parts[_TENCENT_FIELDS["amplitude_pct"]]),
        "float_mv_yi": _num(parts[_TENCENT_FIELDS["float_mv"]]),
        "total_mv_yi": _num(parts[_TENCENT_FIELDS["total_mv"]]),
        "volume_ratio": _num(parts[_TENCENT_FIELDS["volume_ratio"]]),
        "limit_up": _num(parts[_TENCENT_FIELDS["limit_up"]]),
        "limit_down": _num(parts[_TENCENT_FIELDS["limit_down"]]),
        "time": parts[_TENCENT_FIELDS["time"]],
        "source": "tencent",
    }


async def quotes_batch(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """批量行情（腾讯源）：返回 {symbol: quote}；不可用返回 {}。

    一次请求拿全部代码，比逐个请求省往返；失败不抛错，由调用方降级。
    """
    wanted = [s for s in (str(x).strip().upper() for x in symbols) if s]
    if not wanted:
        return {}
    codes = []
    mapping: dict[str, str] = {}
    for s in wanted:
        tx = to_tencent(s)
        if tx:
            codes.append(tx)
            mapping[tx] = s
    if not codes:
        return {}

    key = ",".join(sorted(codes))
    cached = _quote_cache.get(key)
    if cached is not None:
        return {mapping[c]: cached[c] for c in cached if c in mapping}

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(QT_URL + ",".join(codes), headers={"Referer": "https://gu.qq.com", "User-Agent": _UA})
            resp.raise_for_status()
            raw = resp.content.decode("gbk", errors="replace")
    except Exception:  # noqa: BLE001 — 行情失败一律降级
        return {}

    parsed: dict[str, dict[str, Any]] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("v_") or '="' not in line:
            continue
        head, _, body = line.partition('="')
        code = head[2:]
        body = body.rstrip('";')
        item = _parse_quote_body(body)
        if item:
            item["symbol"] = mapping.get(code, item["symbol"])
            parsed[code] = item
    if not parsed:
        _quote_cache[key] = None
        return {}
    _quote_cache[key] = parsed
    return {mapping[c]: parsed[c] for c in parsed if c in mapping}


async def quote(symbol: str) -> dict[str, Any] | None:
    """单只行情（腾讯源）。"""
    out = await quotes_batch([symbol])
    return out.get(str(symbol).strip().upper())

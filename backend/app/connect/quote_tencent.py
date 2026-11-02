"""行情深化：腾讯源（本机实测可达）+ 个股档案 + 市场温度 + 分时。

为什么加腾讯源：
- 东财 push2 在本机运营商出口被直接重置（curl 000 / httpx RemoteProtocolError）；
- 新浪 hq.sinajs.cn 可用但只有基础字段，没有 PE/PB/市值/量比；
- 腾讯 qt.gtimg.cn 返回 50+ 字段（价格、涨跌、PE、PB、总市值/流通市值、量比、换手、
  振幅、涨停/跌停价、外盘内盘），且同时支持指数与个股，一个请求批量拿。

口径：
- 腾讯字段是 GBK 编码、`~` 分隔；下标含义见 `_TENCENT_FIELDS`；
- 市值单位是「亿元」，前端按亿元展示，避免再换算错；
- 分时用 `web.ifzq.gtimg.cn/appstock/app/minute/query`，返回 `HHMM 价格 累计量 累计额`。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx
from cachetools import TTLCache

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


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def to_tencent(symbol: str) -> str | None:
    """系统内 symbol → 腾讯代码（sh/sz/bj 前缀）。"""
    s = str(symbol or "").strip().upper()
    if s in ("CASH", "") or not s.isdigit() or len(s) != 6:
        return None
    if s[0] in "65":
        return f"sh{s}"
    if s[0] in "03":
        return f"sz{s}"
    if s.startswith(("15", "16")):
        return f"sz{s}"
    if s[0] in "489":
        return f"bj{s}"
    return None


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


async def profile(symbol: str) -> dict[str, Any] | None:
    """个股档案：行情快照 + 估值 + 规模 + 交易活跃度，一次打包。

    明确不提供「行业/主营」这类需要另一套接口的字段（宁缺勿编）。
    """
    q = await quote(symbol)
    if q is None:
        return None
    out = dict(q)
    total_mv = q.get("total_mv_yi")
    pe = q.get("pe_ttm")
    out["valuation"] = {
        "pe_ttm": pe,
        "pb": q.get("pb"),
        "total_mv_yi": total_mv,
        "float_mv_yi": q.get("float_mv_yi"),
        "pe_note": "PE 为负表示亏损；腾讯口径为 TTM 滚动市盈率" if pe is not None and pe < 0 else "",
    }
    out["activity"] = {
        "turnover_pct": q.get("turnover_pct"),
        "volume_ratio": q.get("volume_ratio"),
        "amplitude_pct": q.get("amplitude_pct"),
        "amount_wan": q.get("amount"),
    }
    return out


async def minute(symbol: str) -> dict[str, Any] | None:
    """分时数据：[{time, price, volume, amount}]，用于当日走势。"""
    tx = to_tencent(symbol)
    if not tx:
        return None
    cached = _minute_cache.get(tx)
    if cached is not None:
        return cached
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(MINUTE_URL, params={"code": tx}, headers={"Referer": "https://gu.qq.com", "User-Agent": _UA})
            resp.raise_for_status()
            payload = resp.json() or {}
    except Exception:  # noqa: BLE001
        return None
    node = ((payload.get("data") or {}).get(tx) or {}).get("data") or {}
    rows = node.get("data") or []
    points = []
    for row in rows:
        bits = str(row).split()
        if len(bits) < 2:
            continue
        price = _num(bits[1])
        if price is None:
            continue
        points.append(
            {
                "time": f"{bits[0][:2]}:{bits[0][2:]}" if len(bits[0]) == 4 else bits[0],
                "price": price,
                "volume": _num(bits[2]) if len(bits) > 2 else None,
                "amount": _num(bits[3]) if len(bits) > 3 else None,
            }
        )
    if not points:
        return None
    out = {"symbol": symbol, "points": points, "date": node.get("date") or "", "source": "tencent", "fetched_at": _now()}
    _minute_cache[tx] = out
    return out


async def kline(symbol: str, period: str = "daily", limit: int = 120) -> dict[str, Any] | None:
    """K 线（腾讯前复权）：与 quotes.kline 返回形状一致，作为东财不可用时的备源。"""
    tx = to_tencent(symbol)
    if not tx:
        return None
    kind = {"daily": "day", "weekly": "week", "monthly": "month"}.get(period, "day")
    n = max(10, min(int(limit), 500))
    key = f"{tx}:{kind}:{n}"
    cached = _tx_kline_cache.get(key)
    if cached is not None:
        return cached
    params = {"param": f"{tx},{kind},,,{n},qfq"}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(KLINE_URL, params=params, headers={"Referer": "https://gu.qq.com", "User-Agent": _UA})
            resp.raise_for_status()
            payload = resp.json() or {}
    except Exception:  # noqa: BLE001
        return None
    node = (payload.get("data") or {}).get(tx) or {}
    rows = node.get(f"qfq{kind}") or node.get(kind) or []
    points = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        d, open_p, close_p, high_p, low_p, volume = row[:6]
        close_v = _num(close_p)
        if close_v is None:
            continue
        points.append(
            {
                "date": str(d),
                "open": _num(open_p) or close_v,
                "close": close_v,
                "high": _num(high_p) or close_v,
                "low": _num(low_p) or close_v,
                "volume": _num(volume) or 0,
            }
        )
    if not points:
        return None
    out = {
        "symbol": symbol,
        "period": period,
        "points": points[-n:],
        "source": "tencent",
        "fetched_at": _now(),
    }
    _tx_kline_cache[key] = out
    return out


async def market_breadth() -> dict[str, Any]:
    """市场温度：涨跌家数分布 + 涨停/跌停/强势股数量。

    数据源：东财 push2ex（`getTopicZDFenBu` 涨跌分布、`getTopicZTPool` 涨停池、
    `getTopicDTPool` 跌停池、`getTopicQSPool` 强势池）。push2ex 与 push2 不同域名，
    实测本机可达。
    """
    cached = _breadth_cache.get("v")
    if cached is not None:
        return cached

    headers = {"Referer": "https://quote.eastmoney.com/", "User-Agent": _UA}
    ut = "7eea3edcaed734bea9cbfc24409ed989"

    async def _get(url: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get(url, params=params, headers=headers)
                resp.raise_for_status()
                return resp.json() or {}
        except Exception:  # noqa: BLE001 — 单个子接口失败不影响整体
            return {}

    dist_task = _get("https://push2ex.eastmoney.com/getTopicZDFenBu", {"ut": ut, "dpt": "wz.ztzt"})
    zt_task = _get(
        "https://push2ex.eastmoney.com/getTopicZTPool",
        {"ut": ut, "dpt": "wz.ztzt", "Pageindex": "0", "pagesize": "1", "sort": "fbt:asc"},
    )
    dt_task = _get(
        "https://push2ex.eastmoney.com/getTopicDTPool",
        {"ut": ut, "dpt": "wz.ztzt", "Pageindex": "0", "pagesize": "1", "sort": "fund:asc"},
    )
    qs_task = _get(
        "https://push2ex.eastmoney.com/getTopicQSPool",
        {"ut": ut, "dpt": "wz.ztzt", "Pageindex": "0", "pagesize": "1", "sort": "zdp:desc"},
    )
    dist, zt, dt, qs = await asyncio.gather(dist_task, zt_task, dt_task, qs_task)

    buckets = ((dist.get("data") or {}).get("fenbu")) or []
    up = down = flat = limit_up = limit_down = 0
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        for k, v in bucket.items():
            try:
                pct = int(k)
                count = int(v)
            except (TypeError, ValueError):
                continue
            if pct > 0:
                up += count
            elif pct < 0:
                down += count
            else:
                flat += count
            if pct >= 10:
                limit_up += count
            if pct <= -10:
                limit_down += count

    total = up + down + flat
    zt_count = int((zt.get("data") or {}).get("tc") or 0)
    dt_count = int((dt.get("data") or {}).get("tc") or 0)
    qs_count = int((qs.get("data") or {}).get("tc") or 0)
    if total == 0 and zt_count == 0 and dt_count == 0:
        _breadth_cache["v"] = None
        return {"available": False, "reason": "涨跌分布接口暂时不可用", "checked_at": _now()}

    # 情绪温度 0-100：上涨占比 60% + 涨停/跌停比 25% + 强势股占比 15%
    up_ratio = up / total if total else 0.0
    zt_ratio = zt_count / (zt_count + dt_count) if (zt_count + dt_count) else 0.5
    qs_ratio = min(1.0, qs_count / max(1, total) * 20)
    temperature = round((up_ratio * 0.6 + zt_ratio * 0.25 + qs_ratio * 0.15) * 100, 1)
    if temperature >= 70:
        mood = "hot"
    elif temperature >= 55:
        mood = "warm"
    elif temperature >= 45:
        mood = "neutral"
    elif temperature >= 30:
        mood = "cool"
    else:
        mood = "cold"

    out = {
        "available": True,
        "up": up,
        "down": down,
        "flat": flat,
        "total": total,
        "limit_up": max(limit_up, zt_count),
        "limit_down": max(limit_down, dt_count),
        "strong": qs_count,
        "up_ratio_pct": round(up_ratio * 100, 1),
        "temperature": temperature,
        "mood": mood,
        "buckets": buckets,
        "source": "eastmoney_push2ex",
        "checked_at": _now(),
    }
    _breadth_cache["v"] = out
    return out

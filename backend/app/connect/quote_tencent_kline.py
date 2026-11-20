"""K 线（前复权）：东财不可用时的备源，形状与 quotes.kline 一致。"""

from __future__ import annotations

from typing import Any

import httpx

from ..timeutil import now_iso as _now
from .quote_tencent_core import _UA, KLINE_URL, _num, _tx_kline_cache, to_tencent


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

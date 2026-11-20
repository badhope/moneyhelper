"""分时序列：当日分钟价量与累计成交额。"""

from __future__ import annotations

from typing import Any

import httpx

from ..timeutil import now_iso as _now
from .quote_tencent_core import _UA, MINUTE_URL, _minute_cache, _num, to_tencent


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

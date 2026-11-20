"""组合今日盈亏：东财现价-昨收，失败降级新浪备源。"""

from __future__ import annotations

from typing import Any

import httpx
from cachetools import TTLCache

from .quotes_sources import (
    EASTMONEY_URL,
    _parse_price,
    _sina_prev_close,
    _sina_quotes,
    _to_secid,
)

_today_pnl_cache = TTLCache[str, tuple[dict[str, float], float]](maxsize=1, ttl=30.0)


async def portfolio_today_pnl(positions: list[dict[str, Any]]) -> dict[str, Any]:
    """今日盈亏：{total, items:{symbol: pnl}}；网络失败返回 {total: 0, items: {}}。"""
    cached = _today_pnl_cache.get("v")
    if cached is not None:
        return {"total": cached[1], "items": cached[0]}

    code_to_symbol: dict[str, str] = {}
    secids: list[str] = []
    for p in positions:
        if p.get("kind") == "现金":
            continue
        sid = _to_secid(p["symbol"])
        if sid:
            code_to_symbol[sid.split(".", 1)[1]] = p["symbol"]
            secids.append(sid)
    items: dict[str, float] = {}
    total = 0.0
    if secids:
        params = {
            "fltt": "2",
            "invt": "2",
            "fields": "f2,f18,f12",
            "secids": ",".join(secids),
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        }
        headers = {"User-Agent": "Mozilla/5.0 (moneyhelper)"}
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(EASTMONEY_URL, params=params, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
        except Exception:  # noqa: BLE001 — 今日盈亏失败不影响其他
            payload = None
        if payload is not None:
            diff = ((payload or {}).get("data") or {}).get("diff") or []
            if isinstance(diff, dict):
                diff = list(diff.values())
            pos_by_symbol = {p["symbol"]: p for p in positions}
            for item in diff:
                if not isinstance(item, dict):
                    continue
                sym = code_to_symbol.get(str(item.get("f12") or ""))
                if not sym or sym not in pos_by_symbol:
                    continue
                last = _parse_price(item.get("f2"))
                prev = _parse_price(item.get("f18"))
                if last is None or prev is None:
                    continue
                pnl = float(pos_by_symbol[sym].get("shares") or 0) * (last - prev)
                items[sym] = round(pnl, 2)
                total += pnl
        # 东财不可用 → 新浪备源（现价 - 昨收）× 份额
        if not items and secids:
            non_cash = [p for p in positions if p.get("kind") != "现金"]
            quotes = await _sina_quotes([p["symbol"] for p in non_cash])
            prev = await _sina_prev_close([p["symbol"] for p in non_cash])
            if quotes and prev:
                for p in non_cash:
                    q, pr = quotes.get(p["symbol"]), prev.get(p["symbol"])
                    if q is None or pr is None:
                        continue
                    pnl = float(p.get("shares") or 0) * (q - pr)
                    items[p["symbol"]] = round(pnl, 2)
                    total += pnl
    total = round(total, 2)
    _today_pnl_cache["v"] = (items, total)
    return {"total": total, "items": items}

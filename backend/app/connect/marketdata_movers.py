"""全市场排行：东财 push2 主源、新浪 Market_Center 备源。"""

from __future__ import annotations

from typing import Any

from cachetools import TTLCache

from ..timeutil import now_iso as _now
from . import marketdata as _facade
from .marketdata_common import _UA, _num

MOVERS_URL = "https://push2.eastmoney.com/api/qt/clist/get"
SINA_MOVERS_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
)

_movers_cache: TTLCache[str, list[dict[str, Any]]] = TTLCache(maxsize=8, ttl=60.0)


def _secid_to_symbol(code: str) -> str:
    """东财代码 → 系统内 symbol（沪市 1.x → 6/5 开头，深市 0.x → 0/3/1 开头）。"""
    return str(code).strip()


async def market_movers(kind: str = "gainers", limit: int = 20) -> dict[str, Any]:
    """全市场排行：kind = gainers | losers | turnover | amount。

    主源东财 push2、备源新浪 Market_Center（push2 在本机网络常被重置，实测只有新浪稳定）。
    返回 {items:[{symbol,name,price,change_pct,amount}], kind, source, fetched_at}；
    失败返回空列表 + note，不抛错。
    """
    kind = kind if kind in ("gainers", "losers", "turnover", "amount") else "gainers"
    n = max(1, min(int(limit), 100))
    key = f"{kind}:{n}"
    cached = _movers_cache.get(key)
    if cached is not None:
        return {"items": cached, "kind": kind, "source": "cached", "fetched_at": _now(), "note": ""}

    east = await _facade._movers_eastmoney(kind, n)
    if east:
        _movers_cache[key] = east
        return {"items": east, "kind": kind, "source": "eastmoney", "fetched_at": _now(), "note": ""}

    sina = await _facade._movers_sina(kind, n)
    if sina:
        _movers_cache[key] = sina
        return {"items": sina, "kind": kind, "source": "sina", "fetched_at": _now(), "note": "东财不可用，已切换新浪"}
    return {
        "items": [],
        "kind": kind,
        "source": "none",
        "fetched_at": _now(),
        "note": "涨跌榜接口暂时不可用（网络或对方限流）",
    }


async def _movers_eastmoney(kind: str, n: int) -> list[dict[str, Any]]:
    fid = {"gainers": "f3", "losers": "f3", "turnover": "f8", "amount": "f6"}[kind]
    po = "0" if kind == "losers" else "1"
    params = {
        "pn": "1",
        "pz": str(n),
        "po": po,
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fid": fid,
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f2,f3,f6,f8,f12,f14",
    }
    try:
        async with _facade.httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(MOVERS_URL, params=params, headers={"User-Agent": _UA})
            resp.raise_for_status()
            payload = resp.json() or {}
    except Exception:  # noqa: BLE001 — 主源失败交给备源
        return []
    diff = ((payload.get("data") or {}).get("diff")) or []
    if isinstance(diff, dict):
        diff = list(diff.values())
    items = []
    for r in diff:
        if not isinstance(r, dict):
            continue
        code = str(r.get("f12") or "").strip()
        name = str(r.get("f14") or "").strip()
        if not code or not name:
            continue
        items.append(
            {
                "symbol": _secid_to_symbol(code),
                "name": name,
                "price": _num(r.get("f2")),
                "change_pct": _num(r.get("f3")),
                "amount": _num(r.get("f6")),
                "turnover_pct": _num(r.get("f8")),
            }
        )
    return items


async def _movers_sina(kind: str, n: int) -> list[dict[str, Any]]:
    """新浪全市场排行备源；字段口径与东财不同，统一成同一形状。"""
    sort = {"gainers": "changepercent", "losers": "changepercent", "turnover": "turnoverratio", "amount": "amount"}[
        kind
    ]
    asc = "1" if kind == "losers" else "0"
    params = {"page": "1", "num": str(n), "sort": sort, "asc": asc, "node": "hs_a", "symbol": ""}
    headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": _UA}
    try:
        async with _facade.httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(SINA_MOVERS_URL, params=params, headers=headers)
            resp.raise_for_status()
            rows = resp.json() or []
    except Exception:  # noqa: BLE001
        return []
    items = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        code = str(r.get("code") or "").strip()
        name = str(r.get("name") or "").strip()
        if not code or not name:
            continue
        items.append(
            {
                "symbol": code,
                "name": name,
                "price": _num(r.get("trade")),
                "change_pct": _num(r.get("changepercent")),
                "amount": _num(r.get("amount")),
                "turnover_pct": _num(r.get("turnoverratio")),
            }
        )
    return items

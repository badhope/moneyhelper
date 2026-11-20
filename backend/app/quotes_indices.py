"""大盘指数行情：东财 push2 批量快照，失败降级新浪 hq.sinajs.cn。"""

from __future__ import annotations

from typing import Any

import httpx
from cachetools import TTLCache

from .quotes_sources import (
    _SINA_HEADERS,
    EASTMONEY_URL,
    SINA_URL,
    _num,
    _parse_price,
)

INDICES: dict[str, tuple[str, str]] = {
    "sh000001": ("1.000001", "上证指数"),
    "sz399001": ("0.399001", "深证成指"),
    "sz399006": ("0.399006", "创业板指"),
    "sh000300": ("1.000300", "沪深300"),
}


_indices_cache = TTLCache[str, list[dict[str, Any]]](maxsize=1, ttl=30.0)


async def indices_quotes() -> list[dict[str, Any]]:
    """大盘指数快照：[{symbol, name, price, change, change_pct}]；失败返回 []。

    东财 push2 在部分网络（尤其本机运营商出口）会被直接重置，实测整条行情条消失。
    因此失败后降级新浪 hq.sinajs.cn（与个股备源同一域名，已证明可达）。
    """
    cached = _indices_cache.get("v")
    if cached is not None:
        return cached

    params = {
        "fltt": "2",
        "invt": "2",
        "fields": "f2,f3,f4,f12,f14",
        "secids": ",".join(secid for secid, _ in INDICES.values()),
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    }
    headers = {"User-Agent": "Mozilla/5.0 (moneyhelper)"}
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(EASTMONEY_URL, params=params, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
    except Exception:  # noqa: BLE001 — 东财失败降级新浪，不影响其他功能
        out = await _sina_indices()
        if out:
            _indices_cache["v"] = out
        return out

    diff = ((payload or {}).get("data") or {}).get("diff") or []
    if isinstance(diff, dict):
        diff = list(diff.values())
    by_code = {secid.split(".", 1)[1]: (sym, name) for sym, (secid, name) in INDICES.items()}

    out: list[dict[str, Any]] = []
    for item in diff:
        if not isinstance(item, dict):
            continue
        code = str(item.get("f12") or "")
        meta = by_code.get(code)
        if not meta:
            continue
        px = _parse_price(item.get("f2"))
        if px is None:
            continue
        sym, name = meta
        out.append(
            {
                "symbol": sym,
                "name": name,
                "price": px,
                "change": _num(item.get("f4")),
                "change_pct": _num(item.get("f3")),
            }
        )
    if not out:
        out = await _sina_indices()
    if out:
        _indices_cache["v"] = out
    return out


async def _sina_indices() -> list[dict[str, Any]]:
    """新浪指数备源：批量拉取四大指数，GBK 解码后按昨收算涨跌。"""
    names = {sym: name for sym, (_secid, name) in INDICES.items()}
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(
                SINA_URL + ",".join(names),
                headers=_SINA_HEADERS,
            )
            resp.raise_for_status()
            resp.encoding = "gbk"
            text = resp.text
    except Exception:  # noqa: BLE001 — 备源也失败则隐藏行情条
        return []

    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        if "=" not in line:
            continue
        head, _, body = line.partition("=")
        sym = head.replace("var hq_str_", "").strip()
        if sym not in names:
            continue
        parts = body.strip().strip(";").strip('"').split(",")
        if len(parts) < 4:
            continue
        try:
            prev = float(parts[2])
            now = float(parts[3])
        except ValueError:
            continue
        # 集合竞价/停牌时段现价为 0：跳过而不是算出 -100% 的假涨跌
        if prev <= 0 or now <= 0:
            continue
        out.append(
            {
                "symbol": sym,
                "name": names[sym],
                "price": round(now, 2),
                "change": round(now - prev, 2),
                "change_pct": round((now / prev - 1) * 100, 2),
            }
        )
    return out

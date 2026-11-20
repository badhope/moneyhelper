"""K 线：东财 push2his 日/周/月线（前复权），HTTP→HTTPS 回退，300s 缓存。"""

from __future__ import annotations

from typing import Any

import httpx
from cachetools import TTLCache

from .quotes_sources import _num

KLT = {"daily": 101, "weekly": 102, "monthly": 103}


KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


KLINE_URL_HTTP = "http://push2his.eastmoney.com/api/qt/stock/kline/get"


_KLINE_FIELDS = (
    "date",
    "open",
    "close",
    "high",
    "low",
    "volume",
    "amount",
    "amplitude",
    "pct_change",
    "change",
    "turnover",
)


_kline_cache = TTLCache[tuple[str, str, int], dict[str, Any]](maxsize=64, ttl=300.0)


def _parse_kline_rows(rows: list[Any]) -> list[dict[str, Any]]:
    """东财 kline 字符串数组 → 结构化点；坏行跳过，不影响其余。"""
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, str):
            continue
        parts = row.split(",")
        if len(parts) < 11:
            continue
        point: dict[str, Any] = {"date": parts[0].strip()}
        for key, raw in zip(_KLINE_FIELDS[1:], parts[1:11], strict=False):
            point[key] = _num(raw)
        if point["close"] is None:
            continue
        out.append(point)
    return out


async def _fetch_kline(secid: str, klt: int, limit: int) -> list[str]:
    params = {
        "secid": secid,
        "klt": str(klt),
        "fqt": "1",  # 前复权
        "beg": "19900101",
        "end": "20500101",
        "lmt": str(max(1, min(limit, 1000))),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    }
    headers = {"User-Agent": "Mozilla/5.0 (moneyhelper)"}
    last_exc: Exception | None = None
    for url in (KLINE_URL, KLINE_URL_HTTP):
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get(url, params=params, headers=headers)
                resp.raise_for_status()
                data = (resp.json() or {}).get("data") or {}
            rows = data.get("klines") or []
            return [r for r in rows if isinstance(r, str)]
        except Exception as exc:  # noqa: BLE001 — 换下一个端点重试
            last_exc = exc
    raise last_exc if last_exc else RuntimeError("kline fetch failed")





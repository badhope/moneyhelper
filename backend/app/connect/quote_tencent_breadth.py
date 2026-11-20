"""市场温度：东财 push2ex 涨跌分布/涨停跌停/强势池聚合。"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from ..timeutil import now_iso as _now
from .quote_tencent_core import _UA, _breadth_cache


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

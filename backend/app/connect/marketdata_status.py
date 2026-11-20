"""数据源连通性探测：并发轻量请求，任一源失败不影响其他源。"""

from __future__ import annotations

import asyncio
from typing import Any

from ..timeutil import now_iso as _now
from . import marketdata as _facade


async def source_status() -> dict[str, Any]:
    """探测各公开数据源可用性（并发），供连接中心显示「通/断」。

    只做一次轻量请求，不重试；任一源失败不影响其他源。
    """
    checks = {
        "eastmoney_quote": _facade.index_snapshot(),
        "eastmoney_fund": _facade.fund_nav("110011"),
        "eastmoney_movers": _facade.market_movers("gainers", 3),
    }
    names = list(checks)
    results = await asyncio.gather(*checks.values(), return_exceptions=True)
    out: list[dict[str, Any]] = []
    for name, res in zip(names, results, strict=False):
        ok = False
        detail = ""
        if isinstance(res, Exception):
            detail = f"{type(res).__name__}: {res}"
        elif name == "eastmoney_quote":
            ok = bool((res or {}).get("items"))
            detail = f"{len((res or {}).get('items') or [])} 个指数" if ok else ((res or {}).get("note") or "无返回")
        elif name == "eastmoney_fund":
            ok = bool((res or {}).get("items"))
            detail = "净值可用" if ok else "无返回"
        else:
            ok = bool((res or {}).get("items"))
            detail = f"{len((res or {}).get('items') or [])} 条" if ok else "无返回"
        out.append({"id": name, "ok": ok, "detail": detail})
    return {"items": out, "checked_at": _now()}

"""基金数据：净值快照与历史净值（东财基金移动端接口）。"""

from __future__ import annotations

from typing import Any

from cachetools import TTLCache

from ..timeutil import now_iso as _now
from . import marketdata as _facade
from .marketdata_common import _UA, _num

FUND_NAV_URL = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNFInfo"
FUND_HISTORY_URL = "https://api.fund.eastmoney.com/f10/lsjz"

_fund_nav_cache: TTLCache[str, dict[str, Any] | None] = TTLCache(maxsize=256, ttl=300.0)
_fund_hist_cache: TTLCache[str, dict[str, Any] | None] = TTLCache(maxsize=64, ttl=1800.0)


async def fund_nav(codes: list[str] | str) -> dict[str, Any]:
    """场外基金最新净值：{items:[{code,name,nav,acc_nav,change_pct,date,source}], missing:[...]}。

    走天天基金移动端公开接口（免登录）；失败的代码放进 missing，不编造价格。
    """
    if isinstance(codes, str):
        codes = [c for c in codes.replace("，", ",").split(",") if c.strip()]
    wanted = [str(c).strip() for c in codes if str(c).strip()][:50]
    if not wanted:
        return {"items": [], "missing": [], "source": "eastmoney_fund", "fetched_at": _now()}

    key = ",".join(wanted)
    cached = _fund_nav_cache.get(key)
    if cached is not None:
        return cached

    params = {
        "pageIndex": "1",
        "pageSize": str(len(wanted)),
        "plat": "Android",
        "appType": "ttjj",
        "product": "EFund",
        "Version": "1",
        "deviceid": "moneyhelper",
        "Fcodes": ",".join(wanted),
    }
    items: list[dict[str, Any]] = []
    try:
        async with _facade.httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(FUND_NAV_URL, params=params, headers={"User-Agent": _UA})
            resp.raise_for_status()
            payload = resp.json() or {}
        for row in payload.get("Datas") or []:
            if not isinstance(row, dict):
                continue
            code = str(row.get("FCODE") or "").strip()
            nav = _num(row.get("NAV"))
            if not code or nav is None:
                continue
            items.append(
                {
                    "code": code,
                    "name": str(row.get("SHORTNAME") or "").strip() or code,
                    "nav": nav,
                    "acc_nav": _num(row.get("ACCNAV")),
                    "change_pct": _num(row.get("NAVCHGRT")),
                    "date": str(row.get("PDATE") or "").strip(),
                    "source": "eastmoney_fund",
                }
            )
    except Exception:  # noqa: BLE001 — 外部行情失败只降级，不影响本地功能
        items = []

    got = {i["code"] for i in items}
    out = {
        "items": items,
        "missing": [c for c in wanted if c not in got],
        "source": "eastmoney_fund",
        "fetched_at": _now(),
        "note": "" if items else "基金净值接口暂时不可用（网络或对方限流）",
    }
    _fund_nav_cache[key] = out
    return out


async def fund_history(code: str, limit: int = 60) -> dict[str, Any] | None:
    """基金历史净值：{code, name, points:[{date,nav,acc_nav,change_pct}], source}。

    用于场外基金的走势曲线（个股走 quotes.kline，两者不混用）。
    """
    fund = str(code).strip()
    if not fund or not fund.isdigit():
        return None
    n = max(5, min(int(limit), 400))
    key = f"{fund}:{n}"
    cached = _fund_hist_cache.get(key)
    if cached is not None:
        return cached

    params = {"fundCode": fund, "pageIndex": "1", "pageSize": str(n)}
    headers = {"User-Agent": _UA, "Referer": "https://fundf10.eastmoney.com/"}
    try:
        async with _facade.httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(FUND_HISTORY_URL, params=params, headers=headers)
            resp.raise_for_status()
            payload = resp.json() or {}
    except Exception:  # noqa: BLE001
        return None

    rows = ((payload.get("Data") or {}).get("LSJZList")) or []
    points: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        d = str(r.get("FSRQ") or "").strip()
        nav = _num(r.get("DWJZ"))
        if not d or nav is None:
            continue
        points.append(
            {
                "date": d,
                "nav": nav,
                "acc_nav": _num(r.get("LJJZ")),
                "change_pct": _num(r.get("JZZZL")),
            }
        )
    if not points:
        return None
    points.sort(key=lambda p: p["date"])
    out = {
        "code": fund,
        "name": fund,
        "period": "daily",
        "points": points,
        "source": "eastmoney_fund",
        "fetched_at": _now(),
    }
    _fund_hist_cache[key] = out
    return out

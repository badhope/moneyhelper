"""公开行情数据源：基金净值 / 基金历史净值 / 市场涨跌榜 / 数据源可用性探测。

设计约束：
- 全部免登录、免密钥，只打官方或官方 CDN 域名；
- 每个函数失败返回 None / 空列表并给出可读原因，绝不抛错拖垮页面；
- 结果进 TTL 缓存，避免用户来回切页把对方站点打爆；
- 所有返回体带 `source` 字段，前端据此标注「这个是哪来的」。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx
from cachetools import TTLCache

_UA = "Mozilla/5.0 (moneyhelper connect-hub)"

FUND_NAV_URL = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNFInfo"
FUND_HISTORY_URL = "https://api.fund.eastmoney.com/f10/lsjz"
MOVERS_URL = "https://push2.eastmoney.com/api/qt/clist/get"
SINA_MOVERS_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeData"
)
SINA_HQ_URL = "https://hq.sinajs.cn/list="

_fund_nav_cache: TTLCache[str, dict[str, Any] | None] = TTLCache(maxsize=256, ttl=300.0)
_fund_hist_cache: TTLCache[str, dict[str, Any] | None] = TTLCache(maxsize=64, ttl=1800.0)
_movers_cache: TTLCache[str, list[dict[str, Any]]] = TTLCache(maxsize=8, ttl=60.0)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _num(raw: Any) -> float | None:
    try:
        v = float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # 过滤 NaN


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
        async with httpx.AsyncClient(timeout=6.0) as client:
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
        async with httpx.AsyncClient(timeout=6.0) as client:
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

    east = await _movers_eastmoney(kind, n)
    if east:
        _movers_cache[key] = east
        return {"items": east, "kind": kind, "source": "eastmoney", "fetched_at": _now(), "note": ""}

    sina = await _movers_sina(kind, n)
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
        async with httpx.AsyncClient(timeout=5.0) as client:
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
        async with httpx.AsyncClient(timeout=6.0) as client:
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


async def index_snapshot() -> dict[str, Any]:
    """四大指数快照（新浪源，东财 push2 在部分网络下不可达）。

    与 quotes.indices_quotes 的返回形状一致，供连接中心「行情直连」卡片使用。
    """
    codes = {
        "sh000001": "上证指数",
        "sz399001": "深证成指",
        "sz399006": "创业板指",
        "sh000300": "沪深300",
    }
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                SINA_HQ_URL + ",".join(codes),
                headers={"Referer": "https://finance.sina.com.cn", "User-Agent": _UA},
            )
            resp.raise_for_status()
            resp.encoding = "gbk"
            text = resp.text
    except Exception:  # noqa: BLE001
        return {"items": [], "source": "sina", "fetched_at": _now(), "note": "指数行情暂时不可用"}

    out = []
    for line in text.splitlines():
        if "=" not in line:
            continue
        head, _, body = line.partition("=")
        sym = head.replace("var hq_str_", "").strip()
        if sym not in codes:
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
                "name": codes[sym],
                "price": round(now, 2),
                "change": round(now - prev, 2),
                "change_pct": round((now / prev - 1) * 100, 2),
            }
        )
    return {
        "items": out,
        "source": "sina",
        "fetched_at": _now(),
        "note": "" if out else "指数行情暂时不可用",
    }


async def source_status() -> dict[str, Any]:
    """探测各公开数据源可用性（并发），供连接中心显示「通/断」。

    只做一次轻量请求，不重试；任一源失败不影响其他源。
    """
    checks = {
        "eastmoney_quote": index_snapshot(),
        "eastmoney_fund": fund_nav("110011"),
        "eastmoney_movers": market_movers("gainers", 3),
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

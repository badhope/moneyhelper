"""行情层：异步、可插拔、失败降级。

- snapshot：用组合库里的 `last` 快照价（零网络、可复现）。
- eastmoney：东方财富 push2 批量行情（免 key），httpx 异步请求，4s 超时。
- sina：新浪 hq.sinajs.cn 备源（需 Referer），东财不可用时自动切换。
- auto：优先东财，失败降级新浪，再降级快照。不做同步探测线程（旧实现会阻塞事件循环最长 16s）。
- kline()：东财 push2his 日/周/月 K 线（前复权），按需拉取 + 300s 缓存，失败返回 None。
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any

import httpx
from cachetools import TTLCache

from . import db

EASTMONEY_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
SINA_URL = "https://hq.sinajs.cn/list="

_UA = "Mozilla/5.0 (xiaoman)"
_SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": _UA,
}


def _to_secid(symbol: str) -> str | None:
    """A股/ETF/场内基金 → 东财 secid；现金与场外基金无法映射返回 None。"""
    s = symbol.strip().upper()
    if s == "CASH" or not s.isdigit() or len(s) != 6:
        return None
    if s[0] in "65":  # 沪市股票 / 沪市ETF(51/58)
        return f"1.{s}"
    if s[0] in "03":
        return f"0.{s}"
    if s.startswith(("15", "16")):  # 深市场内基金
        return f"0.{s}"
    return None


def _to_sina(symbol: str) -> str | None:
    """A股/ETF/场内基金 → 新浪代码（sh/sz 前缀）；现金与场外基金无法映射返回 None。"""
    s = symbol.strip().upper()
    if s == "CASH" or not s.isdigit() or len(s) != 6:
        return None
    if s[0] in "65":
        return f"sh{s}"
    if s[0] in "03":
        return f"sz{s}"
    if s.startswith(("15", "16")):
        return f"sz{s}"
    return None


def _parse_price(raw: Any) -> float | None:
    """价格解析：必须是正数（0 与负数视为无效，如盘前 0.000）。"""
    value = _num(raw)
    return value if value is not None and value > 0 else None


async def _eastmoney_quotes(symbols: list[str]) -> dict[str, float]:
    """东财批量行情；网络失败/缺价返回 {}，由调用方降级。"""
    code_to_symbol: dict[str, str] = {}
    secids: list[str] = []
    for s in symbols:
        sid = _to_secid(s)
        if sid:
            code_to_symbol[sid.split(".", 1)[1]] = s
            secids.append(sid)
    if not secids:
        return {}

    params = {
        "fltt": "2",
        "invt": "2",
        "fields": "f2,f12,f14",
        "secids": ",".join(secids),
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    }
    headers = {"User-Agent": "Mozilla/5.0 (xiaoman)"}
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(EASTMONEY_URL, params=params, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
    except Exception:  # noqa: BLE001 — 行情失败一律降级，绝不拖垮分析
        return {}

    diff = ((payload or {}).get("data") or {}).get("diff") or []
    if isinstance(diff, dict):
        diff = list(diff.values())
    out: dict[str, float] = {}
    for item in diff:
        if not isinstance(item, dict):
            continue
        sym = code_to_symbol.get(str(item.get("f12") or ""))
        if not sym:
            continue
        px = _parse_price(item.get("f2"))
        if px is not None:
            out[sym] = px
    return out


async def _sina_quotes(symbols: list[str]) -> dict[str, float]:
    """新浪行情备源：hq.sinajs.cn 批量现价（GBK 编码，需 Referer）。

    返回 {symbol: 现价}；网络失败/缺价返回 {}，由调用方继续降级。
    """
    codes = [_to_sina(s) for s in symbols]
    mapped: dict[str, str] = {}
    for s, c in zip(symbols, codes, strict=False):
        if c:
            mapped[c] = s
    if not mapped:
        return {}
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(SINA_URL + ",".join(mapped), headers=_SINA_HEADERS)
            resp.raise_for_status()
            text = resp.content.decode("gbk", errors="ignore")
    except Exception:  # noqa: BLE001 — 行情失败一律降级
        return {}
    out: dict[str, float] = {}
    for line in text.splitlines():
        # var hq_str_sh600000="浦发银行,今开,昨收,现价,...";
        m = re.match(r'var hq_str_([a-z]{2}\d{6})="([^"]*)"', line.strip())
        if not m:
            continue
        sym = mapped.get(m.group(1))
        if not sym:
            continue
        parts = m.group(2).split(",")
        if len(parts) < 4:
            continue
        px = _parse_price(parts[3])
        if px is not None:
            out[sym] = px
    return out


async def _sina_prev_close(symbols: list[str]) -> dict[str, float]:
    """新浪昨收（字段 2），供今日盈亏在备源下计算。失败返回 {}。"""
    codes = [_to_sina(s) for s in symbols]
    mapped: dict[str, str] = {}
    for s, c in zip(symbols, codes, strict=False):
        if c:
            mapped[c] = s
    if not mapped:
        return {}
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(SINA_URL + ",".join(mapped), headers=_SINA_HEADERS)
            resp.raise_for_status()
            text = resp.content.decode("gbk", errors="ignore")
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, float] = {}
    for line in text.splitlines():
        m = re.match(r'var hq_str_([a-z]{2}\d{6})="([^"]*)"', line.strip())
        if not m:
            continue
        sym = mapped.get(m.group(1))
        if not sym:
            continue
        parts = m.group(2).split(",")
        if len(parts) < 3:
            continue
        prev = _parse_price(parts[2])
        if prev is not None:
            out[sym] = prev
    return out


# 行情缓存：TTLCache 自动管理 TTL 过期与 LRU 淘汰，替代自建 dict + time.time() 比较
# maxsize 256 覆盖常规持仓组合数；ttl 30s 与行情源刷新频率一致
_live_cache = TTLCache[str, tuple[dict[str, float], str]](maxsize=256, ttl=30.0)
# 离网模式开关（ContextVar）：CLI / 脚本 / 离线场景用它强制走快照价，
# 而不必去改用户的持久化设置（那是给界面用的偏好，不该被一次性脚本改写）。
_offline: ContextVar[bool] = ContextVar("quotes_offline", default=False)


@contextmanager
def snapshot_only():
    """上下文管理器：期间所有行情取快照价，不发任何网络请求。

    用途：CLI 默认行为、离线自检、单元测试里不想 mock 的场合。
    """
    token = _offline.set(True)
    try:
        yield
    finally:
        _offline.reset(token)

_last_source = "snapshot"


def last_source() -> str:
    """最近一次取价实际生效的来源：eastmoney | sina | snapshot。"""
    return _last_source


def _snapshot(positions: list[dict[str, Any]]) -> dict[str, float]:
    return {p["symbol"]: float(p["last"]) for p in positions}


async def live_quotes(positions: list[dict[str, Any]]) -> dict[str, float]:
    """按设置取行情：auto/eastmoney → 东财（失败降级新浪 → 快照）；snapshot → 快照价。

    只对非现金标的请求实时价；现金直接用库里价格。
    每次调用都会更新 last_source()，供来源标注使用。
    """
    global _last_source
    if _offline.get():
        _last_source = "snapshot"
        return _snapshot(positions)
    mode = (await db.get_settings()).get("quote_source_mode", "auto")
    symbols = [p["symbol"] for p in positions if p["kind"] != "现金"]
    if mode == "snapshot" or not symbols:
        _last_source = "snapshot"
        return _snapshot(positions)

    key = ",".join(sorted(symbols))
    cached = _live_cache.get(key)
    if cached is not None:
        _last_source = cached[1]
        return cached[0]

    got = await _eastmoney_quotes(symbols)
    if got:
        _last_source = "eastmoney"
    else:
        got = await _sina_quotes(symbols)
        _last_source = "sina" if got else "snapshot"
        if not got:
            got = _snapshot(positions)
    _live_cache[key] = (got, _last_source)
    return got


# invalidate_quotes_cache 已移至文件末尾统一实现（见 _ALL_CACHES 注册表）


# ---------------------------------------------------------------------------
# 大盘指数（东财 push2 ulist，与个股行情同源同缓存策略）：
# 上证指数 / 深证成指 / 创业板指 / 沪深300，失败返回 []，由前端隐藏行情条。
# ---------------------------------------------------------------------------

# symbol → (东财 secid, 显示名)
INDICES: dict[str, tuple[str, str]] = {
    "sh000001": ("1.000001", "上证指数"),
    "sz399001": ("0.399001", "深证成指"),
    "sz399006": ("0.399006", "创业板指"),
    "sh000300": ("1.000300", "沪深300"),
}
_indices_cache = TTLCache[str, list[dict[str, Any]]](maxsize=1, ttl=30.0)


async def indices_quotes() -> list[dict[str, Any]]:
    """大盘指数快照：[{symbol, name, price, change, change_pct}]；失败返回 []。"""
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
    headers = {"User-Agent": "Mozilla/5.0 (xiaoman)"}
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(EASTMONEY_URL, params=params, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
    except Exception:  # noqa: BLE001 — 指数失败只隐藏行情条，不影响其他
        return []

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
    _indices_cache["v"] = out
    return out


# ---------------------------------------------------------------------------
# 今日盈亏（东财 f2 最新 / f18 昨收）：仅非现金且可映射的持仓，
# 失败/不可映射一律不参与，返回空则前端显示 "--"。
# ---------------------------------------------------------------------------

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
        headers = {"User-Agent": "Mozilla/5.0 (xiaoman)"}
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


# ---------------------------------------------------------------------------
# 单股实时报价（自选用）：东财优先，失败降级新浪；30s 缓存。
# ---------------------------------------------------------------------------

_quote_cache = TTLCache[str, dict[str, Any] | None](maxsize=128, ttl=30.0)

SINGLE_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"


async def quote_now(symbol: str) -> dict[str, Any] | None:
    """单只标的最新行情：{symbol, name, price, change, change_pct, source}；不可用返回 None。

    name 由调用方（自选库）提供后覆盖；这里只保证价格与涨跌。
    """
    key = symbol.strip().upper()
    cached = _quote_cache.get(key)
    if cached is not None:
        return cached

    out: dict[str, Any] | None = None
    secid = _to_secid(key)
    if secid:
        params = {
            "fltt": "2",
            "invt": "2",
            "fields": "f43,f44,f45,f46,f57,f58,f60,f169,f170",
            "secid": secid,
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        }
        headers = {"User-Agent": _UA}
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(SINGLE_QUOTE_URL, params=params, headers=headers)
                resp.raise_for_status()
                data = ((resp.json() or {}).get("data") or {})
            price = _parse_price(data.get("f43"))
            if price is not None:
                out = {
                    "symbol": key,
                    "name": data.get("f58") or "",
                    "price": price,
                    "change": _num(data.get("f169")),
                    "change_pct": _num(data.get("f170")),
                    "source": "eastmoney",
                }
        except Exception:  # noqa: BLE001 — 单股报价失败降级
            out = None

    if out is None:
        sina_code = _to_sina(key)
        if sina_code:
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    resp = await client.get(SINA_URL + sina_code, headers=_SINA_HEADERS)
                    resp.raise_for_status()
                    text = resp.content.decode("gbk", errors="ignore")
                m = re.search(rf'var hq_str_{re.escape(sina_code)}="([^"]*)"', text)
                if m:
                    parts = m.group(1).split(",")
                    if len(parts) >= 4:
                        price = _parse_price(parts[3])
                        prev = _parse_price(parts[2])
                        # 盘前/非交易时段现价为 0.000（_parse_price 判无效）：
                        # 用昨收兜底显示（涨跌 0），避免「无法获取行情」假失败
                        if price is None and prev is not None:
                            price = prev
                        if price is not None:
                            out = {
                                "symbol": key,
                                "name": parts[0],
                                "price": price,
                                "change": round(price - prev, 3) if prev is not None else None,
                                "change_pct": round((price - prev) / prev * 100, 2) if prev not in (None, 0) else 0.0,
                                "source": "sina",
                            }
            except Exception:  # noqa: BLE001
                out = None

    _quote_cache[key] = out
    return out


# ---------------------------------------------------------------------------
# K 线（东财 push2his）：日/周/月 K，前复权。失败一律返回 None，由调用方降级。
# ---------------------------------------------------------------------------

KLT = {"daily": 101, "weekly": 102, "monthly": 103}
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
# 回退：部分网络对 push2his 的 HTTPS 握手会被中间设备重置（实测 curl 正常、
# httpx TLS 被断），同一路径的 HTTP 端点仍可用。K 线是公开只读行情，HTTP 无泄密风险。
KLINE_URL_HTTP = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
_kline_cache = TTLCache[tuple[str, str, int], dict[str, Any]](maxsize=64, ttl=300.0)

# f51..f61 固定顺序：日期,开,收,高,低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
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


def _num(raw: Any) -> float | None:
    """数值解析：允许 0 与负数（涨跌额/涨跌幅需要负值），只排除缺失与占位符。

    不能复用 _parse_price：价格必须为正，但涨跌额/涨跌幅下跌时就是负数。
    """
    if raw is None or raw == "-" or raw == "" or isinstance(raw, bool):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


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
    headers = {"User-Agent": "Mozilla/5.0 (xiaoman)"}
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


async def kline(
    symbol: str, period: str = "daily", limit: int = 120
) -> dict[str, Any] | None:
    """取 K 线：{symbol, period, points, source}；不可用或失败一律 None。

    与实时行情同源（东财），但**不进总览请求**——只在用户点开某只标的时按需拉，
    300s 缓存，避免拖慢首屏。
    """
    secid = _to_secid(symbol)
    klt = KLT.get(period, KLT["daily"])
    if not secid:
        return None
    key = (secid, period, max(1, min(limit, 1000)))
    cached = _kline_cache.get(key)
    if cached is not None:
        return cached
    try:
        rows = await _fetch_kline(secid, klt, key[2])
    except Exception:  # noqa: BLE001 — K 线失败不影响任何其他功能
        return None
    points = _parse_kline_rows(rows)
    if not points:
        return None
    out: dict[str, Any] = {
        "symbol": symbol,
        "period": period,
        "points": points[-key[2] :],
        "source": "eastmoney",
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    _kline_cache[key] = out
    return out


# ---------------------------------------------------------------------------
# 统一缓存失效入口：所有 TTLCache 实例集中注册，失效只需调 invalidate_quotes_cache()
# ---------------------------------------------------------------------------
_ALL_CACHES: tuple[TTLCache[Any, Any], ...] = (
    _live_cache,
    _kline_cache,
    _indices_cache,
    _today_pnl_cache,
    _quote_cache,
)


async def invalidate_quotes_cache() -> None:
    for _c in _ALL_CACHES:
        _c.clear()


# ---------------------------------------------------------------------------
# 指数日线（基准对比用）：INDICES 里的 secid 直接复用，不走 _to_secid。
# 与个股 K 线共用同一份缓存与 HTTP→HTTPS 回退逻辑。
# ---------------------------------------------------------------------------


async def index_kline(symbol: str, limit: int = 750) -> dict[str, Any] | None:
    """基准指数日线。symbol 形如 sh000300（见 INDICES）。不可用返回 None。"""
    meta = INDICES.get(symbol)
    if not meta:
        return None
    secid = meta[0]
    key = (f"idx:{secid}", "daily", max(1, min(limit, 1000)))
    cached = _kline_cache.get(key)
    if cached is not None:
        return cached
    try:
        rows = await _fetch_kline(secid, KLT["daily"], key[2])
    except Exception:  # noqa: BLE001 — 基准失败只影响对比指标，不影响主流程
        return None
    points = _parse_kline_rows(rows)
    if not points:
        return None
    out: dict[str, Any] = {
        "symbol": symbol,
        "name": meta[1],
        "period": "daily",
        "points": points[-key[2] :],
        "source": "eastmoney",
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    _kline_cache[key] = out
    return out

"""行情源适配：东财批量报价与新浪备源的字段解析。

纯函数 + 请求常量，没有模块级可变状态；缓存、降级链与对外入口仍在 quotes.py。
`_num` 也放在这里——它在四类解析里共用（涨跌幅需要负数，不能用价格解析）。
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from . import symbols
from .numeric import to_float

EASTMONEY_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
SINA_URL = "https://hq.sinajs.cn/list="

_UA = "Mozilla/5.0 (moneyhelper)"
_SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": _UA,
}


_to_secid = symbols.to_secid
_to_sina = symbols.to_sina

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
    headers = {"User-Agent": "Mozilla/5.0 (moneyhelper)"}
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


async def _sina_fields(symbols: list[str], field: int) -> dict[str, float]:
    """新浪备源：一次性批量拉取，按 `field` 取某一列。

    新浪 `hq_str_*` 的返回是逗号分隔的定长字段表：
    `0 名称 / 1 今开 / 2 昨收 / 3 现价 / ...`。
    现价与昨收原本各写了一份「建映射 → 请求 → GBK 解码 → 正则拆行 → 取第 N 列」，
    只有列下标不同（3 vs 2）与长度下界（<4 vs <3）不同，后者还容易写成 off-by-one。
    合并后长度判断统一成 `len(parts) <= field`。

    返回 {symbol: 该列数值}；网络失败或缺字段的值跳过，由调用方继续降级。
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
    except Exception:  # noqa: BLE001 — 行情失败一律降级，绝不拖垮分析
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
        if len(parts) <= field:
            continue
        value = _parse_price(parts[field])
        if value is not None:
            out[sym] = value
    return out


async def _sina_quotes(symbols: list[str]) -> dict[str, float]:
    """新浪备源现价（字段 3）。"""
    return await _sina_fields(symbols, 3)


async def _sina_prev_close(symbols: list[str]) -> dict[str, float]:
    """新浪备源昨收（字段 2），供今日盈亏在备源下计算。"""
    return await _sina_fields(symbols, 2)


_num = to_float

"""东财 suggest（标的全名/代码搜索）—— 单一实现。

真实返回是顶层 {"QuotationCodeTable": {...}}；早期按 {"data": {...}} 取值，
导致搜索永远返回空列表。这个坑修过一次，但当时只修了 `/api/search` 路由，
Agent 工具 `search_symbol` 还留着自己那份旧解析，于是"网页能搜、对话搜不到"。
所以把请求与解析都收到这里，路由和工具共用一份。
"""

from __future__ import annotations

import os
from typing import Any

import httpx

_URL = "https://searchapi.eastmoney.com/api/suggest/get"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; moneyhelper)"}


async def fetch_suggest(keyword: str, timeout: float = 4.0) -> dict[str, Any]:
    """拉 suggest 原始响应；网络错误向上抛，由调用方决定降级文案。"""
    params = {
        "input": keyword,
        "type": "14",
        "token": os.getenv("EASTMONEY_SEARCH_TOKEN", "D43BF722C8E33BDC906FB84D85E326E8"),
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(_URL, params=params, headers=_HEADERS)
        resp.raise_for_status()
        return resp.json() or {}


def parse_suggest(body: dict[str, Any], limit: int = 8) -> list[dict[str, str]]:
    """解析 suggest 响应，兼容顶层与 data 包裹两种形态。"""
    table = (
        body.get("QuotationCodeTable")
        or (body.get("data") or {}).get("QuotationCodeTable")
        or {}
    )
    rows = table.get("Data") or []
    out: list[dict[str, str]] = []
    for r in rows[: max(1, min(limit, 20))]:
        code = str(r.get("Code") or "").strip()
        name = str(r.get("Name") or "").strip()
        if not code or not name:
            continue
        stype = str(r.get("SecurityTypeName") or "")
        kind = "基金" if "基金" in stype else ("指数" if "指" in stype else "股票")
        out.append({"symbol": code, "name": name, "kind": kind})
    return out

"""MCP 行情：搜索、报价、K 线、自选股工具。

从 mcp_server.py 拆出，import 即用 @_tool() 注册；mcp_server 末尾再导入本模块，
既触发注册也保留原有同名属性。
"""

from __future__ import annotations

from . import tools as xtools
from .logging_utils import get_logger
from .mcp_server import _tool

log = get_logger(__name__)

@_tool()
async def search_symbol(query: str) -> str:
    """搜索 A股/基金/指数（按代码或名称，如「茅台」「600519」）。"""
    return await xtools.tool_search_symbol({"query": query})


@_tool()
async def get_quote(symbol: str) -> str:
    """查询单只标的实时行情：现价、涨跌幅、来源（东财/新浪）。symbol 为 6 位代码如 600519。"""
    return await xtools.tool_get_quote({"symbol": symbol})


@_tool()
async def get_kline(symbol: str, period: str = "daily", limit: int = 60) -> str:
    """查询某标的的 K 线走势。symbol=6 位代码，period=daily/weekly/monthly，limit=返回点数（10-500）。"""
    return await xtools.tool_get_kline({"symbol": symbol, "period": period, "limit": limit})


@_tool()
async def add_to_watchlist(symbol: str, name: str = "", kind: str = "股票") -> str:
    """把标的加入自选。name 省略时自动从实时行情获取名称。"""
    return await xtools.tool_add_watchlist({"symbol": symbol, "name": name, "kind": kind})


@_tool()
async def remove_from_watchlist(symbol: str) -> str:
    """自选列表移除标的。"""
    return await xtools.tool_remove_watchlist({"symbol": symbol})


@_tool()
async def get_watchlist() -> str:
    """查询自选列表及其实时行情。"""
    return await xtools.tool_get_watchlist({})

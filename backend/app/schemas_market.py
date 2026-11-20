"""行情与自选股：K 线、搜索、报价、自选增删、市场广度与个股画像。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .tool_schemas import _In


class GetKlineIn(_In):
    symbol: str = Field(..., description="6位证券代码，如 600519")
    period: Literal["daily", "weekly", "monthly"] = Field(
        "daily", description="K 线周期：daily / weekly / monthly，默认 daily"
    )
    limit: int = Field(0, description="返回点数，默认 60")

class SearchSymbolIn(_In):
    query: str = Field(..., description="搜索关键词，代码或名称")

class GetQuoteIn(_In):
    symbol: str = Field(..., description="6 位代码，如 600519")

class AddToWatchlistIn(_In):
    symbol: str = Field(..., description="6 位代码")
    name: str = Field("", description="标的名称（可省略，自动获取）")
    kind: str = Field("", description="股票/基金/指数")

class RemoveFromWatchlistIn(_In):
    symbol: str = Field(..., description="6 位代码")

class GetWatchlistIn(_In):
    """查自选列表及实时行情。"""

class MarketBreadthIn(_In):
    pass

class StockProfileIn(_In):
    symbol: str = Field(..., description="6 位证券代码，如 600519")


MODELS: dict[str, type[BaseModel]] = {
    "get_kline": GetKlineIn,
    "search_symbol": SearchSymbolIn,
    "get_quote": GetQuoteIn,
    "add_to_watchlist": AddToWatchlistIn,
    "remove_from_watchlist": RemoveFromWatchlistIn,
    "get_watchlist": GetWatchlistIn,
    "market_breadth": MarketBreadthIn,
    "stock_profile": StockProfileIn,
}

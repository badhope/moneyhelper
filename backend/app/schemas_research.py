"""投研与模拟盘：分析/回测/预测/财报解读、团队模拟盘开仓与交易。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .tool_schemas import _In


class ResearchAnalyzeIn(_In):
    symbol: str = Field(..., description="6位证券代码，如 600519")
    period: Literal["daily", "weekly", "monthly"] = Field(
        "daily", description="K 线周期：daily / weekly / monthly，默认 daily"
    )
    limit: int = Field(0, description="取数根数，默认 180")

class ResearchBacktestIn(_In):
    symbol: str = Field(..., description="6位证券代码，如 600519")
    strategy: Literal["ma_cross", "dca"] = Field(
        "ma_cross", description="回测策略：ma_cross 双均线 / dca 定投"
    )
    fast: int = Field(0, description="快线周期（ma_cross），默认 5")
    slow: int = Field(0, description="慢线周期（ma_cross），默认 20")
    invest_amount: float = Field(0, description="每期定投金额（dca），默认 1000")
    freq_days: int = Field(0, description="定投间隔交易日（dca），默认 5")

class StatementsAnalyzeIn(_In):
    payload: dict[str, Any] = Field(
        ...,
        description="标准化三表 JSON：{company, currency, periods:[{period, balance_sheet, income_statement, cashflow_statement}]}",
    )

class ResearchForecastIn(_In):
    symbol: str = Field(..., description="6位证券代码，如 600519")
    period: Literal["daily", "weekly", "monthly"] = Field(
        "daily", description="K 线周期：daily / weekly / monthly，默认 daily"
    )
    days: int = Field(0, description="预测未来根数，默认 20，范围 1-60")

class PaperOpenIn(_In):
    name: str = Field("模拟账户", description="账户名（成员昵称），默认 模拟账户")
    initial_cash: float = Field(0, description="初始虚拟资金，默认 100000，最小 1000")

class PaperTradeIn(_In):
    account_id: str = Field(..., description="模拟账户 ID（paper_overview 可查）")
    symbol: str = Field(..., description="6位证券代码，如 600519")
    side: Literal["buy", "sell"] = Field(..., description="buy 买入 / sell 卖出")
    price: float = Field(..., description="成交价（可填现价）")
    shares: float = Field(..., description="股数；买入必须 100 股整数倍，卖出可零股")

class PaperOverviewIn(_In):
    pass


MODELS: dict[str, type[BaseModel]] = {
    "research_analyze": ResearchAnalyzeIn,
    "research_backtest": ResearchBacktestIn,
    "statements_analyze": StatementsAnalyzeIn,
    "research_forecast": ResearchForecastIn,
    "paper_open": PaperOpenIn,
    "paper_trade": PaperTradeIn,
    "paper_overview": PaperOverviewIn,
}

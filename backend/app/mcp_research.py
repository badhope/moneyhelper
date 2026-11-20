"""MCP 研究、报表分析与模拟盘工具。

从 mcp_server.py 拆出，import 即用 @_tool() 注册；mcp_server 末尾再导入本模块，
既触发注册也保留原有同名属性。
"""

from __future__ import annotations

from . import tools as xtools
from .logging_utils import get_logger
from .mcp_server import _tool

log = get_logger(__name__)

@_tool()
async def web_search(q: str) -> str:
    """联网搜索（免 key，Bing 接口，国内可达）。q 为搜索关键词。"""
    return await xtools.tool_web_search({"q": q})


# ---------------------------------------------------------------------------
# 投研 / 财报工具（v4.0：确定性技术面 + 回测 + 三表分析）
# ---------------------------------------------------------------------------


@_tool()
async def research_analyze(symbol: str, period: str = "daily", limit: int = 180) -> str:
    """股票技术面研报：MA/MACD/RSI/BOLL/KDJ 指标快照 + 规则信号 + 多空倾向 + 文字结论。symbol 为 6 位代码，period 可选 daily/weekly/monthly。"""
    return await xtools.tool_research_analyze(
        {"symbol": symbol, "period": period, "limit": limit}
    )


@_tool()
async def research_backtest(
    symbol: str,
    strategy: str = "ma_cross",
    fast: int = 5,
    slow: int = 20,
    invest_amount: float = 1000.0,
    freq_days: int = 5,
) -> str:
    """策略历史回测：ma_cross（双均线）或 dca（定投），输出收益/年化/最大回撤/夏普/胜率/盈亏比。symbol 为 6 位代码。"""
    return await xtools.tool_research_backtest(
        {
            "symbol": symbol,
            "strategy": strategy,
            "fast": fast,
            "slow": slow,
            "invest_amount": invest_amount,
            "freq_days": freq_days,
        }
    )


@_tool()
async def statements_analyze(payload: dict) -> str:
    """财报分析：输入标准化三表 JSON（{company, currency, periods:[{period, balance_sheet, income_statement, cashflow_statement}]}），输出 20+ 指标、杜邦拆解、异常预警与文字报告。"""
    return await xtools.tool_statements_analyze({"payload": payload})


@_tool()
async def research_forecast(symbol: str, period: str = "daily", days: int = 20) -> str:
    """价格统计预测：线性趋势 + 年化波动率 + 蒙特卡洛 GBM 分位区间（固定种子可复现）。symbol 为 6 位代码，days 为预测根数。"""
    return await xtools.tool_research_forecast({"symbol": symbol, "period": period, "days": days})


# ---------------------------------------------------------------------------
# 团队模拟盘工具（v4.2：事件溯源式虚拟账户）
# ---------------------------------------------------------------------------


@_tool()
async def paper_open(name: str = "模拟账户", initial_cash: float = 100000.0) -> str:
    """团队模拟盘开户：为成员创建虚拟账户（独立初始资金，最小 1000）。"""
    return await xtools.tool_paper_open({"name": name, "initial_cash": initial_cash})


@_tool()
async def paper_trade(account_id: str, symbol: str, side: str, price: float, shares: float) -> str:
    """团队模拟盘下单：买入/卖出虚拟持仓（A股整手、含佣金与印花税）。side 为 buy/sell。"""
    return await xtools.tool_paper_trade(
        {"account_id": account_id, "symbol": symbol, "side": side, "price": price, "shares": shares}
    )


@_tool()
async def paper_overview() -> str:
    """团队模拟盘总览：账户收益率排行、团队汇总、持仓摘要。"""
    return await xtools.tool_paper_overview({})

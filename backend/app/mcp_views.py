"""MCP 只读视图：市场/账本/风险/预算/趋势/目标/健康度/组合风险/再平衡/估值/定投/FIRE。

从 mcp_server.py 拆出，import 即用 @_tool() 注册；mcp_server 末尾再导入本模块，
既触发注册也保留原有同名属性。
"""

from __future__ import annotations

from . import tools as xtools
from .logging_utils import get_logger
from .mcp_server import _tool

log = get_logger(__name__)

@_tool()
async def get_market_view() -> str:
    """查询用户持仓组合：总市值、累计盈亏、前几大持仓、集中度告警。"""
    return await xtools.tool_get_market_view({})


@_tool()
async def get_ledger_view() -> str:
    """查询用户账本：本月收入、支出、结余、储蓄率、支出分类、订阅、负债、应急金。"""
    return await xtools.tool_get_ledger_view({})


@_tool()
async def get_risk_flags() -> str:
    """运行风控规则：集中度超限、应急金不足、高息负债、负债收入比偏高、储蓄率偏低等告警。"""
    return await xtools.tool_get_risk_flags({})


@_tool()
async def get_budget(month: str = "") -> str:
    """查询预算设置与实时使用情况。month 格式 YYYY-MM，省略=本月。"""
    return await xtools.tool_get_budget({"month": month})


@_tool()
async def get_trend(months: int = 6) -> str:
    """查询近几个月收支趋势。months 范围 1-24，默认 6。"""
    return await xtools.tool_get_trend({"months": months})


@_tool()
async def get_financial_identity() -> str:
    """财务数字身份证：财务坐标、数据覆盖、风险与异常、权限边界、数据来源。无参数。"""
    return await xtools.tool_get_financial_identity({})


@_tool()
async def get_monthly_review(month: str = "") -> str:
    """月度结账复盘：某月收支、预算、异常、数据体检与下月动作。month 格式 YYYY-MM，省略=本月。"""
    return await xtools.tool_get_monthly_review({"month": month})


@_tool()
async def get_goals() -> str:
    """查询用户的财务目标：目标金额、已存金额、进度百分比、距截止月、建议月存。"""
    return await xtools.tool_get_goals({})


@_tool()
async def get_health_check() -> str:
    """跑一次结构化财务体检：资产配置 / 现金流 / 负债 / 应急金 / 目标进度 五个维度评分与建议。"""
    return await xtools.tool_get_health_check({})


# ---------------------------------------------------------------------------
# 投资策略工具（与 LLM function calling 同源，数字由确定性引擎算出）
# ---------------------------------------------------------------------------


@_tool()
async def get_portfolio_risk(benchmark: str = "sh000300") -> str:
    """组合风险指标：年化波动率、夏普、索提诺、最大回撤、Calmar、Beta/Alpha、VaR，并与基准对比。benchmark 可选 sh000300/sh000001/sz399001/sz399006。"""
    return await xtools.tool_get_portfolio_risk({"benchmark": benchmark})


@_tool()
async def get_rebalance_plan(band_pct: float = 5.0) -> str:
    """再平衡建议：对照目标配置给出偏离度与应买/应卖金额、约多少股。band_pct 为容忍带百分比。"""
    return await xtools.tool_get_rebalance_plan({"band_pct": band_pct})


@_tool()
async def get_valuation(symbols: str = "") -> str:
    """估值位置分位：当前价在近 750 个交易日区间中的位置（0=最低，100=最高）。symbols 为逗号分隔代码，省略=全部持仓。"""
    return await xtools.tool_get_valuation({"symbols": symbols})


@_tool()
async def get_dca_plans() -> str:
    """定投计划与回测：每期金额、累计投入、份额、成本线、当前盈亏、下一期扣款日。"""
    return await xtools.tool_get_dca_plans({})


@_tool()
async def get_fire_plan() -> str:
    """FIRE 进度：目标本金、当前完成度、储蓄率、按复利估算的达成年限。"""
    return await xtools.tool_get_fire_plan({})

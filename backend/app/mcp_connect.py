"""MCP 连接器、税务、现金流与扫描类工具。

从 mcp_server.py 拆出，import 即用 @_tool() 注册；mcp_server 末尾再导入本模块，
既触发注册也保留原有同名属性。
"""

from __future__ import annotations

from . import tools as xtools
from .logging_utils import get_logger
from .mcp_server import _tool

log = get_logger(__name__)

@_tool()
async def connect_catalog() -> str:
    """连接中心目录：支持哪些外部平台（行情/券商/银行/支付/发票/公司财税）、接入方式与当前连接状态。"""
    return await xtools.tool_connect_catalog({})


@_tool()
async def connect_sync(
    connector_id: str,
    label: str = "",
    account_ref: str = "",
    sync: bool = True,
) -> str:
    """建立/刷新一个外部连接：公开源立即拉数据；登录类返回官方入口与一次性配对码。"""
    return await xtools.tool_connect_sync(
        {"connector_id": connector_id, "label": label, "account_ref": account_ref, "sync": sync}
    )


@_tool()
async def connect_fund_nav(codes: str) -> str:
    """查场外基金最新净值（公开接口免登录），多个代码逗号分隔。"""
    return await xtools.tool_connect_fund_nav({"codes": codes})


@_tool()
async def connect_order(
    symbol: str,
    side: str,
    price: float,
    shares: float,
    mode: str = "paper",
    name: str = "",
    connector_id: str = "",
    execute: bool = False,
) -> str:
    """生成交易指令：paper=模拟盘（可立即成交），live=只出交接单由用户在券商页面下单。"""
    return await xtools.tool_connect_order(
        {
            "symbol": symbol,
            "side": side,
            "price": price,
            "shares": shares,
            "mode": mode,
            "name": name,
            "connector_id": connector_id,
            "execute": execute,
        }
    )

# ---------------------------------------------------------------------------
# v4.5 深化：财税 / 现金流 / 风控 / 对账 / 发票 / 市场温度 / 条件单
# ---------------------------------------------------------------------------


@_tool()
async def tax_calc(kind: str = "summary", revenue: float = 0, sales: float = 0, cost: float = 0,
                   purchases: float = 0, expenses: float = 0, vat_rate: float = 0.13,
                   vat_simple: bool = False, location: str = "city", cit_category: str = "standard",
                   monthly_salary: float = 0, gross_salary: float = 0, months: int = 1,
                   social_insurance: float = 0, housing_fund: float = 0,
                   special_additional: float = 0, payroll_gross: float = 0) -> str:
    """税负测算：vat 增值税 / cit 企业所得税 / iit 个税 / payroll 工资 / summary 综合税负。"""
    return await xtools.tool_tax_calc({
        "kind": kind, "revenue": revenue, "sales": sales, "cost": cost, "purchases": purchases,
        "expenses": expenses, "vat_rate": vat_rate, "vat_simple": vat_simple, "location": location,
        "cit_category": cit_category, "monthly_salary": monthly_salary, "gross_salary": gross_salary,
        "months": months, "social_insurance": social_insurance, "housing_fund": housing_fund,
        "special_additional": special_additional, "payroll_gross": payroll_gross,
    })


@_tool()
async def cashflow_forecast(months_ahead: int = 3, opening_balance: float = 0) -> str:
    """现金流三档预测（悲观/中性/乐观），基于真实流水的月度净流入分布。"""
    return await xtools.tool_cashflow_forecast({"months_ahead": months_ahead, "opening_balance": opening_balance})


@_tool()
async def scan_subscriptions() -> str:
    """识别订阅扣款：周期、金额、下次扣款日、涨价标记。"""
    return await xtools.tool_scan_subscriptions({})


@_tool()
async def scan_anomalies(lookback_days: int = 180) -> str:
    """异常扣款检测：中位数 + MAD 判离群，输出异常倍数与建议。"""
    return await xtools.tool_scan_anomalies({"lookback_days": lookback_days})


@_tool()
async def debt_payoff_plan(
    extra_payment: float = 0,
    method: str = "avalanche",
    compare: bool = False,
) -> str:
    """债务清偿规划：逐月摊还模拟，给出还清顺序、月数、总利息与可省利息。

    method: avalanche（按利率从高到低，省利息最多）/ snowball（按余额从小到大）。
    compare=true 同时返回两种方法的对比。数据来自账本已有负债记录。
    """
    return await xtools.tool_debt_payoff_plan(
        {"extra_payment": extra_payment, "method": method, "compare": compare}
    )


@_tool()
async def pretrade_check(symbol: str, side: str, price: float, shares: float) -> str:
    """下单前风控：涨跌停/整手/T+1/集中度/日限额/重复单。"""
    return await xtools.tool_pretrade_check({"symbol": symbol, "side": side, "price": price, "shares": shares})


@_tool()
async def import_brokerage_holdings(content: str, apply: bool = False, file_name: str = "holdings.csv") -> str:
    """导入券商持仓对账单 CSV：预览或直接合并进持仓。"""
    return await xtools.tool_import_brokerage_holdings({"content": content, "apply": apply, "file_name": file_name})


@_tool()
async def parse_invoice(text: str, file_name: str = "invoice-text") -> str:
    """解析并归档发票票面文本：代码/号码/日期/价税合计/购销方。"""
    return await xtools.tool_parse_invoice({"text": text, "file_name": file_name})


@_tool()
async def market_breadth() -> str:
    """市场温度：涨跌家数、涨跌停数量、情绪温度 0-100。"""
    return await xtools.tool_market_breadth({})


@_tool()
async def stock_profile(symbol: str) -> str:
    """个股档案：PE/PB、市值、换手率、量比、振幅、涨跌停价。"""
    return await xtools.tool_stock_profile({"symbol": symbol})


@_tool()
async def conditional_order(symbol: str, side: str, trigger_type: str, trigger_value: float,
                            price: float, shares: float, mode: str = "paper", name: str = "") -> str:
    """创建条件单：触发后生成待确认交易意图，不直接下单。"""
    return await xtools.tool_conditional_order({
        "symbol": symbol, "side": side, "trigger_type": trigger_type,
        "trigger_value": trigger_value, "price": price, "shares": shares,
        "mode": mode, "name": name,
    })

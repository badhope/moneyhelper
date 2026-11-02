"""工具入参的 pydantic 模型 —— schema 的单一真源（M2.1）。

## 为什么需要这一层

改造前同一份工具定义存在两处，各自手写：
- `tools.py` 里 22 个 OpenAI function calling 的 JSON Schema 字面量
- `mcp_server.py` 里 30 个 MCP 工具的函数签名 + 文档字符串

两份已经漂移：MCP 多出 8 个工具（净值/健康/收益/目标进度/导入/家庭/审计），
`tools.py` 里的 `get_lessons`、`set_setting` 则没有 MCP 对应。改一个参数要
同步改两处，漏改的结果是"模型看到的参数"和"MCP 客户端看到的参数"不一致。

现在只在这里定义一次，两侧都从 `model_json_schema()` 派生：

    OpenAI function calling:  {"type":"function","function":{"parameters": <schema>}}
    MCP inputSchema:          <schema>

## 约定

- 所有模型 `extra="forbid"` → 产出 `additionalProperties: false`，
  模型多传参数时会被拒绝，而不是被静默忽略。
- 字段描述写清"省略时是什么行为"，这是模型决定传不传参数的唯一依据。
- 可选参数的默认值用空串/0 表达（与既有实现一致），不使用 Optional：
  下游工具函数统一用 `args.get(...) or 默认值`，空串等价于未传。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

# ---------------------------------------------------------------------------
# 公共基类
# ---------------------------------------------------------------------------


class _In(BaseModel):
    """所有工具入参的基类：禁止多余字段（产出 additionalProperties: false）。"""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# 财务查询（无参数）
# ---------------------------------------------------------------------------


class GetMarketViewIn(_In):
    """查持仓与行情：总市值、盈亏、集中度。"""


class GetLedgerViewIn(_In):
    """查账本：本月收支、结余、储蓄率、订阅、负债、应急金。"""


class GetRiskFlagsIn(_In):
    """运行风控规则：集中度/应急金/高息负债/负债收入比/储蓄率。"""


class GetGoalsIn(_In):
    """查财务目标：目标金额、已存、进度、建议月存。"""


class GetLessonsIn(_In):
    """查经验库：历史工具调用踩坑记录。"""


class GetHealthCheckIn(_In):
    """结构化财务体检：五维度评分与建议。"""


class GetWatchlistIn(_In):
    """查自选列表及实时行情。"""


class TriggerMorningReportIn(_In):
    """立即生成今日晨报。"""

    lang: str = Field("", description="输出语言 zh/en，可省略（默认 zh）")


class BackupNowIn(_In):
    """生成本地加密备份包。"""

    lang: str = Field("", description="输出语言 zh/en，可省略（默认 zh）")


# ---------------------------------------------------------------------------
# 财务查询（带参数）
# ---------------------------------------------------------------------------


class GetBudgetIn(_In):
    month: str = Field("", description="月份 YYYY-MM，可省略（默认本月）")


class GetTrendIn(_In):
    months: int = Field(0, description="月份数 1-24，默认 6")


class GetKlineIn(_In):
    symbol: str = Field(..., description="6位证券代码，如 600519")
    period: Literal["daily", "weekly", "monthly"] = Field(
        "daily", description="K 线周期：daily / weekly / monthly，默认 daily"
    )
    limit: int = Field(0, description="返回点数，默认 60")


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


class ResearchForecastIn(_In):
    symbol: str = Field(..., description="6位证券代码，如 600519")
    period: Literal["daily", "weekly", "monthly"] = Field(
        "daily", description="K 线周期：daily / weekly / monthly，默认 daily"
    )
    days: int = Field(0, description="预测未来根数，默认 20，范围 1-60")


class StatementsAnalyzeIn(_In):
    payload: dict[str, Any] = Field(
        ...,
        description="标准化三表 JSON：{company, currency, periods:[{period, balance_sheet, income_statement, cashflow_statement}]}",
    )


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


class ConnectCatalogIn(_In):
    """查连接中心目录：外部平台接入方式、已建连接与状态。"""


class ConnectSyncIn(_In):
    connector_id: str = Field(..., description="连接器 ID，如 alipay / cmb / eastmoney_fund（先用 connect_catalog 查）")
    label: str = Field("", description="连接标签，默认用连接器名；同平台多账户时用于区分")
    account_ref: str = Field("", description="账号后四位等辨识信息（可选，勿填完整卡号）")
    sync: bool = Field(True, description="建好连接后是否立即同步一次，默认 true")


class ConnectFundNavIn(_In):
    codes: str = Field(..., description="基金代码，多个用逗号分隔，如 110011,000001")


class ConnectOrderIn(_In):
    symbol: str = Field(..., description="6位证券代码，如 600519")
    side: Literal["buy", "sell"] = Field(..., description="buy 买入 / sell 卖出")
    price: float = Field(..., description="委托价（可填现价）")
    shares: float = Field(..., description="股数；买入须 100 股整数倍")
    mode: Literal["paper", "live"] = Field(
        "paper", description="paper 模拟盘直接成交；live 只生成交接单，用户在券商页面自行下单"
    )
    name: str = Field("", description="标的名称（可选）")
    connector_id: str = Field("", description="交易通道 ID（可选，实盘时填券商连接器，如 eastmoney_sec）")
    execute: bool = Field(
        False, description="是否立即执行：paper 且 execute=true 时直接写入模拟盘；实盘永远只生成交接单"
    )


class TaxCalcIn(_In):
    kind: Literal["vat", "cit", "iit", "payroll", "summary"] = Field(
        "summary", description="vat 增值税 / cit 企业所得税 / iit 个税 / payroll 工资 / summary 综合税负"
    )
    revenue: float = Field(0, description="收入（不含税），summary/cit 用")
    sales: float = Field(0, description="销售额（不含税），vat 用；未填时取 revenue")
    cost: float = Field(0, description="成本（不含税）")
    purchases: float = Field(0, description="采购额（不含税），vat 进项用；未填时取 cost")
    expenses: float = Field(0, description="期间费用")
    vat_rate: float = Field(0.13, description="增值税税率：0.13/0.09/0.06/0")
    vat_simple: bool = Field(False, description="是否简易计税")
    location: str = Field("city", description="城建税地区：city 7% / county 5% / other 1%")
    cit_category: str = Field("standard", description="standard 25% / high_tech 15% / small_micro 5%")
    monthly_salary: float = Field(0, description="月薪（iit/payroll 用）")
    gross_salary: float = Field(0, description="月应发工资（payroll 用；未填时取 monthly_salary）")
    months: int = Field(1, description="累计月数（iit 累计预扣 / payroll 累计）")
    social_insurance: float = Field(0, description="个人三险合计（月）")
    housing_fund: float = Field(0, description="个人公积金（月）")
    special_additional: float = Field(0, description="专项附加扣除（月）")
    payroll_gross: float = Field(0, description="月工资总额（summary 估人工成本）")


class CashflowForecastIn(_In):
    months_ahead: int = Field(3, description="预测月数 1-12")
    opening_balance: float = Field(0, description="期初余额；0 表示用账本现金资产估算")


class SubscriptionScanIn(_In):
    pass


class AnomalyScanIn(_In):
    lookback_days: int = Field(180, description="回看天数 30-730")


class PretradeCheckIn(_In):
    symbol: str = Field(..., description="6 位证券代码")
    side: Literal["buy", "sell"] = Field(..., description="buy / sell")
    price: float = Field(..., description="委托价")
    shares: float = Field(..., description="委托股数")


class HoldingsImportIn(_In):
    content: str = Field(..., description="券商导出的持仓 CSV 全文")
    apply: bool = Field(False, description="true 时合并进持仓表；false 只预览")
    file_name: str = Field("holdings.csv", description="文件名（用于导入记录）")


class InvoiceParseIn(_In):
    text: str = Field(..., description="发票票面文本（OFD/PDF 请走上传接口）")
    file_name: str = Field("invoice-text", description="文件名（用于归档记录）")


class MarketBreadthIn(_In):
    pass


class StockProfileIn(_In):
    symbol: str = Field(..., description="6 位证券代码，如 600519")


class ConditionalOrderIn(_In):
    symbol: str = Field(..., description="6 位证券代码")
    side: Literal["buy", "sell"] = Field(..., description="buy / sell")
    trigger_type: Literal["price_below", "price_above", "pct_change_below", "pct_change_above"] = Field(
        "price_below", description="触发条件类型"
    )
    trigger_value: float = Field(..., description="触发值：价格或涨跌幅百分数")
    price: float = Field(..., description="触发后的委托价")
    shares: float = Field(..., description="股数")
    mode: Literal["paper", "live"] = Field("paper", description="paper 模拟盘 / live 实盘交接")
    name: str = Field("", description="标的名称（可选）")


class CategorizeIn(_In):
    rows: list[dict] = Field(..., description="交易数组，每项含 item（摘要）、可选 peer/category、amount")


class PdfStatementIn(_In):
    pass


class BrokerStatusIn(_In):
    pass


class BrokerPreviewIn(_In):
    symbol: str = Field(..., description="6 位证券代码")
    side: Literal["buy", "sell"] = Field(..., description="buy / sell")
    quantity: int = Field(..., description="股数；买入须 100 股整数倍")
    limit_price: float = Field(..., description="限价")


class BrokerSubmitIn(_In):
    symbol: str = Field(..., description="6 位证券代码")
    side: Literal["buy", "sell"] = Field(..., description="buy / sell")
    quantity: int = Field(..., description="股数")
    limit_price: float = Field(..., description="限价")
    confirmation_token: str = Field("", description="preview 返回的确认令牌；dry_run 模式可空")


class InvoiceVisionIn(_In):
    pass


class GetUserMemoryIn(_In):
    query: str = Field("", description="检索关键词（可选）：返回与该话题相关的记忆")
    kind: str = Field(
        "", description="按类型过滤（可选）：fact / preference / goal_related"
    )


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


# ---------------------------------------------------------------------------
# 财务写入
# ---------------------------------------------------------------------------


class RecordTransactionIn(_In):
    text: str = Field(..., description="用户原话")


class SaveUserMemoryIn(_In):
    content: str = Field(..., description="要记住的内容（一句话，含具体事实）")


class RecordPositionIn(_In):
    symbol: str = Field(..., description="6 位代码")
    name: str = Field("", description="名称（可省略，自动获取）")
    kind: str = Field("", description="股票/基金/ETF")
    shares: float = Field(..., description="份额/股数")
    cost: float = Field(..., description="成本价（买入价）")
    last: float = Field(0, description="现价（可省略，自动获取）")
    buy_date: str = Field("", description="买入日期 YYYY-MM-DD，可省略默认今天")
    industry: str = Field("", description="行业分类（可省略，默认其他）")


class SellPositionIn(_In):
    symbol: str = Field(..., description="6 位代码")
    shares: float = Field(0, description="卖出份额/股数（省略=清仓全部）")


class SetSettingIn(_In):
    key: str = Field(..., description="设置键名，见工具描述")
    value: str = Field(..., description="设置值，见工具描述")


# ---------------------------------------------------------------------------
# 通用（领域无关）
# ---------------------------------------------------------------------------


class GetNowIn(_In):
    """查当前日期与时间。"""


class WebSearchIn(_In):
    q: str = Field(..., description="搜索关键词")


# ---------------------------------------------------------------------------
# MCP 专属工具（不在 LLM function calling 工具集里，仅对外暴露给 MCP 客户端）
# ---------------------------------------------------------------------------


class GetNetWorthIn(_In):
    """查净值：总资产、总负债、净值与明细。"""


class GetFinancialHealthIn(_In):
    """查财务健康评分（0-100）与五维度拆解。"""


class GetReturnsIn(_In):
    months: int = Field(0, description="统计月数，可省略（默认 6）")


class GetGoalProgressIn(_In):
    """查全部财务目标进度。"""


class ImportTransactionsIn(_In):
    source: str = Field(..., description="账单来源：generic / wechat / alipay")
    csv_text: str = Field(..., description="CSV 文本内容")


class GetFamilySummaryIn(_In):
    """查家庭整体汇总（收支、成员占比、未结清借贷）。"""


class GetProvenanceIn(_In):
    entity_type: str = Field("", description="按实体类型过滤（可选）")
    entity_id: str = Field("", description="按实体 ID 过滤（可选）")
    limit: int = Field(0, description="返回条数上限，可省略（默认 20，最大 200）")


# ---------------------------------------------------------------------------
# 投资策略（LLM 可调用：回答"我的组合风险大吗/该调仓吗/现在贵吗"）
# ---------------------------------------------------------------------------


class GetPortfolioRiskIn(_In):
    """查组合风险：波动率、夏普、索提诺、最大回撤、Beta、与基准对比。"""

    benchmark: str = Field(
        "", description="基准指数代码 sh000300/sh000001/sz399001/sz399006，可省略（默认沪深300）"
    )


class GetRebalancePlanIn(_In):
    """查再平衡建议：目标配置偏离度与买卖清单。"""

    band_pct: float = Field(0, description="容忍带百分比，偏差在带内不动；可省略（默认 5）")


class GetValuationIn(_In):
    """查估值位置分位：当前价在近 N 个交易日区间中的位置（0=区间最低，100=最高）。"""

    symbols: str = Field("", description="逗号分隔的标的代码，可省略（默认全部非现金持仓）")


class GetDcaPlansIn(_In):
    """查定投计划：每期金额、累计投入、成本线、当前盈亏。"""


class GetFirePlanIn(_In):
    """查 FIRE 进度：目标本金、储蓄率、预计达成年限。"""


# ---------------------------------------------------------------------------
# 工具名 → 入参模型
# ---------------------------------------------------------------------------

TOOL_INPUT_MODELS: dict[str, type[BaseModel]] = {
    # 财务查询
    "get_market_view": GetMarketViewIn,
    "get_ledger_view": GetLedgerViewIn,
    "get_risk_flags": GetRiskFlagsIn,
    "get_budget": GetBudgetIn,
    "get_trend": GetTrendIn,
    "get_kline": GetKlineIn,
    "get_goals": GetGoalsIn,
    "get_user_memory": GetUserMemoryIn,
    "get_lessons": GetLessonsIn,
    "get_health_check": GetHealthCheckIn,
    "get_watchlist": GetWatchlistIn,
    "search_symbol": SearchSymbolIn,
    "get_quote": GetQuoteIn,
    "add_to_watchlist": AddToWatchlistIn,
    "remove_from_watchlist": RemoveFromWatchlistIn,
    # 投资策略
    "get_portfolio_risk": GetPortfolioRiskIn,
    "get_rebalance_plan": GetRebalancePlanIn,
    "get_valuation": GetValuationIn,
    "get_dca_plans": GetDcaPlansIn,
    "get_fire_plan": GetFirePlanIn,
    # 投研与财报（v4.0）
    "research_analyze": ResearchAnalyzeIn,
    "research_backtest": ResearchBacktestIn,
    "statements_analyze": StatementsAnalyzeIn,
    # 投研预测（v4.1）
    "research_forecast": ResearchForecastIn,
    # 团队模拟盘（v4.2）
    "paper_open": PaperOpenIn,
    "paper_trade": PaperTradeIn,
    "paper_overview": PaperOverviewIn,
    # 连接中心（v4.4）
    "connect_catalog": ConnectCatalogIn,
    "connect_sync": ConnectSyncIn,
    "connect_fund_nav": ConnectFundNavIn,
    "connect_order": ConnectOrderIn,
    # 财务部门深化（v4.5）
    "tax_calc": TaxCalcIn,
    "cashflow_forecast": CashflowForecastIn,
    "scan_subscriptions": SubscriptionScanIn,
    "scan_anomalies": AnomalyScanIn,
    "pretrade_check": PretradeCheckIn,
    "import_brokerage_holdings": HoldingsImportIn,
    "parse_invoice": InvoiceParseIn,
    "market_breadth": MarketBreadthIn,
    "stock_profile": StockProfileIn,
    "conditional_order": ConditionalOrderIn,
    # 攻坚（v4.6）
    "categorize_bills": CategorizeIn,
    "broker_status": BrokerStatusIn,
    "broker_preview_order": BrokerPreviewIn,
    "broker_submit_order": BrokerSubmitIn,
    "invoice_vision_status": InvoiceVisionIn,
    # 财务写入
    "record_transaction": RecordTransactionIn,
    "save_user_memory": SaveUserMemoryIn,
    "record_position": RecordPositionIn,
    "sell_position": SellPositionIn,
    "trigger_morning_report": TriggerMorningReportIn,
    "backup_now": BackupNowIn,
    "set_setting": SetSettingIn,
    # 通用
    "get_now": GetNowIn,
    "web_search": WebSearchIn,
}

# 暴露给 MCP 但不在 function calling 工具集里的增强工具（M2.1 一并 schema 化，
# 使两侧共用同一套参数定义；是否对 LLM 暴露由各自的清单决定）。
MCP_ONLY_INPUT_MODELS: dict[str, type[BaseModel]] = {
    "get_net_worth": GetNetWorthIn,
    "get_financial_health": GetFinancialHealthIn,
    "get_returns": GetReturnsIn,
    "get_goal_progress": GetGoalProgressIn,
    "import_transactions": ImportTransactionsIn,
    "get_family_summary": GetFamilySummaryIn,
    "get_provenance": GetProvenanceIn,
}


def _strip_noise(node: Any) -> Any:
    """去掉 pydantic 生成的展示性字段，让 schema 与手写版本逐字一致。

    - `title`：pydantic 用字段名生成，OpenAI/MCP 都不需要，且会让 schema 变噪声
    - 可选字段的 `default`：下游工具统一用 `args.get(...) or 默认值` 兜底，
      schema 里再写一遍默认值会与实现产生第二处真源
    - 顶层 `description`：pydantic 会把无参数模型的 class docstring 带进来，
      而工具描述已在 function.description / MCP 工具 description 里给出，
      参数 schema 里再重复一遍是噪声（且两份描述会各自漂移）
    """
    if isinstance(node, dict):
        return {
            k: _strip_noise(v)
            for k, v in node.items()
            if k not in ("title", "default")
        }
    if isinstance(node, list):
        return [_strip_noise(x) for x in node]
    return node


def input_schema(name: str) -> dict[str, Any]:
    """取某工具入参的 JSON Schema（已去除展示性字段）。"""
    model = TOOL_INPUT_MODELS.get(name) or MCP_ONLY_INPUT_MODELS.get(name)
    if model is None:
        raise KeyError(f"未定义入参模型：{name}")
    schema = _strip_noise(model.model_json_schema())
    schema.pop("description", None)
    schema.setdefault("type", "object")
    # 空 required 无信息量（手写版本对无参数工具有的带有的不带，本身就不一致），
    # 统一不产出：OpenAI 与 MCP 都按"无必填项"处理。
    if schema.get("required") == []:
        schema.pop("required")
    return schema


def validate_tool_args(name: str, args: Any) -> tuple[dict[str, Any] | None, str | None]:
    """执行前校验工具入参 —— 让 extra="forbid" 真正落地，而不是只写在 schema 里。

    返回 (清洗后的参数, None) 或 (None, 错误文案)。三个执行边界
    （agent 工具循环 / agent_graph action 节点 / confirm 直接执行）都必须
    先过这一关再进 impl：模型多传字段、类型不符会被拦下，
    错误文案可直接回填给模型 self-correct。未登记模型的工具放行原参数
    （与 schema 派生口径一致：没模型 = 没约束）。
    """
    model = TOOL_INPUT_MODELS.get(name) or MCP_ONLY_INPUT_MODELS.get(name)
    if model is None:
        return (args if isinstance(args, dict) else {}), None
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return None, f"参数必须是 JSON 对象，收到 {type(args).__name__}"
    try:
        cleaned = model.model_validate(args)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", ())) or "(root)"
        msg = first.get("msg", "invalid")
        return None, f"参数校验失败：{loc}: {msg}"
    return dict(cleaned), None


def function_schema(name: str, description: str) -> dict[str, Any]:
    """产出 OpenAI function calling 形态的工具定义。"""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": input_schema(name),
        },
    }

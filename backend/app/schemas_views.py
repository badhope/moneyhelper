"""只读视图与分析：市场/账本/风控/预算/趋势/目标/体检/净值/家庭/审计/组合风险/估值/定投/FIRE。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .schemas_base import _In


class GetMarketViewIn(_In):
    """查持仓与行情：总市值、盈亏、集中度。"""

class GetLedgerViewIn(_In):
    """查账本：本月收支、结余、储蓄率、订阅、负债、应急金。"""

class GetFinancialIdentityIn(_In):
    """查财务数字身份证：财务坐标、数据覆盖、风险项、权限与来源。"""

class GetMonthlyReviewIn(_In):
    """查指定月份的结账复盘：收支、预算、异常、数据体检与下月动作。"""

    month: str = Field("", description="月份 YYYY-MM，可省略（默认本月）")

class GetRiskFlagsIn(_In):
    """运行风控规则：集中度/应急金/高息负债/负债收入比/储蓄率。"""

class GetBudgetIn(_In):
    month: str = Field("", description="月份 YYYY-MM，可省略（默认本月）")

class GetTrendIn(_In):
    months: int = Field(0, description="月份数 1-24，默认 6")

class GetGoalsIn(_In):
    """查财务目标：目标金额、已存、进度、建议月存。"""

class GetHealthCheckIn(_In):
    """结构化财务体检：五维度评分与建议。"""

class GetLessonsIn(_In):
    """查经验库：历史工具调用踩坑记录。"""

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


MODELS: dict[str, type[BaseModel]] = {
    "get_market_view": GetMarketViewIn,
    "get_ledger_view": GetLedgerViewIn,
    "get_financial_identity": GetFinancialIdentityIn,
    "get_monthly_review": GetMonthlyReviewIn,
    "get_risk_flags": GetRiskFlagsIn,
    "get_budget": GetBudgetIn,
    "get_trend": GetTrendIn,
    "get_goals": GetGoalsIn,
    "get_health_check": GetHealthCheckIn,
    "get_lessons": GetLessonsIn,
    "get_net_worth": GetNetWorthIn,
    "get_financial_health": GetFinancialHealthIn,
    "get_returns": GetReturnsIn,
    "get_goal_progress": GetGoalProgressIn,
    "import_transactions": ImportTransactionsIn,
    "get_family_summary": GetFamilySummaryIn,
    "get_provenance": GetProvenanceIn,
    "get_portfolio_risk": GetPortfolioRiskIn,
    "get_rebalance_plan": GetRebalancePlanIn,
    "get_valuation": GetValuationIn,
    "get_dca_plans": GetDcaPlansIn,
    "get_fire_plan": GetFirePlanIn,
}

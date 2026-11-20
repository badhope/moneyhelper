"""连接中心与增强能力：同步/交易指令/税务/现金流/扫描/预交易/导入/发票/条件单/账单分类/券商通道/债务规划。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .schemas_base import _In


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

class DebtPayoffPlanIn(_In):
    """债务清偿规划：雪崩法（按利率）与雪球法（按余额），逐月摊还模拟。"""

    extra_payment: float = Field(
        0, description="每月除最低月供外额外还款额，可省略（默认 0 = 只按最低月供）"
    )
    method: Literal["avalanche", "snowball", "custom"] = Field(
        "avalanche", description="avalanche 按利率从高到低（省利息最多）/ snowball 按余额从小到大"
    )
    custom_order: str = Field(
        "", description="method=custom 时的债务名称顺序，逗号分隔，可省略"
    )
    compare: bool = Field(
        False, description="true 时同时返回两种方法的对比与利息差额，可省略（默认 false）"
    )


MODELS: dict[str, type[BaseModel]] = {
    "connect_catalog": ConnectCatalogIn,
    "connect_sync": ConnectSyncIn,
    "connect_fund_nav": ConnectFundNavIn,
    "connect_order": ConnectOrderIn,
    "tax_calc": TaxCalcIn,
    "cashflow_forecast": CashflowForecastIn,
    "scan_subscriptions": SubscriptionScanIn,
    "scan_anomalies": AnomalyScanIn,
    "pretrade_check": PretradeCheckIn,
    "import_brokerage_holdings": HoldingsImportIn,
    "parse_invoice": InvoiceParseIn,
    "conditional_order": ConditionalOrderIn,
    "categorize_bills": CategorizeIn,
    "broker_status": BrokerStatusIn,
    "broker_preview_order": BrokerPreviewIn,
    "broker_submit_order": BrokerSubmitIn,
    "invoice_vision_status": InvoiceVisionIn,
    "debt_payoff_plan": DebtPayoffPlanIn,
}

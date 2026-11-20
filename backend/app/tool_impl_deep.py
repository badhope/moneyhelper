"""v4.5/v4.6 深化工具门面：财税、交易、执行层三域实现各成模块，这里只留目录与注册表。

本模块暴露 `DEEP_TOOL_NAMES`（name, description）与 `DEEP_TOOL_IMPL`（name → 协程），
由 tool_registry 合并进统一注册表。
"""

from __future__ import annotations

from typing import Any

from .tool_impl_deep_broker import (
    tool_broker_preview_order,
    tool_broker_status,
    tool_broker_submit_order,
    tool_categorize_bills,
    tool_invoice_vision_status,
)
from .tool_impl_deep_fiscal import (
    tool_cashflow_forecast,
    tool_debt_payoff_plan,
    tool_scan_anomalies,
    tool_scan_subscriptions,
    tool_tax_calc,
)
from .tool_impl_deep_trade import (
    tool_conditional_order,
    tool_import_brokerage_holdings,
    tool_market_breadth,
    tool_parse_invoice,
    tool_pretrade_check,
    tool_stock_profile,
)

DEEP_TOOL_NAMES: tuple[tuple[str, str], ...] = (
    (
        "tax_calc",
        "税负测算：增值税及附加（一般/简易计税）、企业所得税（标准/高新/小微）、个税（累计预扣法）、"
        "工资五险一金核算、综合税负率。适合「算一下这个月要交多少税」「税后工资多少」「公司税负多少」。",
    ),
    (
        "debt_payoff_plan",
        "债务清偿规划：按账本负债做逐月摊还模拟，对比雪崩法（按利率，省利息最多）与雪球法（按余额），"
        "输出还清顺序、几个月还清、总利息、相比只付最低月供能省多少。适合「先还哪笔」「多久能还清」「多还 2000 能省多少」。",
    ),
    (
        "cashflow_forecast",
        "现金流预测：按最近几个月真实收支分布，给出未来 1-12 个月悲观/中性/乐观三档余额。"
        "适合「我下个月会不会不够花」「未来三个月现金够不够」。",
    ),
    ("scan_subscriptions", "订阅识别：从流水里找周期性固定扣款，输出下次扣款日与涨价标记。适合「我都有哪些订阅」「哪个会员涨价了」。"),
    ("scan_anomalies", "异常扣款检测：按商户用中位数+MAD 找异常大额支出。适合「这个月有没有异常消费」「哪笔钱花得不对劲」。"),
    ("pretrade_check", "下单前风控检查：涨跌停、整手、T+1、集中度、日限额、重复单。适合在下单前问「这笔能不能买」「为什么下不了单」。"),
    (
        "import_brokerage_holdings",
        "导入券商持仓对账单 CSV：解析代码/名称/数量/成本/现价，可预览或直接合并进持仓。适合「把我的券商持仓导进来」。",
    ),
    ("parse_invoice", "解析并归档发票票面文本：提取发票代码/号码/日期/价税合计/购销方。适合「这张发票帮我记一下」。"),
    ("market_breadth", "市场温度：涨跌家数、涨跌停数量、情绪温度 0-100 与冷热档位。适合「今天市场怎么样」「情绪冷不冷」。"),
    ("stock_profile", "个股档案：PE/PB、总市值/流通市值、换手率、量比、振幅、涨跌停价。适合「茅台现在估值多少」「这只票基本面指标」。"),
    ("conditional_order", "创建条件单：价格跌破/突破或涨跌幅达到阈值时生成待确认指令。适合「跌到 1300 提醒我买」「涨 5% 就卖」。"),
)

DEEP_TOOL_IMPL: dict[str, Any] = {
    "tax_calc": tool_tax_calc,
    "cashflow_forecast": tool_cashflow_forecast,
    "scan_subscriptions": tool_scan_subscriptions,
    "scan_anomalies": tool_scan_anomalies,
    "pretrade_check": tool_pretrade_check,
    "import_brokerage_holdings": tool_import_brokerage_holdings,
    "parse_invoice": tool_parse_invoice,
    "market_breadth": tool_market_breadth,
    "stock_profile": tool_stock_profile,
    "conditional_order": tool_conditional_order,
}

DEEP_TOOL_NAMES = (
    *DEEP_TOOL_NAMES,
    (
        "categorize_bills",
        "账单智能归类：按规则引擎（商户/摘要/收支/金额多维匹配）给交易打分类，返回命中规则与兜底比例。适合「帮我看看这些账单怎么归类」「哪些消费没分类」。",
    ),
    ("broker_status", "券商执行层状态：交易开关、dry-run、各券商适配器（QMT/easytrader）本机可用性与缺失项。适合「能不能自动下单」「需要装什么」。"),
    ("broker_preview_order", "券商下单预检：跑资金上限/日限额/集中度/白名单/二次确认等全部护栏，返回放行结果与确认令牌（默认 dry-run，不下单）。"),
    ("broker_submit_order", "券商报单：必须带预检令牌；默认 dry-run 只返回模拟结果，真实开启需用户配置环境变量。"),
    ("invoice_vision_status", "探测发票识别能力：二维码解码器、OCR 引擎、PDF 表格解析是否可用，缺失时给安装建议。"),
)

DEEP_TOOL_IMPL = {
    **DEEP_TOOL_IMPL,
    "categorize_bills": tool_categorize_bills,
    "broker_status": tool_broker_status,
    "broker_preview_order": tool_broker_preview_order,
    "broker_submit_order": tool_broker_submit_order,
    "invoice_vision_status": tool_invoice_vision_status,
    "debt_payoff_plan": tool_debt_payoff_plan,
}

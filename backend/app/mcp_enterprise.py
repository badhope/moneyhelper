"""MCP 企业域工具：总账、应付、报销、组织与长任务。

从 mcp_server.py 拆出，注册机制不变——import 时 @_tool() 即完成注册；
mcp_server 末尾 import 触发注册并保留同名属性。
"""

from __future__ import annotations

from typing import Any

try:  # fastmcp 会解析函数签名，注解里的 Context 必须在运行时可见
    from fastmcp import Context
except Exception:  # pragma: no cover — fastmcp 不可用时 MCP 已整体关闭
    Context = Any  # type: ignore[misc,assignment]

import json

from . import db
from . import tools as xtools
from .mcp_server import _tool


def _tenant() -> int:
    from .db.tenant import current_tenant_id

    return current_tenant_id()


@_tool()
async def get_gl_summary() -> str:
    """查企业总账概览：科目、会计期间、最近凭证、试算平衡。"""
    return await xtools.tool_get_gl_summary({})


@_tool()
async def get_payables_summary() -> str:
    """查采购应付：供应商数、采购单状态分布、未付款应付金额、逾期应付。"""
    return await xtools.tool_get_payables_summary({})


@_tool()
async def get_expense_queue() -> str:
    """查报销队列：待审核报销单数量与金额。"""
    return await xtools.tool_get_expense_queue({})


@_tool()
async def get_org_overview() -> str:
    """查组织架构：部门、岗位、成员数量。"""
    return await xtools.tool_get_org_overview({})


@_tool()
async def list_longtasks() -> str:
    """查长任务列表：标题、类型、已完成阶段、状态。"""
    return await xtools.tool_list_longtasks({})


@_tool()
async def gl_accounts() -> str:
    """查总账科目表：科目编码、名称、类型（asset/liability/equity/income/expense）、是否启用。"""
    rows = await db.gl_list_accounts(_tenant())
    return json.dumps({"accounts": rows}, ensure_ascii=False, default=str)


@_tool()
async def gl_periods() -> str:
    """查会计期间列表：年、月、起止日期、状态（open/closed）。"""
    rows = await db.gl_list_periods(_tenant())
    return json.dumps({"periods": rows}, ensure_ascii=False, default=str)


@_tool()
async def gl_entries(period_id: int = 0, limit: int = 50) -> str:
    """查凭证列表（新→旧）。period_id 省略=全部期间；limit 1-200，默认 50。

    返回每张凭证的编号、日期、摘要、借贷合计、状态（draft/posted）、来源。
    """
    rows = await db.gl_list_entries(_tenant(), period_id or None, limit)
    return json.dumps({"entries": rows}, ensure_ascii=False, default=str)


@_tool()
async def gl_trial_balance(period_id: int) -> str:
    """查某会计期间的试算平衡表：各科目期初/借方/贷方/期末，以及全局是否借贷平衡。"""
    data = await db.gl_trial_balance(_tenant(), int(period_id))
    return json.dumps(data, ensure_ascii=False, default=str)


@_tool()
async def gl_create_entry(
    entry_date: str,
    description: str,
    lines: list[dict[str, Any]],
    post_now: bool = False,
) -> str:
    """新建总账凭证（默认只建草稿，post_now=true 时立即过账）。

    lines 是分录数组，每项形如 {"account_id": 1, "debit": 100, "credit": 0, "memo": "..."}；
    借贷必须平衡，金额单位为元（内部转整数分）。account_id 先用 gl_accounts 查。
    """
    entry = await db.gl_create_entry(_tenant(), entry_date, description, lines, 0)
    if post_now:
        entry = await db.gl_post_entry(_tenant(), int(entry["id"]))
    return json.dumps(entry, ensure_ascii=False, default=str)


@_tool()
async def vendors() -> str:
    """查供应商档案：编码、名称、税号、联系人、状态。"""
    rows = await db.vendor_list(_tenant())
    return json.dumps({"vendors": rows}, ensure_ascii=False, default=str)


@_tool()
async def purchase_orders() -> str:
    """查采购单：单号、供应商、金额、状态（draft/submitted/approved）、关联审批人。"""
    rows = await db.po_list(_tenant())
    return json.dumps({"orders": rows}, ensure_ascii=False, default=str)


@_tool()
async def payables() -> str:
    """查应付单：单号、供应商、发票号、金额、税额、到期日、状态、关联凭证与付款。"""
    rows = await db.payable_list(_tenant())
    return json.dumps({"payables": rows}, ensure_ascii=False, default=str)


@_tool()
async def expense_claims(status: str = "") -> str:
    """查报销单。status 可传 draft/submitted/approved/rejected，省略=全部。"""
    rows = await db.expense_list_claims(_tenant(), status or None)
    return json.dumps({"claims": rows}, ensure_ascii=False, default=str)


@_tool()
async def create_purchase_order(
    vendor_id: int,
    order_date: str,
    amount: float,
    expected_date: str = "",
    description: str = "",
) -> str:
    """新建采购单（草稿）。amount 单位为元；提交与审核需在采购页或调用对应工具人工确认。"""
    po = await db.po_create(
        _tenant(), int(vendor_id), order_date, expected_date, amount, description
    )
    return json.dumps(po, ensure_ascii=False, default=str)


@_tool()
async def create_payable(
    vendor_id: int,
    invoice_date: str,
    amount: float,
    expense_account_id: int,
    payable_account_id: int,
    po_id: int = 0,
    invoice_no: str = "",
    due_date: str = "",
    tax: float = 0,
) -> str:
    """新建应付单（草稿）。需先用 gl_accounts 查借方费用科目与贷方应付科目 id。"""
    ap = await db.payable_create(
        _tenant(),
        int(vendor_id),
        int(po_id) if po_id else None,
        invoice_no,
        invoice_date,
        due_date,
        amount,
        tax,
        int(expense_account_id),
        int(payable_account_id),
    )
    return json.dumps(ap, ensure_ascii=False, default=str)


@_tool()
async def longtask_templates() -> str:
    """查长任务模板：每种任务类型（小说/网页/Word/论文/程序）的阶段划分。"""
    from . import longtask

    return json.dumps({"templates": longtask.list_templates()}, ensure_ascii=False)


@_tool()
async def longtasks() -> str:
    """查长任务列表：标题、类型、状态、已完成阶段数。"""
    from . import longtask

    return json.dumps({"tasks": longtask.list_tasks()}, ensure_ascii=False)


@_tool()
async def run_longtask(task_id: str, max_stages: int = 0) -> str:
    """执行长任务（未完成阶段）。max_stages 限制本次跑几个阶段，0=全部。

    长任务会真实调用模型、逐阶段落盘产物，耗时可能数分钟到数十分钟。
    """
    from . import longtask

    task = await longtask.run_task(task_id, max_stages=max_stages or None)
    return json.dumps(task, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# 包装器分域模块：import 即注册（@_tool 装饰器副作用），同时保留同名属性
# ---------------------------------------------------------------------------
from .mcp_analytics import (  # noqa: F401,E402 — 注册副作用 + 同名属性
    get_family_summary,
    get_financial_health,
    get_goal_progress,
    get_net_worth,
    get_provenance,
    get_returns,
    import_transactions,
)
from .mcp_broker import (  # noqa: F401,E402 — 注册副作用 + 同名属性
    broker_preview_order,
    broker_status,
    broker_submit_order,
    categorize_bills,
    invoice_vision_status,
)
from .mcp_connect import (  # noqa: F401,E402 — 注册副作用 + 同名属性
    cashflow_forecast,
    conditional_order,
    connect_catalog,
    connect_fund_nav,
    connect_order,
    connect_sync,
    debt_payoff_plan,
    import_brokerage_holdings,
    market_breadth,
    parse_invoice,
    pretrade_check,
    scan_anomalies,
    scan_subscriptions,
    stock_profile,
    tax_calc,
)
from .mcp_market import (  # noqa: F401,E402 — 注册副作用 + 同名属性
    add_to_watchlist,
    get_kline,
    get_quote,
    get_watchlist,
    remove_from_watchlist,
    search_symbol,
)
from .mcp_research import (  # noqa: F401,E402 — 注册副作用 + 同名属性
    paper_open,
    paper_overview,
    paper_trade,
    research_analyze,
    research_backtest,
    research_forecast,
    statements_analyze,
    web_search,
)
from .mcp_views import (  # noqa: F401,E402 — 注册副作用 + 同名属性
    get_budget,
    get_dca_plans,
    get_fire_plan,
    get_goals,
    get_health_check,
    get_ledger_view,
    get_market_view,
    get_portfolio_risk,
    get_rebalance_plan,
    get_risk_flags,
    get_trend,
    get_valuation,
)
from .mcp_writes import (  # noqa: F401,E402 — 注册副作用 + 测试访问 _confirm_write
    _confirm_write,
    get_lessons,
    get_user_memory,
    record_position,
    record_transaction,
    save_user_memory,
    sell_position,
    set_setting,
)


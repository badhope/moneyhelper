"""工具注册表：schema + 实现 + 技能包模式（finance / general）的单一真源。

描述文案来自 tool_catalog，schema 来自 tool_schemas，实现在各 tools_* 模块；
本模块只做组装，不定义任何工具执行体。
"""

from __future__ import annotations

from typing import Any

from . import tool_schemas
from .tool_catalog import ENTERPRISE_TOOL_NAMES, FINANCE_TOOL_NAMES, GENERAL_TOOL_NAMES
from .tool_impl_deep import DEEP_TOOL_IMPL, DEEP_TOOL_NAMES  # noqa: F401
from .tools_connect import (
    tool_connect_catalog,
    tool_connect_fund_nav,
    tool_connect_order,
    tool_connect_sync,
)
from .tools_enterprise import (
    tool_get_expense_queue,
    tool_get_gl_summary,
    tool_get_org_overview,
    tool_get_payables_summary,
    tool_list_longtasks,
)
from .tools_market import (
    tool_add_watchlist,
    tool_get_quote,
    tool_get_watchlist,
    tool_record_position,
    tool_remove_watchlist,
    tool_search_symbol,
    tool_sell_position,
)
from .tools_memory import (
    tool_get_lessons,
    tool_get_user_memory,
    tool_save_user_memory,
)
from .tools_paper import tool_paper_open, tool_paper_overview, tool_paper_trade
from .tools_portfolio import (
    tool_get_dca_plans,
    tool_get_fire_plan,
    tool_get_portfolio_risk,
    tool_get_rebalance_plan,
    tool_get_valuation,
)
from .tools_report import tool_trigger_morning_report
from .tools_research import (
    tool_research_analyze,
    tool_research_backtest,
    tool_research_forecast,
    tool_statements_analyze,
)
from .tools_system import (
    tool_backup_now,
    tool_get_health_check,
    tool_get_now,
    tool_set_setting,
    tool_web_search,
)
from .tools_views import (
    tool_get_budget,
    tool_get_goals,
    tool_get_kline,
    tool_get_ledger_view,
    tool_get_market_view,
    tool_get_risk_flags,
    tool_get_trend,
    tool_record_transaction,
)

TOOLS: list[dict[str, Any]] = [
    tool_schemas.function_schema(name, desc) for name, desc in FINANCE_TOOL_NAMES
]

TOOL_IMPL: dict[str, Any] = {
    "get_market_view": tool_get_market_view,
    "get_ledger_view": tool_get_ledger_view,
    "get_risk_flags": tool_get_risk_flags,
    "get_budget": tool_get_budget,
    "get_trend": tool_get_trend,
    "record_transaction": tool_record_transaction,
    "get_kline": tool_get_kline,
    "get_goals": tool_get_goals,
    "get_user_memory": tool_get_user_memory,
    "save_user_memory": tool_save_user_memory,
    "get_lessons": tool_get_lessons,
    "get_health_check": tool_get_health_check,
    "search_symbol": tool_search_symbol,
    "get_quote": tool_get_quote,
    "add_to_watchlist": tool_add_watchlist,
    "remove_from_watchlist": tool_remove_watchlist,
    "get_watchlist": tool_get_watchlist,
    "record_position": tool_record_position,
    "sell_position": tool_sell_position,
    "trigger_morning_report": tool_trigger_morning_report,
    "backup_now": tool_backup_now,
    "set_setting": tool_set_setting,
    "get_portfolio_risk": tool_get_portfolio_risk,
    "get_rebalance_plan": tool_get_rebalance_plan,
    "get_valuation": tool_get_valuation,
    "get_dca_plans": tool_get_dca_plans,
    "get_fire_plan": tool_get_fire_plan,
    "research_analyze": tool_research_analyze,
    "research_backtest": tool_research_backtest,
    "statements_analyze": tool_statements_analyze,
    "research_forecast": tool_research_forecast,
    "paper_open": tool_paper_open,
    "paper_trade": tool_paper_trade,
    "paper_overview": tool_paper_overview,
    "connect_catalog": tool_connect_catalog,
    "connect_sync": tool_connect_sync,
    "connect_fund_nav": tool_connect_fund_nav,
    "connect_order": tool_connect_order,
    **DEEP_TOOL_IMPL,
    # 企业域只读（切片 12）
    "get_gl_summary": tool_get_gl_summary,
    "get_payables_summary": tool_get_payables_summary,
    "get_expense_queue": tool_get_expense_queue,
    "get_org_overview": tool_get_org_overview,
    "list_longtasks": tool_list_longtasks,
}

GENERAL_TOOLS: list[dict[str, Any]] = [
    tool_schemas.function_schema(name, desc) for name, desc in GENERAL_TOOL_NAMES
]

GENERAL_IMPL: dict[str, Any] = {"get_now": tool_get_now, "web_search": tool_web_search}

_GENERAL_SCHEMAS = {t["function"]["name"]: t for t in GENERAL_TOOLS}

_TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    t["function"]["name"]: {
        "schema": t, "impl": TOOL_IMPL[t["function"]["name"]], "mode": "finance",
    }
    for t in TOOLS
}
_TOOL_REGISTRY.update({
    n: {"schema": _GENERAL_SCHEMAS[n], "impl": GENERAL_IMPL[n], "mode": "general"}
    for n in GENERAL_IMPL
})

FINANCE_TOOLS: list[dict[str, Any]] = [r["schema"] for r in _TOOL_REGISTRY.values() if r["mode"] == "finance"]
FINANCE_IMPL: dict[str, Any] = {n: r["impl"] for n, r in _TOOL_REGISTRY.items() if r["mode"] == "finance"}
GENERAL_TOOLS: list[dict[str, Any]] = [r["schema"] for r in _TOOL_REGISTRY.values() if r["mode"] == "general"]
GENERAL_IMPL: dict[str, Any] = {n: r["impl"] for n, r in _TOOL_REGISTRY.items() if r["mode"] == "general"}
TOOL_REGISTRY: dict[str, dict[str, Any]] = _TOOL_REGISTRY

ENTERPRISE_TOOLS: list[dict[str, Any]] = [
    r["schema"] for n, r in _TOOL_REGISTRY.items() if n in ENTERPRISE_TOOL_NAMES
]
ENTERPRISE_IMPL: dict[str, Any] = {
    n: r["impl"] for n, r in _TOOL_REGISTRY.items() if n in ENTERPRISE_TOOL_NAMES
}

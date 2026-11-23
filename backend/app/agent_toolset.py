"""工具面装配：内置科研工具、技能开关、MCP 动态工具与主角色白名单。

从 agent.py 的 run_agent 中抽出（原 209-270 行）。顺序有硬约束：
内置工具 → 技能开关过滤 → MCP 合并 → 角色白名单，白名单必须最后。
"""

from __future__ import annotations

from typing import Any

from . import agent_config, mcp_client
from .agent_tooling import ALLOWED_IMPL, READ_TOOLS
from .logging_utils import get_logger

log = get_logger(__name__)

# 路由到工具面的动态收窄：不是把全部只读工具一次塞给模型，而是按
# supervisor 判定的问题域只暴露相关工具。对齐 coding harness 的 progressive
# disclosure——工具越少，小模型误选与 schema 占用越低。
# 只对明确单一域生效；both/未知路由保留全量，宁可多给也不要用错工具集。
_ROUTE_TOOLS: dict[str, frozenset[str]] = {
    "market": frozenset({
        "get_market_view", "get_kline", "search_symbol", "get_quote", "get_watchlist",
        "get_portfolio_risk", "get_rebalance_plan", "get_valuation", "get_dca_plans",
        "get_fire_plan", "research_analyze", "research_backtest", "research_forecast",
        "statements_analyze", "market_breadth", "stock_profile", "pretrade_check",
        "connect_catalog", "connect_fund_nav", "paper_overview", "broker_status",
    }),
    "ledger": frozenset({
        "get_ledger_view", "get_financial_identity", "get_monthly_review",
        "get_risk_flags", "get_budget", "get_trend", "get_goals", "get_user_memory",
        "get_lessons", "get_health_check", "tax_calc", "debt_payoff_plan",
        "cashflow_forecast", "scan_subscriptions", "scan_anomalies",
    }),
}


async def build_toolset(
    tools_list: list | None,
    impl_map: dict | None,
    *,
    route: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """返回 (tool_schemas, tool_map, internal_impl, mcp_schemas)。"""
    tool_schemas = tools_list if tools_list is not None else READ_TOOLS
    tool_map = impl_map if tools_list is not None else ALLOWED_IMPL
    # 按路由收窄本地只读工具面（显式 tools_list 的通用分支不参与）
    allowed_by_route = _ROUTE_TOOLS.get(str(route or "").strip())
    if tools_list is None and allowed_by_route:
        tool_schemas = [
            t for t in tool_schemas
            if t["function"]["name"] in allowed_by_route
        ]
        tool_map = {k: v for k, v in tool_map.items() if k in allowed_by_route}
        log.info(
            "agent.toolset route=%s tools=%s",
            route,
            [t["function"]["name"] for t in tool_schemas],
        )
    # Studio 内置科研工具：只进财务/科研分支的工具面（内部工具不对外暴露）
    internal_impl: dict[str, Any] = {}
    if tools_list is None:
        try:
            from .studio import internal_tools as studio_tools
            from .studio import store as studio_store

            enabled_internal = await studio_store.internal_tools_enabled()
            if enabled_internal:
                wanted = [
                    s
                    for s in studio_tools.INTERNAL_FUNCTION_SCHEMAS
                    if enabled_internal.get(s["function"]["name"])
                ]
                if wanted:
                    tool_schemas = tool_schemas + wanted

                    def _make_internal_runner(tool_name: str):
                        async def _run(args: dict[str, Any]) -> str:
                            return studio_tools.run_internal_tool(tool_name, args) or ""

                        return _run

                    # 执行层统一 await impl(args)：内置工具是同步纯函数，必须包一层协程，
                    # 否则 await 一个 str 会抛 TypeError，8 个内置工具全部不可用。
                    internal_impl = {
                        name: _make_internal_runner(name)
                        for name in enabled_internal
                        if name in studio_tools.INTERNAL_TOOL_SPECS
                    }
        except Exception:  # noqa: BLE001 — 内置工具装配失败不影响主工具面
            internal_impl = {}
        # 技能开关真正生效：被关闭技能对应的工具从工具面移除（与 react 路径同口径）
        disabled_tools = await agent_config.disabled_tool_names()
        if disabled_tools:
            tool_schemas = [
                t for t in tool_schemas if t["function"]["name"] not in disabled_tools
            ]
            tool_map = {k: v for k, v in ALLOWED_IMPL.items() if k not in disabled_tools}
    # P2 MCP：把已配置 MCP 服务器提供的工具动态合并进工具列表（仅财务分支，通用分支不接外部工具）
    mcp_schemas: list[dict[str, Any]] = []
    if tools_list is None:
        try:
            mcp_schemas = await mcp_client.refresh()
            tool_schemas = tool_schemas + mcp_schemas
        except Exception:  # noqa: BLE001 — MCP 异常不影响主流程
            pass
        # 主角色工具白名单必须放在最后一步：它是「最终暴露给模型的工具面」，
        # 放在 MCP 合并之前会被后加的 mcp__* 工具绕过去（实测白名单只剩 1 个工具时仍有 9 个）。
        try:
            from .studio import store as studio_store

            role = (await studio_store.primary_role()).get("role") or {}
            allowed = role.get("tools")
            if isinstance(allowed, list) and allowed:
                allow = {str(x) for x in allowed}
                tool_schemas = [t for t in tool_schemas if t["function"]["name"] in allow]
                tool_map = {k: v for k, v in tool_map.items() if k in allow}
                mcp_schemas = [m for m in mcp_schemas if m["function"]["name"] in allow]
        except Exception:  # noqa: BLE001 — 角色配置异常时保留完整工具面
            pass

    return tool_schemas, tool_map, internal_impl, mcp_schemas

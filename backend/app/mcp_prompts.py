"""MCP prompts：月度复盘、持仓体检与目标规划。

import 时 @mcp.prompt() 即注册，依赖 mcp_server 里的 mcp 实例（末尾 import 触发）。
"""

from __future__ import annotations

from typing import Any

try:  # fastmcp 会解析函数签名，注解里的 Context 必须在运行时可见
    from fastmcp import Context
except Exception:  # pragma: no cover — fastmcp 不可用时 MCP 已整体关闭
    Context = Any  # type: ignore[misc,assignment]

from .mcp_server import mcp


@mcp.prompt()
def monthly_review(month: str = "") -> str:
    """月度财务复盘：收支结构 + 异常项 + 下月建议。

    参数 month 形如 2026-11；留空表示当月。
    """
    target = month or "本月"
    return (
        f"请为我做 {target} 的财务复盘，按以下结构输出：\n"
        "1. 收支概览：总收入、总支出、结余、储蓄率（用 get_trend / get_budget 的数据）；\n"
        "2. 支出结构：占比最高的三类及金额，指出是否存在异常增长（用 get_ledger_view）；\n"
        "3. 风险提示：调用 get_risk_flags，逐条说明影响与可执行动作；\n"
        "4. 下月建议：给出 1-3 条具体、可量化的调整建议。\n\n"
        "要求：所有金额必须来自工具返回，不要估算；数据缺失时明确说明缺什么。"
    )

@mcp.prompt()
def portfolio_checkup() -> str:
    """持仓体检：集中度、盈亏归因、再平衡建议。"""
    return (
        "请对我的投资组合做一次体检，按以下结构输出：\n"
        "1. 整体表现：总市值、累计盈亏、今日盈亏（get_market_view）；\n"
        "2. 风险集中度：单一标的与行业占比，标出越过 40% 阈值的项（get_portfolio_risk）；\n"
        "3. 盈亏贡献：哪几只贡献了主要盈利/亏损（get_market_view 的 pnl 字段）；\n"
        "4. 再平衡建议：调用 get_rebalance_plan，说明每笔调整的金额与理由。\n\n"
        "要求：不要给买卖建议式的肯定判断，只陈述数据与规则触发情况；"
        "所有百分比保留两位小数。"
    )

@mcp.prompt()
def goal_planning() -> str:
    """目标规划：进度诊断 + 每月需存 + 可行性判断。"""
    return (
        "请评估我的财务目标进度，按以下结构输出：\n"
        "1. 逐个目标的完成度、剩余缺口、距截止月还有几个月（get_goals）；\n"
        "2. 按当前储蓄能力，判断每个目标是否可行；不可行的给出两个替代方案"
        "（延长期限 / 降低目标额）；\n"
        "3. 如果需要调整月度投入，给出具体数字。\n\n"
        "要求：可行性判断必须基于 get_trend 的真实结余数据，不要用收入代替储蓄能力。"
    )

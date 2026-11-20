"""四部门确定性执行器与工单派发。

执行器按名字从门面解析（`getattr(_facade.department_mod(), name)`）：
测试会直接替换 `department._run_risk`，固定引用会让补丁落空。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from . import department as _facade
from . import tools
from .dept_models import (
    WorkOrder,
    order_to_dict,
)
from .logging_utils import get_logger

log = get_logger(__name__)

Emit = Callable[[dict[str, Any]], Awaitable[None]]

async def _run_accounting() -> tuple[str, dict[str, float]]:
    """会计部：账本口径的收支与结余 + 健康体检。"""
    import json

    ledger = json.loads(await tools.tool_get_ledger_view({}))
    health = json.loads(await tools.tool_get_health_check({}))
    text = (
        f"【账本视角】本月收入 {ledger.get('income', 0):,.2f} 元，"
        f"支出 {ledger.get('expense', 0):,.2f} 元，结余 {ledger.get('net', 0):,.2f} 元。\n"
        f"【健康体检】得分 {health.get('score', '—')}（{health.get('grade', '—')}）。"
    )
    metrics = {
        "income": float(ledger.get("income", 0)),
        "expense": float(ledger.get("expense", 0)),
        "net": float(ledger.get("net", 0)),
    }
    return text, metrics


async def _run_risk() -> tuple[str, dict[str, float]]:
    """风控部：风险信号与预算执行。"""
    import json

    flags = json.loads(await tools.tool_get_risk_flags({}))
    budget = json.loads(await tools.tool_get_budget({}))
    # tool_get_risk_flags 的 flags 是字符串列表（不是对象列表），直接展示
    items = flags.get("flags") or []
    text_lines = [f"【风控信号】共 {len(items)} 项需关注"]
    for f in items[:5]:
        text_lines.append(f"· {f if isinstance(f, str) else f.get('text') or f.get('code')}")
    used = budget.get("total_spent")
    if used is not None:
        text_lines.append(f"【预算执行】已用 {float(used):,.2f} 元")
    metrics: dict[str, float] = {"risk_flags": float(len(items))}
    return "\n".join(text_lines), metrics


async def _run_invest() -> tuple[str, dict[str, float]]:
    """投资部：组合市值/盈亏 + 目标进度。"""
    import json

    market = json.loads(await tools.tool_get_market_view({}))
    # tool_get_goals 返回的是列表（不是 dict），别按 dict 取
    goals = json.loads(await tools.tool_get_goals({}))
    goal_list = goals if isinstance(goals, list) else (goals.get("goals") or [])
    cap = (market.get("top_positions") or [{}])[0]
    text = (
        f"【市场视角】组合总市值 {market.get('total_market_value', 0):,.2f} 元，"
        f"累计盈亏 {market.get('total_pnl', 0):,.2f} 元"
        f"（{market.get('total_pnl_pct', 0):+.2f}%）。最大持仓 {cap.get('name', '—')}。\n"
        f"【目标进度】{len(goal_list)} 个目标在跟踪。"
    )
    metrics = {
        "total_market_value": float(market.get("total_market_value", 0)),
        "total_pnl": float(market.get("total_pnl", 0)),
    }
    return text, metrics


async def _run_bookkeeping() -> tuple[str, dict[str, float]]:
    """记账部：流水口径的支出与趋势。"""
    import json

    ledger = json.loads(await tools.tool_get_ledger_view({}))
    # tool_get_trend 返回的也是列表（每月一条），不是 dict
    trend = json.loads(await tools.tool_get_trend({}))
    months = trend if isinstance(trend, list) else (trend.get("months") or [])
    text = (
        f"【流水视角】本月记录支出 {ledger.get('expense', 0):,.2f} 元，"
        f"共 {len(ledger.get('top_categories') or [])} 个主要分类。\n"
        f"【月度趋势】近 {len(months)} 个月趋势已核对。"
    )
    metrics = {
        # 与会计部同口径：两个部门的 expense 必须一致，否则账本有分歧
        "expense": float(ledger.get("expense", 0)),
    }
    return text, metrics


_DEPT_RUNNERS: dict[str, str] = {
    "accounting": "_run_accounting",
    "risk": "_run_risk",
    "invest": "_run_invest",
    "bookkeeping": "_run_bookkeeping",
}


async def _execute_order(
    order: WorkOrder, emit: Emit | None, use_agent: bool = True
) -> WorkOrder:
    """执行一张工单。

    use_agent=True（默认）走 M3.3 部门 agent：模型自主选择工具、受工具白名单
    与 token 预算约束；模型不可用或循环失败时自动退回确定性执行。
    use_agent=False 强制走确定性执行（离线/调试场景）。
    """
    if use_agent:
        from . import dept_agent

        return await dept_agent.run_dept_agent(order, emit)

    order.status = "running"
    if emit:
        await emit(
            {
                "type": "dept",
                "order": order_to_dict(order),
                "status": "running",
            }
        )
    try:
        # 按名字解析：便于测试替换与未来热插拔部门实现
        fn = getattr(_facade.department_mod(), _DEPT_RUNNERS[order.dept])
        text, metrics = await fn()
        order.output, order.metrics = text, metrics
        order.status = "done"
    except Exception as e:  # noqa: BLE001 — 单个部门失败不拖垮整份呈批件
        log.warning("dept_failed dept=%s error=%s", order.dept, str(e))
        order.status = "failed"
        order.error = str(e)[:200]
    if emit:
        await emit({"type": "dept", "order": order_to_dict(order), "status": order.status})
    return order

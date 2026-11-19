"""M3 财务部门模式：一句话 → 工单分解 → 四部门并行 → 秘书交叉对账 → 呈批件。

与 agent_graph 的分工：
  - agent_graph = 单轮问答编排（supervisor 线性流水线）
  - 本模块 = 「老板一句话，部门自己干」：拆单 → 并行执行 → 秘书对账汇总

## 当前实现范围

- **工单**：pydantic 模型（`dept_models.WorkOrder`），带部门/状态枚举校验、
  token 预算、结构化 metrics
- **派工**：规则版（关键词匹配）。LLM 结构化派工留到 M3.2，
  接口已按 LLM 输出形态设计（`DispatchPlan` 可直接接模型 JSON）
- **执行**：各部门直连确定性工具（无模型也能跑，数字不出确定性内核）
- **对账**：按结构化 metrics 的 key 比对，不一致标红并指出是哪两个部门
- **呈批件**：结论 / 各部门发现 / 冲突 / 建议

## 为什么对账靠 metrics 而不是文本

文本里抠数字（正则）在两处以上出现时无法判断"哪个数对应哪个口径"，
且格式一变就失效。让每个部门产出 `metrics: dict[str, float]`，
秘书按 key 比对是确定性的：同名口径不一致就是真冲突。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from . import analysis, tools
from .dept_models import (
    DEPARTMENTS,
    DEPT_TITLES,
    WorkOrder,
    order_to_dict,
)
from .logging_utils import get_logger

log = get_logger(__name__)

Emit = Callable[[dict[str, Any]], Awaitable[None]]

__all__ = [
    "DEPARTMENTS",
    "DEPT_TITLES",
    "WorkOrder",
    "decompose",
    "run_department_mode",
]


def department_mod():
    return __import__(__name__, fromlist=[""])


# ---------------------------------------------------------------------------
# 派工（规则版；M3.2 接 LLM 结构化输出）
# ---------------------------------------------------------------------------

# 关键词 → (部门, 任务描述)。顺序即优先级。
_DISPATCH_RULES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "invest",
        ("持仓", "股票", "基金", "盈亏", "市值", "行情", "etf", "收益", "组合"),
        "复盘当前持仓与市场表现",
    ),
    (
        "risk",
        ("风险", "健康", "应急", "负债", "dti", "集中度", "超支", "预算", "安全"),
        "扫描风控信号（集中度/应急金/负债/预算漂移）",
    ),
    (
        "bookkeeping",
        ("记", "入账", "花了", "消费", "支出明细", "分类", "流水"),
        "核对近期记账与分类质量",
    ),
    (
        "accounting",
        ("汇总", "总结", "盘", "体检", "报告", "现金流", "结余", "收支", "财务"),
        "编制本期收支与结余报表",
    ),
)

# "全面盘点"类问题：老板要的是整体状况，单个部门答不了。
# 这类词一旦命中就派全部四部门，而不是按关键词挑一两个——
# 部门模式的价值就是多视角交叉，只派一个部门时它退化成普通问答。
_FULL_REVIEW_WORDS = (
    "盘",
    "体检",
    "全面",
    "整体",
    "总览",
    "财务状况",
    "家底",
    "上季度",
    "本季度",
    "这季度",
)

_FULL_REVIEW_TASKS: dict[str, str] = {
    "accounting": "编制本期收支与结余报表",
    "risk": "扫描风控信号（集中度/应急金/负债/预算漂移）",
    "invest": "复盘当前持仓与市场表现",
    "bookkeeping": "核对近期记账与分类质量",
}

_DEPT_TOOLS: dict[str, list[str]] = {
    "accounting": ["tool_get_ledger_view", "tool_get_health_check"],
    "risk": ["tool_get_risk_flags", "tool_get_budget"],
    "invest": ["tool_get_market_view", "tool_get_goals"],
    "bookkeeping": ["tool_get_ledger_view", "tool_get_trend"],
}


def decompose(question: str) -> list[WorkOrder]:
    """把老板的一句话拆成工单（规则版）。

    无关键词命中时兜底派给会计部 + 风控部：财务问题至少需要"账本现状"与
    "风险信号"两块信息，这比只派一个部门更接近老板的实际意图。
    """
    q = question.lower()
    # 全面盘点：派全部四部门（单部门无法回答"整体怎么样"）
    if any(w in q for w in _FULL_REVIEW_WORDS):
        return [
            WorkOrder(dept=d, task=_FULL_REVIEW_TASKS[d], tools_allowed=_DEPT_TOOLS[d])
            for d in ("accounting", "risk", "invest", "bookkeeping")
        ]

    orders: list[WorkOrder] = []
    for dept, kws, task in _DISPATCH_RULES:
        if any(kw in q for kw in kws):
            if any(o.dept == dept for o in orders):
                continue
            orders.append(
                WorkOrder(dept=dept, task=task, tools_allowed=_DEPT_TOOLS[dept])
            )
    if not orders:
        orders = [
            WorkOrder(
                dept="accounting",
                task="编制本期收支与结余报表",
                tools_allowed=_DEPT_TOOLS["accounting"],
            ),
            WorkOrder(
                dept="risk", task="扫描风控信号", tools_allowed=_DEPT_TOOLS["risk"]
            ),
        ]
    return orders
# ---------------------------------------------------------------------------
# 各部门执行：返回 (文本, 结构化指标)
# ---------------------------------------------------------------------------


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
        fn = getattr(department_mod(), _DEPT_RUNNERS[order.dept])
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


# ---------------------------------------------------------------------------
# 秘书：交叉对账 + 呈批件
# ---------------------------------------------------------------------------

# 参与交叉对账的指标：只有这些 key 出现两次以上才比对。
# 其余指标（如市值、风险项数）天然只由一个部门产出，比对无意义。
_RECONCILE_KEYS = ("income", "expense", "net", "total_market_value")


def reconcile(orders: list[WorkOrder]) -> list[dict[str, Any]]:
    """按结构化指标交叉对账，返回冲突列表。

    只比对 `_RECONCILE_KEYS` 且至少有 2 个部门产出的指标：
    同一个 key 出现两个不同数值 → 冲突，指明是哪两个部门。
    """
    by_key: dict[str, list[tuple[str, float]]] = {}
    for o in orders:
        if o.status != "done":
            continue
        for key, value in o.metrics.items():
            if key in _RECONCILE_KEYS:
                by_key.setdefault(key, []).append((o.dept, float(value)))

    conflicts: list[dict[str, Any]] = []
    for key, entries in by_key.items():
        values = {round(v, 2) for _, v in entries}
        if len(values) > 1:
            conflicts.append(
                {
                    "metric": key,
                    "detail": "；".join(
                        f"{DEPT_TITLES.get(d, d)}报 {v:,.2f}" for d, v in entries
                    ),
                    "depts": [d for d, _ in entries],
                }
            )
    return conflicts


def _verdict(orders: list[WorkOrder], conflicts: list[dict[str, Any]]) -> str:
    """呈批件的结论行：先给判断，再给依据。"""
    done = [o for o in orders if o.status == "done"]
    failed = [o for o in orders if o.status == "failed"]
    if not done:
        return "各部门均未能取到数据，建议先检查账本是否为空。"
    if failed:
        names = "、".join(DEPT_TITLES.get(o.dept, o.dept) for o in failed)
        return f"{names}未能完成，其余部门结果已在下方列出。"
    if conflicts:
        return f"有 {len(conflicts)} 项口径不一致，需先核对再决策。"
    return f"{len(done)} 个部门口径一致，可以直接决策。"


async def _secretary(orders: list[WorkOrder], question: str) -> dict[str, Any]:
    """秘书汇总：结论 → 各部门发现 → 冲突 → 建议。"""
    conflicts = reconcile(orders)
    sections: list[str] = []
    for o in orders:
        title = DEPT_TITLES.get(o.dept, o.dept)
        if o.status == "done":
            sections.append(f"## {title}\n{o.output}")
        else:
            sections.append(f"## {title}（未完成：{o.error or o.status}）")

    verdict = _verdict(orders, conflicts)
    conflict_lines = [
        f"· {c['metric']} 不一致：{c['detail']}" for c in conflicts
    ]
    report_parts = [f"# 呈批件\n\n**结论**：{verdict}\n"]
    if conflict_lines:
        report_parts.append("## 需核对\n" + "\n".join(conflict_lines) + "\n")
    report_parts.append("\n\n---\n\n".join(sections))

    return {
        "question": question,
        "verdict": verdict,
        "orders": [order_to_dict(o) for o in orders],
        "report": "\n".join(report_parts),
        "conflicts": conflicts,
        "disclaimer": analysis.DISCLAIMER,
    }


async def run_department_mode(
    question: str,
    emit: Emit | None = None,
    lang: str = "zh",
    use_llm_dispatch: bool = True,
    use_agent: bool = True,
) -> dict[str, Any]:
    """部门模式入口：拆单 → 并行执行 → 秘书汇总呈批。

    派工优先走 LLM（M3.2）：模型不可用或输出非法时回落到规则派工，
    返回值里的 `dispatch` 字段标明实际用了哪条路径（便于排查"为什么少了个部门"）。
    """
    if use_llm_dispatch:
        from . import dept_dispatch

        orders, dispatch_src = await dept_dispatch.dispatch(question, lang)
    else:
        orders, dispatch_src = decompose(question), "rules"
    if emit:
        await emit(
            {
                "type": "dept_start",
                "question": question,
                "dispatch": dispatch_src,
                "orders": [order_to_dict(o) for o in orders],
            }
        )
    # 并行派发；return_exceptions 确保等全部部门结束，不留后台任务拖垮事件循环
    results = await asyncio.gather(
        *(_execute_order(o, emit, use_agent=use_agent) for o in orders),
        return_exceptions=True,
    )
    done: list[WorkOrder] = []
    for o, r in zip(orders, results, strict=False):
        if isinstance(r, Exception):
            o.status, o.error = "failed", str(r)[:200]
        done.append(o)
    report = await _secretary(done, question)
    report["dispatch"] = dispatch_src
    if emit:
        await emit(
            {
                "type": "dept_final",
                "verdict": report["verdict"],
                "conflicts": report["conflicts"],
            }
        )
    return report

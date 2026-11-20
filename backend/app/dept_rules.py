"""规则派工：关键词 → 部门工单，另带全复核触发词与任务模板。

顺序即优先级；LLM 结构化派工（M3.2）按 `DispatchPlan` 形态接，不改变这里的数据形状。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .dept_models import (
    WorkOrder,
)
from .logging_utils import get_logger

log = get_logger(__name__)

Emit = Callable[[dict[str, Any]], Awaitable[None]]


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

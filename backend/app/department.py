"""M3 财务部门模式门面：派工规则 / 四部门执行 / 秘书对账各成一模块。

老板一句话 → 拆单 → 并行执行 → 秘书交叉对账 → 呈批件。
对账只比对结构化 `metrics`（同名口径不一致才是真冲突），不从文本抠数字。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

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


from .dept_rules import (  # noqa: F401,E402 — 对外同名导出
    _DEPT_TOOLS,
    _DISPATCH_RULES,
    _FULL_REVIEW_TASKS,
    _FULL_REVIEW_WORDS,
    decompose,
)
from .dept_runners import (  # noqa: F401,E402 — 对外同名导出与测试替换点
    _DEPT_RUNNERS,
    _execute_order,
    _run_accounting,
    _run_bookkeeping,
    _run_invest,
    _run_risk,
)
from .dept_secretary import (  # noqa: F401,E402 — 对外同名导出
    _RECONCILE_KEYS,
    _secretary,
    _verdict,
    reconcile,
)


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

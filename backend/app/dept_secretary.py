"""秘书：按结构化指标交叉对账，产出冲突与呈批件结论。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from . import analysis
from .dept_models import (
    DEPT_TITLES,
    WorkOrder,
    order_to_dict,
)
from .logging_utils import get_logger

log = get_logger(__name__)

Emit = Callable[[dict[str, Any]], Awaitable[None]]


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

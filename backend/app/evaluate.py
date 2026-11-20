"""规则驱动的"首页评估层"：聚合预算/订阅/债务/目标/现金流信号，生成结构化行动项。

完全确定性，不依赖 LLM；规则本体在 `evaluate_rules.py`，数据结构与日期工具在
`evaluate_types.py`，此处保留 RULES 注册表、`evaluate_all` 与排序/汇总。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .evaluate_rules import (
    _rule_budget,
    _rule_cashflow,
    _rule_debts,
    _rule_goals,
    _rule_subscriptions,
)
from .evaluate_types import (  # noqa: F401 — 对外同名导出（测试直接用）
    SUBS_REMIND_WITHIN_DAYS,
    EvalItem,
    _days_in_month,
    _month_str,
    _safe_int,
    _upcoming_due,
)

RULES = (
    ("budget",   _rule_budget),
    ("subs",     _rule_subscriptions),
    ("debts",    _rule_debts),
    ("goals",    _rule_goals),
    ("cashflow", _rule_cashflow),
)


async def evaluate_all(month: str | None = None, *, today: date | None = None) -> dict[str, Any]:
    """跑全部规则，返回按 priority 排序后的 items + 元数据。"""
    month = month or _month_str(today)
    today = today or date.today()

    items: list[EvalItem] = []
    for name, fn in RULES:
        try:
            if name == "budget" or name == "goals":
                items += await fn(month)
            elif name == "cashflow":
                items += await fn()
            elif name in ("subs", "debts"):
                items += await fn(today)
            else:
                items += await fn(month)
        except Exception as exc:  # noqa: BLE001 — 任一规则异常不应拖垮评估层
            from .logging_utils import get_logger
            get_logger(__name__).warning("evaluate rule %s failed: %s", name, exc)

    items.sort(key=lambda i: (i.priority, i.kind))
    return {
        "month": month,
        "refreshed_at": datetime.now().isoformat(timespec="seconds"),
        "items": [i.to_dict() for i in items],
        "summary": _summary(items),
    }


def _summary(items: list[EvalItem]) -> dict[str, int]:
    r = {"todo": 0, "warn": 0, "info": 0, "goal": 0, "max_priority": 3}
    for i in items:
        r[i.kind] = r.get(i.kind, 0) + 1
        if i.priority < r["max_priority"]:
            r["max_priority"] = i.priority
    return r

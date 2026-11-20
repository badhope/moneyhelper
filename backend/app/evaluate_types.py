"""评估层数据结构与日期/金额小工具（EvalItem、月度窗口计算）。"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

from . import scheduler

# 与 scheduler.py 中的订阅到期窗口保持一致
SUBS_REMIND_WITHIN_DAYS = getattr(scheduler, "SUBS_REMIND_WITHIN_DAYS", 7)


@dataclass
class EvalItem:
    kind: str           # todo / warn / info / goal
    priority: int       # 0..3
    code: str           # i18n key: eval.<code>.title / eval.<code>.detail
    title: str = ""     # 缺省回退（i18n 失败时用）
    detail: str = ""
    vars: dict[str, Any] = field(default_factory=dict)
    action: dict[str, str] | None = None  # {"path": "/settings#budget", "label": "..."}

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self)}


# --------------------------------------------------------------------------
# 日期 / 金额工具
# --------------------------------------------------------------------------

def _month_str(d: date | None = None) -> str:
    return (d or date.today()).strftime("%Y-%m")


def _days_in_month(d: date) -> int:
    m = d.month
    y = d.year
    if m == 12:
        return (date(y + 1, 1, 1) - date(y, m, 1)).days
    return (date(y, m + 1, 1) - date(y, m, 1)).days


def _safe_int(s: str) -> int | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return int(re.sub(r"\s+", "", s))
    except (TypeError, ValueError):
        return None


def _upcoming_due(today: date, due_day_raw: str, *, window: int) -> tuple[int, date] | None:
    """(days_until, due_date) or None（不在窗口内 / due_day 非法）。"""
    if window <= 0:
        window = 7
    n = _safe_int(due_day_raw)
    if n is None or n <= 0:
        return None

    def on_month(d: date, day: int) -> date | None:
        last = _days_in_month(d)
        if day > last:
            return None
        return d.replace(day=day)

    # 本月
    this = on_month(today, n)
    if this and today <= this <= today + timedelta(days=window):
        return ( (this - today).days, this )
    # 下月
    if today.month == 12:
        nxt = today.replace(year=today.year + 1, month=1, day=1)
    else:
        nxt = today.replace(month=today.month + 1, day=1)
    that = on_month(nxt, n)
    if that and today <= that <= today + timedelta(days=window):
        return ( (that - today).days, that )
    return None


# --------------------------------------------------------------------------
# Rules：每条 rule 接收拉取的聚合数据，返回 list[EvalItem]
# --------------------------------------------------------------------------

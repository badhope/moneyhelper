"""现金流计算共用：日期解析、分位数、月份键与区间。"""

from __future__ import annotations

import math
from datetime import date
from typing import Any


def _parse_date(raw: Any) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _quantile(values: list[float], q: float) -> float:
    """线性插值分位数（与 numpy.percentile 默认口径一致）。"""
    if not values:
        return 0.0
    arr = sorted(values)
    if len(arr) == 1:
        return arr[0]
    pos = (len(arr) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return arr[int(pos)]
    return arr[lo] + (arr[hi] - arr[lo]) * (pos - lo)


def _month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def _month_range(start: date, end: date) -> list[str]:
    """生成 [start, end] 之间的月份键（含头尾）。"""
    out: list[str] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out

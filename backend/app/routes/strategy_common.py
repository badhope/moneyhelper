"""策略路由共用小工具：只放被两个以上子域复用的纯函数。"""

from __future__ import annotations

from datetime import date


def _months_ago(n: int) -> str:
    """n 个月前的 1 号（YYYY-MM-01），用于近 N 月回退窗口。"""
    today = date.today()
    y, m = today.year, today.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y:04d}-{m:02d}-01"

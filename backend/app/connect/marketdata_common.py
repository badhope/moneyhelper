"""公开行情源共用：UA 与数值解析（千分位/NaN 一律归 None）。"""

from __future__ import annotations

from typing import Any

_UA = "Mozilla/5.0 (moneyhelper connect-hub)"


def _num(raw: Any) -> float | None:
    try:
        v = float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # 过滤 NaN

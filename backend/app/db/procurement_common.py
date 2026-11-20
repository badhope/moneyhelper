"""采购/应付共享小工具：金额分→元换算、日期合法性校验。"""

from __future__ import annotations

from datetime import date
from typing import Any


def _amount(data: dict[str, Any]) -> dict[str, Any]:
    result = dict(data)
    for key in ("amount_cents", "tax_cents"):
        if key in result:
            result[key.replace("_cents", "")] = round(
                int(result.get(key) or 0) / 100, 2
            )
    return result


def _parse_date(value: Any, field: str = "日期") -> str:
    try:
        return date.fromisoformat(str(value or "").strip()).isoformat()
    except ValueError:
        raise ValueError(f"{field}需为 YYYY-MM-DD") from None

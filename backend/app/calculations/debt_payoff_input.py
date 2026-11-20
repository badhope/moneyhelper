"""债务入参归一：dict/DebtItem 混合输入 → DebtItem 列表，数值字段兜底校验。"""

from __future__ import annotations

from typing import Any

from .debt_payoff_types import DebtItem


def _coerce_items(debts: list[dict[str, Any]] | list[DebtItem]) -> list[DebtItem]:
    """把 dict 列表转成 DebtItem，并拒绝重名。

    重名必须拒绝而不是覆盖：按名字做 dict 时后者会顶掉前者，本金凭空消失
    （实测两笔都叫「信用卡」时 1.5 万本金只剩 5000，且无任何提示）。
    """
    items: list[DebtItem] = []
    for d in debts:
        if isinstance(d, DebtItem):
            items.append(d)
            continue
        if not isinstance(d, dict):
            raise ValueError("负债项必须是对象（含 name/balance/rate/min_payment）")
        # 显式取值而不是 `or 0`：空串/空列表是明显的输入错误，
        # 静默当 0 会产出「这笔债已还清」的误导结论。
        for key in ("balance", "rate", "min_payment", "monthly"):
            raw = d.get(key)
            if raw is None:
                continue
            if isinstance(raw, (list, dict, tuple, bool)):
                raise ValueError(f"{d.get('name') or '负债'}：{key} 必须是数字")
            try:
                float(raw)
            except (TypeError, ValueError, OverflowError):
                raise ValueError(f"{d.get('name') or '负债'}：{key} 必须是数字或超出范围") from None
        items.append(
            DebtItem(
                name=str(d.get("name") or ""),
                balance=_num_or(d.get("balance"), 0.0, "balance"),
                rate=_num_or(d.get("rate"), 0.0, "rate"),
                min_payment=_num_or(d.get("min_payment"), _num_or(d.get("monthly"), 0.0, "monthly"), "min_payment"),
            )
        )
    if not items:
        raise ValueError("至少需要一笔负债")
    names = [i.name for i in items]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ValueError(f"负债名称重复：{'、'.join(dupes)}（名称用于区分每一笔，必须唯一）")
    return items

def _num_or(raw: Any, default: float, field_name: str) -> float:
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{field_name} 必须是数字或超出范围") from None

"""复式总账纯计算：金额转分、逐行校验、借贷平衡。

不碰数据库/网络，便于单测。金额统一用整数分，避免浮点累计误差；
输入允许字符串/数字，统一按 Decimal(str) + ROUND_HALF_UP 到分。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

GL_ACCOUNT_TYPES = ("asset", "liability", "equity", "income", "expense")
GL_NORMAL_BALANCE = {
    "asset": "debit",
    "expense": "debit",
    "liability": "credit",
    "equity": "credit",
    "income": "credit",
}


def to_cents(value: Any) -> int:
    """把金额转成整数分；拒绝空值、非数字、NaN/Inf 和负数。"""
    if value is None or value == "":
        raise ValueError("金额不能为空")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"金额不是有效数字：{value!r}") from None
    if not amount.is_finite():
        raise ValueError("金额不能是 NaN 或无穷")
    if amount < 0:
        raise ValueError("借方/贷方金额不能为负")
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def line_totals(lines: Any) -> tuple[int, int]:
    """校验分录行并返回 (借方分, 贷方分)。

    每行必须且只能有借方或贷方之一大于 0；行数至少 2；总额不能为 0。
    """
    if not isinstance(lines, list) or len(lines) < 2:
        raise ValueError("凭证至少需要 2 条分录行")
    debit_total = 0
    credit_total = 0
    for idx, line in enumerate(lines, 1):
        if not isinstance(line, dict):
            raise ValueError(f"第 {idx} 行必须是对象")
        debit = to_cents(line.get("debit", 0))
        credit = to_cents(line.get("credit", 0))
        if (debit > 0) == (credit > 0):
            raise ValueError(f"第 {idx} 行必须且只能填写借方或贷方")
        debit_total += debit
        credit_total += credit
    if debit_total == 0 and credit_total == 0:
        raise ValueError("凭证金额不能为 0")
    return debit_total, credit_total


def assert_balanced(lines: Any) -> int:
    """校验借贷平衡，返回平衡后的借方分。"""
    debit, credit = line_totals(lines)
    if debit != credit:
        raise ValueError(
            f"借贷不平衡：借方 {debit / 100:.2f}，贷方 {credit / 100:.2f}"
        )
    return debit

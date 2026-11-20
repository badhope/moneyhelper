"""税务核算共用数值口径：ROUND_HALF_UP 到分/到指定位数。"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def _round(value: float, ndigits: int = 2) -> float:
    """金额/税率的四舍五入（ROUND_HALF_UP）。

    中国税务实务按四舍五入到分；Python 内置 round() 是银行家舍入
    （round(2.675, 2) == 2.67），在税额边界会产生分位差异。这里统一走
    Decimal(str(value))，避免二进制浮点尾差，并显式指定舍入模式。
    """
    quant = Decimal("1").scaleb(-ndigits)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))

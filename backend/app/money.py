"""金额换算的单一实现：分 ↔ 元。

## 为什么有这个文件

账务内部一律用「整数分」存储，展示层需要「元」。拆分 db 层时，这套换算被
复制成了多份，且三种写法并存：

    round(int(cents or 0) / 100, 2)              —— float 元（gl / banking / procurement）
    f"{int(c) // 100}.{int(c) % 100:02d}"        —— 精确字符串元（凭证行 / 应付款）

字符串写法是为了绕开浮点误差（1.005 之类），float 写法是为了前端直接拿数字。
两种输出都是合理的，但**实现必须唯一**：四舍五入规则改一次就要改四处，
漏改就会出现「凭证写 100.00、列表显示 100.01」这类对不上的账。

因此这里固定两个出口，语义写清楚，谁需要什么就拿什么。
"""

from __future__ import annotations

from typing import Any


def yuan(cents: Any) -> float:
    """整数分 → 浮点元（2 位小数）。用于展示/JSON 数值，不用于凭证落库。"""
    return round(int(cents or 0) / 100, 2)


def yuan_str(cents: Any) -> str:
    """整数分 → 精确字符串元（`1234` → `"12.34"`）。用于凭证金额、对外文本。"""
    value = int(cents or 0)
    sign = "-" if value < 0 else ""
    value = abs(value)
    return f"{sign}{value // 100}.{value % 100:02d}"

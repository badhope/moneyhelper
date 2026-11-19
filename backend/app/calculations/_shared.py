"""calculation 包内共享的纯函数。

## 为什么有这个文件

拆分 calculations 时，同一份实现被复制到不同模块：

- `_sma()`  —— backtest.py 与 strategies.py 各一份（简单移动均线，逐字重复）
- `_t()`    —— accounts.py 与 decisions.py 各一份（中英文案选择）

两份都是纯函数、无状态，放在包里共用一个实现即可。更重要的原因不是省
十几行代码，而是**口径唯一**：均线算法一旦有人改其中一份（比如改成指数
加权），两个出口（回测/策略）就会给出不同的收益曲线，而调用方看不出差异。
"""

from __future__ import annotations


def sma(values: list[float], window: int) -> list[float | None]:
    """简单移动均线；前 `window-1` 个点无值（None），不足窗口长度时全 None。"""
    out: list[float | None] = [None] * len(values)
    if window <= 0 or len(values) < window:
        return out
    acc = 0.0
    for i, v in enumerate(values):
        acc += v
        if i >= window:
            acc -= values[i - window]
        if i >= window - 1:
            out[i] = acc / window
    return out


def pick_lang(lang: str | None, zh: str, en: str) -> str:
    """按语言码返回文案：`en*` 开头取英文，其余取中文。"""
    return en if str(lang).lower().startswith("en") else zh

"""数值解析的唯一入口。

同一个"把原始值转成 float、坏了就返回默认值"的助手，此前在
`analysis_views`、`quotes_sources`、`financial_statements_metrics`、
`technical_indicators` 各写了一份：字段占位符（空串、`-`、布尔）处理不一致，
后来者在行情里修了负值、在指标里修了 `-` 占位，另一个文件却仍是老样子。
四份实现的差异只在"解析失败返回什么"，所以收敛成 `default` 参数。
"""

from __future__ import annotations

from typing import Any


def to_float(raw: Any, default: float | None = None) -> float | None:
    """宽松解析数值：缺失/占位符/非数字返回 default；0 与负数合法。

    布尔值单独拦掉：`float(True)` 会得 1.0，把"标记位"当成金额。
    """
    if raw is None or raw == "" or raw == "-" or isinstance(raw, bool):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default

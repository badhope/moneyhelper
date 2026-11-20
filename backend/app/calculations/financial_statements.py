"""财报分析门面：指标 / 杜邦与入口 / 预警 / 报告文本各成一模块。

纯函数、无 I/O；阈值常量只在预警模块内使用，避免"阈值散落"。
"""

from __future__ import annotations

from .financial_statements_alerts import _build_alerts  # noqa: F401
from .financial_statements_analysis import _dupont, analyze_statements  # noqa: F401
from .financial_statements_metrics import (  # noqa: F401
    _num,
    _pct,
    _ratio,
    _yoy,
    compute_period_metrics,
)
from .financial_statements_report import _fmt, _report_text  # noqa: F401

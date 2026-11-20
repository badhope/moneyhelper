"""现金流门面：预测 / 订阅识别 / 异常支出。

纯函数，输入交易日列表；样本不足时明确返回 note，不给假预测。
"""

from __future__ import annotations

__all__ = ["cashflow_forecast", "detect_anomalies", "detect_subscriptions"]

from .cashflow_detect import detect_anomalies, detect_subscriptions  # noqa: F401,E402
from .cashflow_forecast import cashflow_forecast  # noqa: F401,E402
from .cashflow_rules import (  # noqa: F401,E402
    MIN_MONTHS_FOR_FORECAST,
    MIN_SAMPLES_FOR_ANOMALY,
    MIN_SAMPLES_FOR_SUBSCRIPTION,
    SUBSCRIPTION_PERIODS,
)
from .cashflow_util import _month_key, _month_range, _parse_date, _quantile  # noqa: F401,E402

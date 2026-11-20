"""现金流识别阈值：最少月份、订阅样本数、周期窗口。"""

from __future__ import annotations

MIN_MONTHS_FOR_FORECAST = 2
MIN_SAMPLES_FOR_SUBSCRIPTION = 3
MIN_SAMPLES_FOR_ANOMALY = 4

SUBSCRIPTION_PERIODS = (
    ("monthly", 25, 35),
    ("quarterly", 85, 100),
    ("yearly", 350, 380),
)

"""技术指标参数：窗口、周期与信号上限（口径唯一的真源）。"""

from __future__ import annotations

MA_WINDOWS = (5, 10, 20, 60)
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
RSI_PERIOD = 14
BOLL_PERIOD = 20
BOLL_STD = 2.0
KDJ_N = 9
KDJ_K = 3
KDJ_D = 3
MAX_SIGNALS = 12  # 单次分析最多返回的信号条数（超出按重要程度 + 新近度截断）

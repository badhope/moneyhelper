"""策略回测门面：序列准备见 backtest_series，双均线/定投各自成模块，报告模板在 backtest_report。

纯函数、无 I/O；K 线由 quotes 层负责，这里只吃价格序列。
"""

from __future__ import annotations

from .backtest_dca import backtest_dca  # noqa: F401 — 对外同名导出
from .backtest_ma import backtest_ma_cross  # noqa: F401 — 对外同名导出
from .backtest_report import (  # noqa: F401 — 对外同名导出
    backtest_text,
    run_backtest,
)
from .backtest_series import (  # noqa: F401 — 对外同名导出
    DCA_DEFAULT_FREQ,
    DCA_MIN_DAYS,
    DEFAULT_COST,
    MA_CROSS_MIN_DAYS,
    TRADING_DAYS,
    _position_size,
    prepare_series,
    series_from_points,
)

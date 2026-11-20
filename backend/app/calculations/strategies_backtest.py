"""策略回测门面：执行引擎、网格与信号策略按模块拆开，对外名字不变。

信号与执行分离：每个策略只产出目标仓位，由统一引擎跑成本/整手/次日成交/风控。
"""

from __future__ import annotations

from .strategies_bt_core import (  # noqa: F401 — 对外同名导出
    _benchmark,
    _benchmark_curve,
    _metrics,
    _r2,
    run_position_backtest,
)
from .strategies_bt_grid import backtest_grid  # noqa: F401 — 对外同名导出
from .strategies_bt_signals import (  # noqa: F401 — 对外同名导出
    backtest_momentum,
    backtest_trend,
    backtest_vol_target,
)

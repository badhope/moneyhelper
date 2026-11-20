"""策略扩展包：指标见 strategies_indicators，回测见 strategies_backtest。

信号与执行分离：每个策略只产出目标仓位，由统一执行引擎跑成本/整手/次日成交/风控。
无前视偏差：第 i 天信号只用 closes[:i+1]，成交价用 closes[i+1]。
"""

from __future__ import annotations

from .strategies_backtest import (  # noqa: F401,E402
    _benchmark,
    _benchmark_curve,
    _metrics,
    _r2,
    backtest_grid,
    backtest_momentum,
    backtest_trend,
    backtest_vol_target,
    run_position_backtest,
)
from .strategies_indicators import (  # noqa: F401,E402
    TRADING_DAYS,
    atr,
    donchian,
    rolling_vol,
)

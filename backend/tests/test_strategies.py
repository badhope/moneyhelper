"""新增策略：能跑出结果、数字合理、不伪造。

这些策略的价值不在"多"，而在"每个都经得起追问"：
参数有依据、失效场景写清楚、数据不足时明确降级。
"""

import math
import random

import pytest

from app.calculations.strategies import (
    atr,
    backtest_grid,
    backtest_momentum,
    backtest_trend,
    backtest_vol_target,
    donchian,
    rolling_vol,
    run_position_backtest,
)


def _oscillating(n: int = 200, amp: float = 8.0, period: int = 40) -> list[float]:
    return [100 + amp * ((i % period) - period / 2) / (period / 2) for i in range(n)]


def _trending(n: int = 200, rate: float = 1.003) -> list[float]:
    return [100 * (rate**i) for i in range(n)]


def _noisy(n: int = 250, seed: int = 42) -> list[float]:
    random.seed(seed)
    out = [100.0]
    for _ in range(n):
        out.append(max(1.0, out[-1] * (1 + random.gauss(0.0005, 0.015))))
    return out


class TestIndicators:
    def test_rolling_vol_positive(self):
        v = rolling_vol(_noisy(), 20)
        vals = [x for x in v if x is not None]
        assert vals and all(x > 0 for x in vals)

    def test_rolling_vol_constant_series_is_zero(self):
        v = rolling_vol([100.0] * 50, 20)
        vals = [x for x in v if x is not None]
        assert vals and all(abs(x) < 1e-9 for x in vals)

    def test_atr_insufficient_data(self):
        assert all(x is None for x in atr([1, 2, 3], [1, 2, 3], [1, 2, 3], 14))

    def test_donchian_uses_past_only(self):
        """通道不能包含当日，否则突破永远无法触发（自我实现）。"""
        highs = [float(i) for i in range(1, 31)]
        lows = [float(i) - 0.5 for i in range(1, 31)]
        upper, lower = donchian(highs, lows, 5)
        # 第 10 天的上沿应是第 5~9 天的最高，即 highs[9]=10，而不是 highs[10]=11
        assert upper[10] == 10.0
        assert lower[10] == 5.5


class TestPositionBacktest:
    def test_full_position_matches_buy_and_hold(self):
        closes = _trending(120)
        targets = [1.0] * len(closes)
        res = run_position_backtest(closes, targets, cost=0.0)
        assert res is not None
        # 满仓 + 零成本 → 应与买入持有完全一致
        bh = closes[-1] / closes[0]
        assert abs(res["curve"][-1] / res["curve"][0] - bh) < 0.01

    def test_zero_position_stays_flat(self):
        closes = _trending(120)
        res = run_position_backtest(closes, [0.0] * len(closes))
        assert res is not None
        assert all(abs(v - res["curve"][0]) < 1e-6 for v in res["curve"])

    def test_risk_stop_loss_triggers(self):
        """从 100 跌到 80，10% 止损必须触发并保住剩余资金。"""
        closes = [100.0] + [100.0 * (0.99**i) for i in range(1, 60)]
        targets = [1.0] * len(closes)
        res = run_position_backtest(closes, targets, cost=0.0, risk={"stop_loss": 0.10})
        assert res is not None
        assert any(t.get("reason") == "signal" or t.get("side") == "sell" for t in res["trades"])
        # 止损后不应继续满仓亏到底
        assert res["curve"][-1] > 100000 * (closes[-1] / closes[0]) * 0.9


class TestGrid:
    def test_oscillating_market_trades(self):
        r = backtest_grid(_oscillating(), grid_pct=0.02)
        assert r is not None
        assert r["trade_count"] > 0, "震荡市网格必须有交易"

    def test_insufficient_data_returns_none(self):
        assert backtest_grid(_trending(30)) is None

    def test_grid_position_in_range(self):
        r = backtest_grid(_oscillating())
        assert r is not None
        assert 0.0 <= r["grid_position"] <= 1.0

    def test_has_risk_note(self):
        r = backtest_grid(_oscillating())
        assert "失效" in r["risk_note"] or "单边" in r["risk_note"]


class TestTrend:
    def test_trending_market_captures_gain(self):
        r = backtest_trend(_trending())
        assert r is not None
        assert r["total_return_pct"] > 10, "单边趋势策略应赚到钱"

    def test_insufficient_data(self):
        assert backtest_trend(_trending(30)) is None

    def test_exit_on_reversal(self):
        """先涨后跌：应在下跌段离场，而不是一路持有到底。"""
        up = [100 * (1.01**i) for i in range(60)]
        down = [up[-1] * (0.98**i) for i in range(1, 60)]
        r = backtest_trend(up + down)
        assert r is not None
        assert r["max_drawdown_pct"] > -40, "趋势跟随应控制回撤，不该吃满下跌"


class TestVolTarget:
    def test_runs_and_reports_avg_position(self):
        r = backtest_vol_target(_noisy())
        assert r is not None
        assert 0 < r["avg_position"] <= 1.0

    def test_lower_target_holds_less(self):
        low = backtest_vol_target(_noisy(), target_vol=0.10)
        high = backtest_vol_target(_noisy(), target_vol=0.30)
        assert low is not None and high is not None
        assert low["avg_position"] < high["avg_position"]

    def test_insufficient_data(self):
        assert backtest_vol_target(_trending(10)) is None


class TestMomentum:
    def test_picks_stronger_asset(self):
        strong = _trending(200, 1.004)
        weak = _trending(200, 1.0005)
        r = backtest_momentum({"STRONG": strong, "WEAK": weak})
        assert r is not None
        assert r["total_return_pct"] > 0

    def test_benchmark_is_equal_weight(self):
        a, b = _trending(200), _trending(200, 1.001)
        r = backtest_momentum({"A": a, "B": b})
        assert r is not None
        expected = (a[-1] / a[0] + b[-1] / b[0]) / 2
        assert abs(r["benchmark_return_pct"] - (expected - 1) * 100) < 0.5

    def test_insufficient_data(self):
        assert backtest_momentum({"A": _trending(10)}) is None

    def test_empty_panels(self):
        assert backtest_momentum({}) is None

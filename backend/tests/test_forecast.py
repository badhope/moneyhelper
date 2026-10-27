"""预测引擎单测（v4.1 forecast.py）。"""

from __future__ import annotations

import pytest
from app.calculations.forecast import (
    annualized_volatility,
    forecast,
    forecast_text,
    linear_trend,
    monte_carlo_gbm,
)


def _uptrend(n: int = 90, start: float = 100.0, step: float = 0.3) -> list[float]:
    """稳定上行序列：100 + i*0.3 + 微小正弦扰动（保证收益率非全同）。"""
    import math

    return [start + i * step + math.sin(i / 7.0) for i in range(n)]


def _noise(n: int = 90, start: float = 100.0) -> list[float]:
    """随机游走序列（固定随机种子，可复现）。"""
    import random

    rng = random.Random(7)
    vals = [start]
    for _ in range(n - 1):
        vals.append(max(1.0, vals[-1] * (1.0 + rng.gauss(0.0, 0.01))))
    return vals


class TestLinearTrend:
    def test_slope_sign(self):
        trend, slope, _ = linear_trend(_uptrend(), 5)
        assert trend is not None and slope is not None
        assert slope > 0
        assert len(trend) == 5
        # 外推应从最后拟合点附近起步，方向与斜率一致
        assert trend[0] > 0

    def test_down_trend(self):
        vals = list(reversed(_uptrend(60)))
        _trend, slope, _ = linear_trend(vals, 5)
        assert slope is not None and slope < 0

    def test_insufficient(self):
        assert linear_trend([1.0], 5) is None

    def test_flat_series(self):
        trend, slope, _ = linear_trend([10.0] * 40, 5)
        assert slope == pytest.approx(0.0, abs=1e-9)
        assert all(abs(v - 10.0) < 1e-6 for v in trend)


class TestVolatility:
    def test_uptrend_vol(self):
        v = annualized_volatility(_uptrend())
        # 稳定上行序列年化波动率应显著小于随机游走
        assert v is not None and 0 < v < 50

    def test_noise_vol(self):
        v = annualized_volatility(_noise())
        assert v is not None and v > 5

    def test_insufficient(self):
        assert annualized_volatility([100.0, 101.0]) is None

    def test_constant(self):
        assert annualized_volatility([10.0] * 40) is None


class TestMonteCarlo:
    def test_reproducible_seed(self):
        a = monte_carlo_gbm(_noise(), 10, seed=42)
        b = monte_carlo_gbm(_noise(), 10, seed=42)
        assert a is not None and b is not None
        assert a["median"] == b["median"]
        assert a["p5"] == b["p5"]

    def test_band_order(self):
        m = monte_carlo_gbm(_noise(), 15)
        assert m is not None
        for t in range(15):
            assert m["p5"][t] <= m["median"][t] <= m["p95"][t]

    def test_length(self):
        m = monte_carlo_gbm(_noise(), 8)
        assert m is not None and len(m["median"]) == 8

    def test_insufficient(self):
        assert monte_carlo_gbm([1.0, 2.0], 5) is None


class TestForecast:
    def test_full_shape(self):
        dates = [f"2026-01-{i + 1:02d}" for i in range(90)]
        f = forecast(_uptrend(), dates=dates, horizon=10)
        assert f is not None
        assert f["horizon"] == 10
        assert len(f["dates"]) == 100
        assert len(f["close"]) == 100
        # 实际部分有值，未来部分为 None
        assert f["close"][89] is not None and f["close"][90] is None
        # 区间：实际部分 None，未来部分有值
        assert f["median"][89] is None and f["median"][90] is not None
        assert f["p5"][95] <= f["median"][95] <= f["p95"][95]
        assert f["bias"] in ("up", "down", "neutral")
        assert f["last_close"] > 0
        assert "不构成投资建议" in f["note"]

    def test_uptrend_bias_up(self):
        f = forecast(_uptrend(), horizon=5)
        assert f is not None and f["bias"] == "up"

    def test_downtrend_bias_down(self):
        vals = list(reversed(_uptrend(90)))
        f = forecast(vals, horizon=5)
        assert f is not None and f["bias"] == "down"

    def test_mean_reversion(self):
        # 末端高于 20 日均线 → 正偏离
        vals = _uptrend(90)
        f = forecast(vals, horizon=5)
        assert f is not None and f["mean_reversion_pct"] is not None

    def test_insufficient(self):
        assert forecast([100.0] * 10, horizon=5) is None

    def test_text(self):
        f = forecast(_uptrend(), horizon=10)
        assert f is not None
        t = forecast_text(f, "zh")
        assert "统计情景" in t
        assert "不构成投资建议" in t or "不构成" in t

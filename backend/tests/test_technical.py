"""技术指标与信号引擎单测（v4.0 投研模块）。"""

from __future__ import annotations

import math

import pytest
from app.calculations.technical import (
    bollinger,
    build_signals,
    ema,
    kdj,
    macd,
    rsi,
    sma,
    technical_analysis,
    trend_text,
)


def _points(closes: list[float]) -> list[dict]:
    out = []
    for i, c in enumerate(closes):
        out.append(
            {
                "date": f"2026-01-{i + 1:02d}",
                "open": c,
                "close": c,
                "high": c * 1.01,
                "low": c * 0.99,
                "volume": 1_000_000 + i,
            }
        )
    return out


class TestIndicators:
    def test_sma_window(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        ma = sma(vals, 3)
        assert ma[0] is None and ma[1] is None
        assert ma[2] == pytest.approx(2.0)
        assert ma[4] == pytest.approx(4.0)

    def test_ema_simple(self):
        vals = [10.0, 11.0, 12.0, 13.0, 14.0]
        e = ema(vals, 3)
        # span 预热：seed 落在第 span 个位置（index 2）
        assert e[2] == pytest.approx((10 + 11 + 12) / 3, abs=1e-4)
        assert e[3] is not None
        assert e[4] is not None

    def test_macd_shape(self):
        vals = [float(i) for i in range(1, 40)]
        out = macd(vals)
        assert len(out["dif"]) == len(vals)
        # 前 slow-1 根（index<25）dif 为 None，此后有值
        assert out["dif"][25] is not None
        # DEA 需要 9 根 dif 预热 → hist 首个非 None 在 index 25+8
        assert out["hist"][33] is not None
        assert out["hist"][25] is None

    def test_rsi_bounds(self):
        vals = [float(i) for i in range(1, 30)]
        out = rsi(vals)
        for v in out[14:]:
            assert 0 <= v <= 100

    def test_bollinger_bands(self):
        vals = [100.0] * 25
        out = bollinger(vals)
        assert out["mid"][24] == pytest.approx(100.0)
        assert out["upper"][24] == pytest.approx(100.0)
        assert out["lower"][24] == pytest.approx(100.0)

    def test_kdj_bounds(self):
        pts = _points([float(i) for i in range(1, 30)])
        out = kdj(pts)
        for i in range(8, 29):
            assert 0 <= out["k"][i] <= 100
            assert 0 <= out["d"][i] <= 100


class TestTechnicalAnalysis:
    def test_insufficient_data_returns_none(self):
        assert technical_analysis(_points([100.0] * 10)) is None

    def test_bull_trend_detects_ma_cross(self):
        # 先跌后涨的震荡序列 → 必然出现金叉/死叉信号
        closes = [100 + 5 * math.sin(i / 3.0) + i * 0.1 for i in range(120)]
        ta = technical_analysis(_points(closes))
        assert ta is not None
        assert ta["point_count"] == 120
        assert ta["last"]["close"] == pytest.approx(closes[-1], abs=1e-3)
        assert len(ta["signals"]) >= 1
        assert ta["bias"] in ("bull", "bear", "neutral")
        # 信号带日期
        assert all(s["date"] for s in ta["signals"])

    def test_trend_text(self):
        closes = [100 + 5 * math.sin(i / 3.0) + i * 0.1 for i in range(120)]
        ta = technical_analysis(_points(closes))
        assert ta is not None
        text = trend_text(ta, "zh")
        assert "信号" in text
        assert "收盘" in text


class TestSignals:
    def test_build_signals_detects_ma_cross(self):
        # 前 30 根下跌，后 30 根上涨 → 至少一次 MA5 上穿 MA20
        closes = list(range(100, 70, -1)) + list(range(71, 101))
        pts = _points(closes)
        ma5 = sma(closes, 5)
        ma10 = sma(closes, 10)
        ma20 = sma(closes, 20)
        dif = [None] * len(closes)
        dea = [None] * len(closes)
        rsi_vals = [50.0] * len(closes)
        boll = {"upper": [None] * len(closes), "lower": [None] * len(closes), "mid": [None] * len(closes)}
        kdj_vals = {"k": [50.0] * len(closes), "d": [50.0] * len(closes), "j": [50.0] * len(closes)}
        sig = build_signals(pts, ma5, ma10, ma20, dif, dea, rsi_vals, boll, kdj_vals)
        assert any(s["code"] == "MA_CROSS" and s["side"] == "bull" for s in sig)

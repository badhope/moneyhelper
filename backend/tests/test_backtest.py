"""策略回测引擎单测（v4.0 投研模块）。"""

from __future__ import annotations

import pytest
from app.calculations.backtest import (
    backtest_dca,
    backtest_ma_cross,
    backtest_text,
    run_backtest,
)


def _closes() -> list[float]:
    # 人造上涨行情：适合验证回测基本口径（不验证策略优劣，只验证计算正确）
    return [100.0 * (1 + i * 0.002) for i in range(120)]


class TestMaCross:
    def test_returns_metrics(self):
        closes = _closes()
        r = backtest_ma_cross(closes)
        assert r is not None
        assert r["strategy"] == "ma_cross"
        assert r["total_return_pct"] is not None
        assert r["max_drawdown_pct"] is not None and r["max_drawdown_pct"] <= 0
        assert r["final_equity"] > 0
        assert len(r["curve"]["strategy"]) == len(closes)
        assert len(r["curve"]["benchmark"]) == len(closes)

    def test_insufficient_data(self):
        assert backtest_ma_cross([100.0] * 30) is None

    def test_benchmark_sanity(self):
        closes = _closes()
        r = backtest_ma_cross(closes)
        # 单边上涨行情下，全仓持有的基准收益应显著为正
        assert r["benchmark_return_pct"] > 5.0

    def test_trade_count_positive(self):
        # 震荡行情会触发多次买卖
        closes = [100 + 8 * (i % 7) for i in range(120)]
        r = backtest_ma_cross(closes)
        assert r is not None
        assert r["trade_count"] >= 1


class TestDca:
    def test_returns_metrics(self):
        closes = _closes()
        r = backtest_dca(closes, invest_amount=1000, freq_days=5)
        assert r is not None
        assert r["strategy"] == "dca"
        assert r["total_invested"] == pytest.approx(1000 * (120 // 5), abs=1000)
        assert r["final_value"] > 0
        assert r["total_return_pct"] is not None

    def test_insufficient_data(self):
        assert backtest_dca([100.0] * 10) is None


class TestDispatch:
    def test_run_backtest_dispatch(self):
        closes = _closes()
        assert run_backtest(closes, strategy="ma_cross") is not None
        assert run_backtest(closes, strategy="dca") is not None
        assert run_backtest(closes, strategy="unknown") is None

    def test_backtest_text(self):
        closes = _closes()
        r = backtest_ma_cross(closes)
        text = backtest_text(r, "zh")
        assert "回测" in text
        assert "不构成投资建议" in text

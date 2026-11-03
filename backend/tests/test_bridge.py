"""回测 → 模拟盘桥接：信号转换与样本外跟踪。

这套断言保护两件事：
  1. 信号必须来自真实回测曲线结构（curve.strategy），不能猜字段名；
  2. 跟踪结论必须可复现且分档正确——偏差大就要说「可能失效」，不能粉饰。
"""

from app.calculations.bridge import (
    TRACKING_BAD_PCT,
    TRACKING_WARN_PCT,
    plan_from_backtest,
    signals_from_backtest,
    tracking_report,
)


def _result(curve, dates=None):
    return {
        "strategy": "ma_cross",
        "total_return_pct": 12.5,
        "benchmark_return_pct": 8.0,
        "max_drawdown_pct": -9.3,
        "trade_count": 4,
        "curve": {"strategy": curve, "dates": dates or list(range(len(curve)))},
    }


class TestSignals:
    def test_emits_enter_then_exit_on_direction_change(self):
        sig = signals_from_backtest(_result([100, 101, 102, 101, 100]))
        actions = [s["action"] for s in sig]
        assert actions[0] == "enter"
        assert "exit" in actions

    def test_monotonic_rise_emits_single_enter(self):
        sig = signals_from_backtest(_result([100, 101, 102, 103]))
        assert [s["action"] for s in sig] == ["enter"]

    def test_monotonic_fall_emits_nothing(self):
        # 从第一根就下跌：从未建立仓位，不应凭空产生信号
        assert signals_from_backtest(_result([100, 99, 98])) == []

    def test_short_curve_returns_empty(self):
        assert signals_from_backtest(_result([100])) == []

    def test_flat_curve_does_not_thrash(self):
        # 完全持平的曲线：没有方向变化，不应反复进出
        assert signals_from_backtest(_result([100, 100, 100])) == []


class TestPlan:
    def test_plan_marks_approximation_and_caveats(self):
        plan = plan_from_backtest(_result([100, 101, 100]), "510300", 100000, "zh")
        assert plan["ok"] is True
        assert plan["approximation"] is True
        assert plan["caveats"], "必须向用户说明口径限制"
        assert plan["signal_count"] == len(plan["signals"])

    def test_plan_without_result_is_explicit_failure(self):
        out = plan_from_backtest(None, "510300", 100000, "zh")
        assert out["ok"] is False
        assert out["error"]

    def test_plan_passes_backtest_metrics_through(self):
        plan = plan_from_backtest(_result([100, 101]), "510300", 50000, "en")
        assert plan["summary"]["total_return_pct"] == 12.5
        assert plan["capital"] == 50000


class TestTracking:
    def test_identical_curves_have_zero_error(self):
        r = tracking_report([100, 110, 120], [100, 110, 120], 100, "zh")
        assert r["ok"] is True
        assert r["tracking_error_pct"] == 0
        assert r["direction_agreement_pct"] == 100.0
        assert r["verdict_key"] == "intact"

    def test_large_deviation_is_flagged_broken(self):
        # 模拟盘走平、回测大涨 → 偏差远超阈值
        r = tracking_report([100, 200, 300], [100, 100, 100], 100, "zh")
        assert r["tracking_error_pct"] >= TRACKING_BAD_PCT
        assert r["verdict_key"] == "broken"

    def test_mid_deviation_is_observation(self):
        # 平均值被起点 0 稀释，但当前/最大偏离超出容忍 → 必须判为需观察，
        # 不能因为「大部分时间贴合」就报 intact。
        bt = [100, 100 + TRACKING_WARN_PCT + 2, 100 + TRACKING_WARN_PCT + 2]
        pp = [100, 100, 100]
        r = tracking_report(bt, pp, 100, "zh")
        assert r["tracking_error_pct"] < TRACKING_WARN_PCT  # 均值确实偏低
        assert r["severity_pct"] >= TRACKING_WARN_PCT
        assert r["verdict_key"] in ("observe", "broken")

    def test_direction_disagreement_is_measured(self):
        r = tracking_report([100, 110, 120], [100, 90, 80], 100, "en")
        assert r["direction_agreement_pct"] == 0.0

    def test_insufficient_overlap_is_explicit(self):
        assert tracking_report([100], [100], 100)["ok"] is False
        assert tracking_report([], [], 100)["ok"] is False

    def test_zero_capital_is_rejected(self):
        assert tracking_report([100, 110], [100, 110], 0)["ok"] is False

    def test_thresholds_are_exposed(self):
        r = tracking_report([100, 101], [100, 101], 100)
        assert r["thresholds"]["warn"] == TRACKING_WARN_PCT
        assert r["thresholds"]["bad"] == TRACKING_BAD_PCT

    def test_report_is_deterministic(self):
        args = ([100, 110, 105], [100, 108, 106], 100, "zh")
        assert tracking_report(*args) == tracking_report(*args)

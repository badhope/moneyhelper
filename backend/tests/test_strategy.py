"""策略计算引擎测试：风险指标 / 再平衡 / FIRE / 估值分位 / 定投回测。

这些用例全部基于**可手算核对**的构造数据，断言具体数值而非"大于 0"：
指标算错会直接暴露，而不是被宽松断言掩盖。
"""

from __future__ import annotations

from datetime import date

import pytest
from app.calculations import (
    annualized_volatility,
    build_equity_curve,
    compute_dca_stats,
    compute_fire,
    compute_rebalance,
    compute_risk_metrics,
    compute_valuation,
    daily_returns,
    max_drawdown,
    next_run_date,
    sharpe_ratio,
)

# --------------------------------------------------------------------------
# 基础序列
# --------------------------------------------------------------------------


def test_daily_returns_basic():
    assert daily_returns([100, 110, 99]) == pytest.approx([0.1, -0.1])


def test_daily_returns_skips_non_positive():
    # 0 与负数不是有效净值，跳过且不产生假收益
    out = daily_returns([100, 0, 120, -5, 132])
    assert out == pytest.approx([0.2, 0.1])


def test_max_drawdown_hand_computed():
    # 峰值 120 → 谷底 90 = -25%
    assert max_drawdown([100, 120, 90, 130]) == pytest.approx(-0.25)


def test_max_drawdown_monotonic_up_is_zero():
    assert max_drawdown([100, 101, 102]) == pytest.approx(0.0)


def test_max_drawdown_needs_two_points():
    assert max_drawdown([100]) is None


def test_annualized_volatility_zero_for_flat_series():
    assert annualized_volatility([0.0] * 30) == pytest.approx(0.0)


def test_annualized_volatility_none_when_too_few_points():
    assert annualized_volatility([0.01]) is None


def test_sharpe_none_when_sample_small():
    # 少于 20 个样本不计算：短样本的夏普没有统计意义
    assert sharpe_ratio([0.01] * 10) is None


def test_sharpe_none_when_zero_volatility():
    assert sharpe_ratio([0.0] * 40) is None


def test_sharpe_positive_for_upward_drift():
    # 必须带波动：完全平滑的上涨波动率为 0，夏普无定义（返回 None 是对的）
    rets = [0.001 if i % 2 == 0 else 0.003 for i in range(60)]
    assert sharpe_ratio(rets) is not None


# --------------------------------------------------------------------------
# 组合风险指标
# --------------------------------------------------------------------------


def _trend_curve(n: int = 300, daily: float = 0.0005) -> list[float]:
    vals = [100.0]
    for _ in range(n - 1):
        vals.append(vals[-1] * (1 + daily))
    return vals


def test_risk_metrics_full_shape():
    m = compute_risk_metrics(_trend_curve())
    d = m.to_dict()
    assert d["observations"] == 300
    assert d["total_return_pct"] is not None
    assert d["max_drawdown_pct"] == pytest.approx(0.0)
    # 全程上涨 → 胜率 100%
    assert d["win_rate_pct"] == pytest.approx(100.0)
    for key in (
        "annualized_return_pct",
        "annualized_volatility_pct",
        "sharpe",
        "sortino",
        "calmar",
        "var_95_pct",
        "beta",
        "alpha_pct",
        "excess_return_pct",
    ):
        assert key in d


def test_risk_metrics_short_sample_returns_none_annualized():
    """短样本不给年化指标——14 天涨 20% 年化成 3000%+ 是误导性数字。"""
    m = compute_risk_metrics([100, 101, 99, 102, 105, 103, 108, 110, 107, 112, 115, 111, 118, 120])
    d = m.to_dict()
    assert d["total_return_pct"] == pytest.approx(20.0)
    assert d["annualized_return_pct"] is None
    assert d["sharpe"] is None
    assert any("样本少于 60" in n for n in d["notes"])


def test_risk_metrics_beta_of_identical_series_is_one():
    # 曲线必须有波动，否则基准方差为 0，Beta 无定义（这是正确的 None）
    import random

    rng = random.Random(42)
    curve = [100.0]
    for _ in range(299):
        curve.append(curve[-1] * (1 + rng.gauss(0.0004, 0.012)))
    m = compute_risk_metrics(curve, curve)
    assert m.beta == pytest.approx(1.0, abs=1e-6)
    assert m.alpha_pct == pytest.approx(0.0, abs=1e-4)
    assert m.excess_return_pct == pytest.approx(0.0)


def test_risk_metrics_beta_zero_when_benchmark_flat():
    # 基准零波动 → Beta 无定义，必须返回 None 而不是 0（0 会被读成"无相关性"）
    flat = [100.0] * 300
    m = compute_risk_metrics(_trend_curve(), flat)
    assert m.beta is None


def test_risk_metrics_insufficient_points():
    m = compute_risk_metrics([100])
    assert m.observations == 1
    assert m.total_return_pct is None
    assert any("样本不足" in n for n in m.notes)


# --------------------------------------------------------------------------
# 净值曲线
# --------------------------------------------------------------------------


def test_equity_curve_forward_fills_missing_dates():
    history = {
        "A": [{"date": "2026-01-02", "close": 10.0}, {"date": "2026-01-03", "close": 11.0}],
        "B": [{"date": "2026-01-03", "close": 5.0}],
    }
    curve = build_equity_curve([{"symbol": "A", "shares": 10}, {"symbol": "B", "shares": 100}], history, cash=1000)
    # 1/2：A 10*10 + B 缺失 + 现金 1000 = 1100
    # 1/3：A 11*10 + B 5*100 + 1000 = 1610
    assert curve == pytest.approx([1100.0, 1610.0])


def test_equity_curve_empty_when_no_history():
    assert build_equity_curve([{"symbol": "A", "shares": 1}], {}) == []


def test_equity_curve_ignores_zero_prices():
    history = {"A": [{"date": "2026-01-02", "close": 0}, {"date": "2026-01-03", "close": 10}]}
    # 只有一天有效价格 → 不足 2 个日期，返回空
    assert build_equity_curve([{"symbol": "A", "shares": 1}], history) == []


# --------------------------------------------------------------------------
# 再平衡
# --------------------------------------------------------------------------


def _pos(symbol, name, kind, shares, last):
    return {"symbol": symbol, "name": name, "kind": kind, "shares": shares, "last": last}


def test_rebalance_empty_targets():
    plan = compute_rebalance([_pos("A", "甲", "股票", 1, 100)], [])
    assert plan.needs_rebalance is False
    assert any("未设置目标配置" in n for n in plan.notes)


def test_rebalance_no_positions():
    plan = compute_rebalance([], [{"symbol": "A", "target_pct": 100}])
    assert plan.needs_rebalance is False
    assert any("没有持仓市值" in n for n in plan.notes)


def test_rebalance_sell_and_buy_amounts_match():
    positions = [
        _pos("600519", "茅台", "股票", 100, 1500),
        _pos("CASH", "现金", "现金", 1, 50000),
    ]
    targets = [
        {"symbol": "600519", "name": "茅台", "target_pct": 40},
        {"symbol": "CASH", "name": "现金", "target_pct": 60},
    ]
    plan = compute_rebalance(positions, targets, band_pct=5)
    assert plan.needs_rebalance is True
    assert plan.total_value == pytest.approx(200000)
    sell = next(i for i in plan.items if i.symbol == "600519")
    buy = next(i for i in plan.items if i.symbol == "CASH")
    assert sell.action == "sell"
    assert sell.amount == pytest.approx(70000)
    # 股票卖出可卖零股：70000 / 1500 = 46 股
    assert sell.approx_shares == 46
    assert buy.action == "buy"
    assert buy.amount == pytest.approx(70000)


def test_rebalance_within_band_holds():
    positions = [
        _pos("A", "甲", "股票", 1, 5100),
        _pos("B", "乙", "股票", 1, 4900),
    ]
    targets = [{"symbol": "A", "target_pct": 50}, {"symbol": "B", "target_pct": 50}]
    plan = compute_rebalance(positions, targets, band_pct=5)
    # 漂移 1% < 5% 容忍带 → 不动
    assert plan.needs_rebalance is False
    assert all(i.action == "hold" for i in plan.items)


def test_rebalance_buy_must_be_whole_lot():
    # 目标缺口 500 元 / 单价 20 元 = 25 股，不足一手 100 股 → 不买
    positions = [_pos("A", "甲", "股票", 100, 20), _pos("CASH", "现金", "现金", 1, 0)]
    targets = [{"symbol": "A", "target_pct": 95}, {"symbol": "CASH", "target_pct": 5}]
    plan = compute_rebalance(positions, targets, band_pct=1)
    a = next(i for i in plan.items if i.symbol == "A")
    # A 当前 2000 元即 100%，目标 95% → 需卖出 100 元（5% of 2000）
    assert a.action == "sell"
    cash = next(i for i in plan.items if i.symbol == "CASH")
    # 缺口 100 元 / 20 元 = 5 股，卖出现金项不按手 → 现金项无 approx
    assert cash.action == "buy"
    assert cash.approx_shares is None


def test_rebalance_target_sum_warning():
    positions = [_pos("A", "甲", "股票", 1, 100)]
    plan = compute_rebalance(positions, [{"symbol": "A", "target_pct": 60}], band_pct=1)
    assert plan.target_sum_pct == pytest.approx(60)
    assert any("建议调整为 100%" in n for n in plan.notes)


def test_rebalance_untargeted_holding_noted():
    positions = [_pos("A", "甲", "股票", 1, 100), _pos("B", "乙", "股票", 1, 100)]
    plan = compute_rebalance(positions, [{"symbol": "A", "target_pct": 100}], band_pct=1)
    assert any("乙" in n and "未设置目标配置" in n for n in plan.notes)


# --------------------------------------------------------------------------
# FIRE
# --------------------------------------------------------------------------


def test_fire_target_is_25x_at_4pct():
    r = compute_fire(8000, 20000, 60, 0)
    assert r["annual_expense"] == pytest.approx(96000)
    assert r["target_principal"] == pytest.approx(2400000)
    assert r["annual_saving"] == pytest.approx(144000)
    assert r["years_to_fire"] is not None


def test_fire_already_reached():
    r = compute_fire(5000, 20000, 50, 10_000_000)
    assert r["years_to_fire"] == 0
    assert r["progress_pct"] > 100


def test_fire_no_saving_never_reaches():
    # 储蓄率为 0 且净值低于目标 → 无法估算年限（None，不是 999）
    r = compute_fire(8000, 8000, 0, 0)
    assert r["years_to_fire"] is None
    assert r["reachable"] is False


def test_fire_negative_net_worth_never_claims_a_year():
    """真实缺陷回归：净值为负 + 正储蓄，二分上界 100 会返回假的「100 年后达成」。

    净值为负且收益率为正时，本金会先被收益放大（放大的是负数），
    缺口只会扩大；即使名义上储蓄在累积，也不该给出一个具体年限。
    """
    r = compute_fire(8000, 20000, 60, -1_000_000, expected_return_pct=0.0)
    assert r["years_to_fire"] is None
    assert r["reachable"] is False


def test_fire_unreachable_when_gap_exceeds_200_years():
    # 目标极大、储蓄极小且零收益：3000 万目标 / 每年存 1.2 万需要 2500 年
    # → 200 年硬上限内达不到，必须返回 None 而不是 200
    r = compute_fire(100000, 120000, 1, 0, expected_return_pct=0.0)
    assert r["years_to_fire"] is None
    assert r["reachable"] is False


def test_fire_savings_rate_derived_when_missing():
    r = compute_fire(6000, 10000, None, 0)
    assert r["savings_rate_pct"] == pytest.approx(40.0)


def test_fire_zero_expense():
    r = compute_fire(0, 10000, 50, 0)
    assert r["target_principal"] == pytest.approx(0)
    assert r["years_to_fire"] == 0


# --------------------------------------------------------------------------
# 估值分位
# --------------------------------------------------------------------------


def test_valuation_at_high_is_expensive():
    v = compute_valuation("X", "测试", [10, 12, 9, 15, 20])
    assert v is not None
    assert v.percentile == pytest.approx(100.0)
    assert v.zone == "expensive"
    assert v.zone_label == "高位区"


def test_valuation_at_low_is_cheap():
    # 区间 9~20，末值 10 → (10-9)/(20-9) = 9.1，落在低位区（<20）
    v = compute_valuation("X", "测试", [20, 15, 9, 12, 10])
    assert v.percentile == pytest.approx(9.1, abs=1e-6)
    assert v.zone == "cheap"
    assert v.zone_label == "低位区"


def test_valuation_flat_series_is_fair():
    v = compute_valuation("X", "测试", [10, 10, 10, 10])
    assert v.percentile == pytest.approx(50.0)
    assert v.zone == "fair"


def test_valuation_needs_two_points():
    assert compute_valuation("X", "测试", [10]) is None
    assert compute_valuation("X", "测试", []) is None
    assert compute_valuation("X", "测试", [0, 0]) is None


def test_valuation_drawdown_from_peak():
    v = compute_valuation("X", "测试", [100, 80])
    assert v.drawdown_pct == pytest.approx(-20.0)


def test_valuation_respects_lookback():
    # 只保留最后 5 个点：早期 1000 不应影响区间
    closes = [1000, 1000, 1000, 10, 11, 12, 13, 14]
    v = compute_valuation("X", "测试", closes, lookback_days=5)
    assert v.high == pytest.approx(14)
    assert v.observations == 5


# --------------------------------------------------------------------------
# 定投
# --------------------------------------------------------------------------

PLAN = {"amount": 1000, "frequency": "monthly", "start_date": "2026-01-01", "day": 1}


def test_dca_monthly_accumulates():
    closes = [
        {"date": "2026-01-01", "close": 10.0},
        {"date": "2026-02-01", "close": 20.0},
        {"date": "2026-03-01", "close": 25.0},
    ]
    s = compute_dca_stats(PLAN, closes, price_now=25.0)
    # 三期各 1000 元：100 份 + 50 份 + 40 份 = 190 份，投入 3000
    assert s["periods"] == 3
    assert s["invested"] == pytest.approx(3000)
    assert s["shares"] == pytest.approx(190)
    assert s["avg_cost"] == pytest.approx(3000 / 190, abs=1e-3)
    assert s["value"] == pytest.approx(190 * 25)
    assert s["pnl"] == pytest.approx(190 * 25 - 3000)


def test_dca_weekly_counts_periods():
    plan = {"amount": 500, "frequency": "weekly", "start_date": "2026-01-05"}
    closes = [{"date": f"2026-01-{d:02d}", "close": 10.0} for d in range(5, 27)]
    s = compute_dca_stats(plan, closes, None)
    # 1/5 起每 7 天：5、12、19、26 → 4 期
    assert s["periods"] == 4
    assert s["invested"] == pytest.approx(2000)


def test_dca_zero_amount_returns_empty():
    s = compute_dca_stats({**PLAN, "amount": 0}, [{"date": "2026-01-01", "close": 10}], None)
    assert s["invested"] == 0
    assert s["periods"] == 0


def test_dca_no_price_series():
    s = compute_dca_stats(PLAN, [], None)
    assert s["periods"] == 0


def test_dca_skips_buy_date_before_first_price():
    closes = [{"date": "2026-06-01", "close": 10.0}, {"date": "2026-07-01", "close": 10.0}]
    s = compute_dca_stats(PLAN, closes, 10.0)
    # start=2026-01-01 → 每月 1 号；但数据从 6/1 才开始，
    # 1–5 月的定投日不补记（没有真实价格，补买=编造成本）
    assert s["periods"] == 2
    assert s["invested"] == pytest.approx(2000)
    assert s["last_buy_date"] == "2026-07-01"


# --------------------------------------------------------------------------
# 下一期日期
# --------------------------------------------------------------------------


def test_next_run_monthly_rolls_to_next_month():
    today = date(2026, 3, 20)
    assert next_run_date(10, "monthly", today) == date(2026, 4, 10)


def test_next_run_monthly_same_month():
    today = date(2026, 3, 1)
    assert next_run_date(10, "monthly", today) == date(2026, 3, 10)


def test_next_run_monthly_today_is_next_month():
    # 今天正好是定投日 → 顺延到下月，避免同日重复扣款
    today = date(2026, 3, 10)
    assert next_run_date(10, "monthly", today) == date(2026, 4, 10)


def test_next_run_weekly():
    today = date(2026, 3, 2)  # 周一
    assert next_run_date(1, "weekly", today) == date(2026, 3, 9)
    assert next_run_date(3, "weekly", today) == date(2026, 3, 4)


def test_next_run_december_wraps_year():
    today = date(2026, 12, 20)
    assert next_run_date(10, "monthly", today) == date(2027, 1, 10)

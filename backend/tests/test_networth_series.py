"""净值序列与归因：口径必须可解释，缺数据必须明说。

核心保护点：
  1. 归因三项相加要能解释总变动（残差单独暴露，不硬凑）；
  2. 没有快照时不许用当前值反推历史（那是伪造）；
  3. 快照同日覆盖幂等。
"""

from app.networth_series import attribute, series


class TestSeries:
    def test_empty_is_explicit(self):
        out = series([])
        assert out["available"] is False
        assert "快照" in out["reason"]
        assert out["points"] == []

    def test_single_point_not_available(self):
        out = series([{"date": "2026-11-01", "net_worth": 100, "total_assets": 150,
                       "total_liabilities": 50}])
        assert out["count"] == 1
        assert out["available"] is False

    def test_two_points_compute_change(self):
        out = series([
            {"date": "2026-11-01", "net_worth": 100_000, "total_assets": 120_000,
             "total_liabilities": 20_000},
            {"date": "2026-11-02", "net_worth": 103_000, "total_assets": 123_000,
             "total_liabilities": 20_000},
        ])
        assert out["available"] is True
        assert out["change"] == 3000
        assert out["change_pct"] == 3.0

    def test_zero_start_has_no_pct(self):
        out = series([
            {"date": "2026-11-01", "net_worth": 0, "total_assets": 0, "total_liabilities": 0},
            {"date": "2026-11-02", "net_worth": 1000, "total_assets": 1000, "total_liabilities": 0},
        ])
        # 从 0 起算的百分比在数学上无定义，必须是 None 而不是 inf
        assert out["change_pct"] is None
        assert out["change"] == 1000


class TestAttribution:
    def test_savings_only(self):
        """市值不变、只把工资存进现金：变动应 100% 归因于净储蓄，且投资损益为 0。

        这是上一版公式的失败点：它把同一个 net_inflow 同时当成储蓄和投资投入，
        于是凭空产生 −5000 的投资损益，两项抵消后"看起来对"但归因错了。
        """
        out = attribute(
            start_net_worth=100_000, end_net_worth=105_000,
            start_market_value=80_000, end_market_value=80_000,
            net_inflow=5_000,
        )
        assert out["change"] == 5000
        assert out["savings"] == 5000
        assert out["investment_pnl"] == 0, "市值没涨，不该有投资损益"
        assert out["other"] == 0
        assert out["shares"]["savings_pct"] == 100.0

    def test_investment_gain_only(self):
        """没存钱、市值涨：变动应 100% 归因于投资损益。"""
        out = attribute(
            start_net_worth=100_000, end_net_worth=110_000,
            start_market_value=100_000, end_market_value=110_000,
            net_inflow=0,
        )
        assert out["investment_pnl"] == 10_000
        assert out["savings"] == 0
        assert abs(out["other"]) < 0.01

    def test_mixed_with_invested_inflow(self):
        """明确区分「存现金」与「转进投资账户」两种资金去向。"""
        out = attribute(
            start_net_worth=100_000, end_net_worth=112_000,
            start_market_value=80_000, end_market_value=87_000,
            net_inflow=8_000, invested_inflow=3_000,
        )
        # 储蓄 8k−3k=5k；投资损益 = 7k 市值变动 − 3k 新投入 = 4k；合计 9k
        assert out["savings"] == 5000
        assert out["investment_pnl"] == 4000
        assert out["change"] == 12_000
        # 残差 3k 必须如实暴露（未标记的现金流）
        assert abs(out["other"] - 3000) < 0.01

    def test_debt_repayment_increases_net_worth(self):
        out = attribute(
            start_net_worth=100_000, end_net_worth=110_000,
            start_market_value=100_000, end_market_value=100_000,
            net_inflow=0,
            start_liabilities=50_000, end_liabilities=40_000,
        )
        assert out["debt_effect"] == 10_000
        assert abs(out["other"]) < 0.01

    def test_residual_note_flags_large_gap(self):
        out = attribute(
            start_net_worth=100_000, end_net_worth=200_000,
            start_market_value=0, end_market_value=0,
            net_inflow=0,
        )
        assert out["other"] == 100_000
        assert "残差" in out["note"]

    def test_zero_change_has_null_shares(self):
        out = attribute(
            start_net_worth=100_000, end_net_worth=100_000,
            start_market_value=50_000, end_market_value=50_000,
            net_inflow=0,
        )
        assert out["change"] == 0
        assert out["shares"]["savings_pct"] is None
        assert out["residual_pct"] is None

    def test_components_sum_to_change(self):
        """不变量：三项 + 残差 = 总变动（任何情况下都不能不平）。"""
        out = attribute(
            start_net_worth=123_456, end_net_worth=135_790,
            start_market_value=90_000, end_market_value=98_500,
            net_inflow=4_321,
            start_liabilities=12_000, end_liabilities=11_000,
        )
        total = out["savings"] + out["investment_pnl"] + out["debt_effect"] + out["other"]
        assert abs(total - out["change"]) < 0.02

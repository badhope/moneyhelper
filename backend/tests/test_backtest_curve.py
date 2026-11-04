"""回测口径回归：定投曲线必须反映真实资金占用，不能靠"越投越多"造出假收益。

历史缺陷（实测数据）：
  资金曲线只累加已投入份额的市值、不含剩余现金，于是曲线从首笔投入的
  几百元一路爬升到全部投入的市值，「首尾之比」被当成收益率：
    单边下跌 62% 的行情 → 年化 +44887%、夏普 243、最大回撤 −1.99%
  三个数字全部方向相反，会直接误导用户。

修复后正确口径：
  - 净值曲线 = 累计投入 − 已花费 + 持仓市值（含现金）
  - 年化用 XIRR（资金加权），不用首尾之比
  - 回撤/夏普基于 TWR 序列（剔除新增资金），否则曲线单调上升
"""

import pytest

from app.calculations.backtest import backtest_dca, backtest_ma_cross


def _declining(n: int = 120, rate: float = 0.995) -> list[float]:
    return [100 * (rate**i) for i in range(n)]


def _rising(n: int = 120, rate: float = 1.004) -> list[float]:
    return [100 * (rate**i) for i in range(n)]


class TestDCACurve:
    def test_curve_includes_cash(self):
        """曲线起点必须大于单笔投入的 90%——含现金，而非只剩持仓市值。"""
        r = backtest_dca(_declining(), invest_amount=1000, freq_days=5)
        assert r is not None
        first = r["curve"]["strategy"][0]
        assert first >= 900, f"首日净值 {first} 明显低于投入额，说明曲线漏了现金"

    def test_curve_not_monotonic_in_declining_market(self):
        """下跌行情里曲线不能单调上升（那是假象）。"""
        r = backtest_dca(_declining(), invest_amount=1000, freq_days=5)
        c = r["curve"]["strategy"]
        ups = sum(1 for i in range(1, len(c)) if c[i] > c[i - 1])
        # 允许投入日上升，但绝大多数交易日应下降
        assert ups < len(c) * 0.5, f"{ups}/{len(c)} 天在涨，下跌行情不该如此"

    def test_declining_market_reports_negative_return(self):
        r = backtest_dca(_declining(), invest_amount=1000, freq_days=5)
        assert r["total_return_pct"] < 0, "单边下跌不该报正收益"
        assert r["annualized_return_pct"] < 0, "年化（XIRR）必须为负"

    def test_declining_market_has_real_drawdown(self):
        """回撤必须反映真实亏损，不能是 −2% 这种假象。"""
        r = backtest_dca(_declining(), invest_amount=1000, freq_days=5)
        assert r["max_drawdown_pct"] < -20, (
            f"跌 62% 的行情只报回撤 {r['max_drawdown_pct']}%，说明仍用了含现金的曲线"
        )

    def test_annualized_basis_is_xirr(self):
        r = backtest_dca(_rising(), invest_amount=1000, freq_days=5)
        assert r.get("annualized_basis") == "xirr"

    def test_rising_market_positive(self):
        r = backtest_dca(_rising(), invest_amount=1000, freq_days=5)
        assert r["total_return_pct"] > 0
        assert r["annualized_return_pct"] > 0

    def test_final_value_matches_curve_tail(self):
        """期末市值应与曲线末值一致（同一套估值口径）。"""
        r = backtest_dca(_rising(), invest_amount=1000, freq_days=5)
        assert abs(r["final_value"] - r["curve"]["strategy"][-1]) < 1.0


class TestMACrossUnaffected:
    def test_ma_cross_still_reports_all_metrics(self):
        r = backtest_ma_cross(_rising(120))
        assert r is not None
        for k in ("total_return_pct", "annualized_return_pct", "max_drawdown_pct", "sharpe"):
            assert k in r

    def test_ma_cross_no_xirr_key(self):
        """MA 是一次性投入，不该被塞进定投的 XIRR 字段（曾误改）。"""
        r = backtest_ma_cross(_rising(120))
        assert "annualized_basis" not in r

    def test_rising_market_positive_return(self):
        """单边上涨必须持有并盈利：只认「金叉那一刻」会全程空仓（曾报 0%）。"""
        r = backtest_ma_cross(_rising(120))
        assert r["total_return_pct"] > 20, (
            f"单边上涨 60% 只报 {r['total_return_pct']}%，说明入场条件漏了多头排列"
        )

    def test_trade_count_counts_fills_not_rounds(self):
        """只买未卖时 trade_count 不能是 0（旧实现 len//2 会得出 0）。"""
        r = backtest_ma_cross(_rising(120))
        assert r["trade_count"] >= 1
        assert r["round_count"] == 0
        assert r["open_position"] is True

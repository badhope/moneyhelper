"""v4.15 审计回归测试：锁死本轮修掉的 8 个缺陷。

每个用例都对应一个**曾经产出错误结果但不报错**的缺陷（或一个 500）。
写法上刻意断言可观测结果（数字、日期、code、长度），不断言实现细节，
这样以后重构只要口径不变，测试就不该红。

索引：
1. RSI 无下跌时必须为 100（旧实现给出 0 → 单边上涨被判"深度超卖"）。
2. 信号截断必须留下最重要的，而不是最不重要的。
3. KDJ 遇到 high/low 缺失的行不能崩（旧实现 TypeError → 投研接口 500）。
4. 指标各并行序列必须等长（旧实现 close 过滤了、dates 没过滤 → 全轴错位）。
5. 盈亏比必须为正（旧实现分母是负的收益率之和 → 报 -1.82）。
6. 价格序列含 0 不能崩（旧实现 closes[0] 做分母 → ZeroDivisionError 500）。
7. fast >= slow 必须被拒绝（旧实现照跑，语义已反但输出格式完整）。
8. 债务清偿：余额为 0 的债不得把月供当成"释放额度"注入还款池。
9. 债务清偿：warning_codes 必须与 warning 文案同源。
10. 日志尾部读取失败时降级为空，不能让接口 500。
"""

from __future__ import annotations

from typing import ClassVar

import httpx
import pytest
from app import main
from app.calculations.backtest import (
    backtest_dca,
    backtest_ma_cross,
    prepare_series,
    series_from_points,
)
from app.calculations.debt_payoff import plan_payoff
from app.calculations.technical import (
    clean_points,
    kdj,
    rsi,
    technical_analysis,
)


@pytest.fixture
async def client(temp_db):
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac


def _pts(closes: list[float], vol: int = 1000) -> list[dict]:
    return [
        {
            "date": f"2026-{i // 28 + 1:02d}-{i % 28 + 1:02d}",
            "open": c * 0.99,
            "close": c,
            "high": c * 1.02,
            "low": c * 0.98,
            "volume": vol,
        }
        for i, c in enumerate(closes)
    ]


def _wave(n: int = 200) -> list[float]:
    """正弦叠加小噪声的震荡行情：保证产生多次完整买卖回合。"""
    import math
    import random

    rnd = random.Random(7)
    out = [100.0]
    for i in range(n):
        out.append(out[-1] * (1 + 0.03 * math.sin(i / 6.0) + rnd.uniform(-0.004, 0.004)))
    return out


class TestRsiBoundary:
    def test_no_loss_means_100(self):
        """单边上涨没有任何下跌 → RSI 必须是 100，不是 0。"""
        up = [100.0 + i for i in range(60)]
        assert rsi(up)[-1] == 100.0

    def test_no_gain_means_0(self):
        down = [200.0 - i for i in range(60)]
        assert rsi(down)[-1] == 0.0

    def test_flat_series_is_neutral_50(self):
        flat = [50.0] * 60
        assert rsi(flat)[-1] == 50.0

    def test_uptrend_never_emits_oversold_signal(self):
        """旧实现会给单边上涨挂"深度超卖"买入信号——方向完全反了。"""
        ta = technical_analysis(_pts([100.0 + i * 0.5 for i in range(80)]))
        assert ta is not None
        oversold = [s for s in ta["signals"] if "超卖" in s["text"]]
        assert oversold == []
        assert ta["last"]["rsi"] == 100.0


class TestSignalTruncation:
    def test_keeps_most_important_not_least(self):
        closes: list[float] = []
        px = 100.0
        import math

        for i in range(300):
            px *= 1 + 0.05 * math.sin(i / 4.0)
            closes.append(px)
        ta = technical_analysis(_pts(closes))
        assert ta is not None
        codes = {s["code"] for s in ta["signals"]}
        assert len(ta["signals"]) <= 12
        # MA_CROSS 是优先级最高的信号，只要它出现过就必须留下；
        # 旧实现 sort(...)[-12:] 取到的是最末尾（最不重要）的 12 条，
        # 实测只剩 RSI_OVER + VOL_SURGE，bias 由噪声决定。
        assert "MA_CROSS" in codes
        assert "VOL_SURGE" not in codes or len(codes) > 1

    def test_signals_are_in_chronological_order(self):
        import math

        closes = [100.0 * (1 + 0.04 * math.sin(i / 5.0)) for i in range(200)]
        closes = [c + 100 for c in closes]
        ta = technical_analysis(_pts(closes))
        assert ta is not None
        dates = [s["date"] for s in ta["signals"]]
        assert dates == sorted(dates)


class TestKdjResilience:
    def test_missing_high_low_does_not_raise(self):
        pts = _pts([10.0 + i * 0.05 for i in range(30)])
        for k in (5, 12, 20):
            pts[k]["high"] = None
            pts[k]["low"] = None
        out = kdj(pts)
        assert len(out["k"]) == len(pts)
        # 残缺行不推进 K/D，但其余行必须有值
        assert out["k"][-1] is not None

    def test_technical_analysis_survives_partial_rows(self):
        pts = _pts([10.0 + i * 0.05 for i in range(40)])
        pts[7]["open"] = None
        pts[15]["high"] = None
        pts[20]["volume"] = None
        ta = technical_analysis(pts)
        assert ta is not None
        assert ta["point_count"] == 40
        assert len(ta["series"]["close"]) == 40
        assert len(ta["series"]["ohlc"]) == 40


class TestSeriesAlignment:
    def test_clean_points_drops_invalid_close(self):
        pts = _pts([10.0] * 5)
        pts[2]["close"] = None
        pts[3]["close"] = 0
        kept = clean_points(pts)
        assert len(kept) == 3
        assert all(p["close"] for p in kept)

    def test_all_parallel_series_have_equal_length(self):
        """close 有 None 时，dates / close / ma5 / ohlc 必须仍然一一对应。"""
        pts = _pts([10.0 + i * 0.1 for i in range(60)])
        for k in (10, 30, 45):
            pts[k]["close"] = None
        ta = technical_analysis(pts)
        assert ta is not None
        s = ta["series"]
        n = len(s["dates"])
        assert n == len(s["close"]) == len(s["ma5"]) == len(s["ohlc"]) == len(s["rsi"])
        assert n == 57

    def test_series_from_points_lockstep(self):
        pts = _pts([10.0, 11.0, 12.0, 13.0])
        pts[1]["close"] = None
        pts[3]["close"] = -5
        closes, dates = series_from_points(pts)
        assert closes == [10.0, 12.0]
        assert dates == [pts[0]["date"], pts[2]["date"]]
        assert len(closes) == len(dates)

    def test_prepare_series_drops_non_positive(self):
        closes, dates = prepare_series([0.0, 10.0, -1.0, 11.0], ["a", "b", "c", "d"])
        assert closes == [10.0, 11.0]
        assert dates == ["b", "d"]

    def test_prepare_series_without_dates(self):
        closes, dates = prepare_series([0.0, 10.0], None)
        assert closes == [10.0]
        assert dates is None


class TestProfitFactorSign:
    def test_profit_factor_is_positive(self):
        r = backtest_ma_cross(_wave())
        assert r is not None
        assert r["round_count"] >= 2
        if r["profit_factor"] is not None:
            assert r["profit_factor"] > 0
            # 盈亏比 = Σ盈利 / |Σ亏损|，与 avg_win/avg_loss 同号同量级
            wins = r["win_rate_pct"] / 100 * r["round_count"]
            losses = r["round_count"] - wins
            if wins and losses:
                expected = (r["avg_win_pct"] * wins) / (r["avg_loss_pct"] * losses)
                assert abs(r["profit_factor"] - expected) < 0.15

    def test_all_wins_profit_factor_none(self):
        """没有亏损回合时分母为 0，应给 None 而不是崩溃或 0。"""
        r = backtest_ma_cross(_wave())
        assert r is not None
        if r["avg_loss_pct"] is None:
            assert r["profit_factor"] is None


class TestZeroPriceSafety:
    def test_leading_zero_close_does_not_crash(self):
        closes = _wave(120)
        closes[0] = 0.0
        r = backtest_ma_cross(closes)
        assert r is not None
        assert r["benchmark_return_pct"] is not None

    def test_dca_all_zero_returns_none_or_value(self):
        assert backtest_dca([0.0] * 40) is None

    def test_dca_trade_count_counts_real_buys(self):
        closes = _wave(60)
        r = backtest_dca(closes, invest_amount=1000.0, freq_days=5)
        assert r is not None
        expected = len([1 for i in range(0, len(closes), 5) if closes[i] > 0])
        assert r["trade_count"] == expected
        assert abs(r["total_invested"] - r["trade_count"] * 1000.0) < 1e-6


class TestMaParamValidation:
    def test_fast_must_be_smaller_than_slow(self):
        with pytest.raises(ValueError):
            backtest_ma_cross(_wave(), fast=30, slow=5)

    def test_fast_below_two_rejected(self):
        with pytest.raises(ValueError):
            backtest_ma_cross(_wave(), fast=1, slow=20)

    @pytest.mark.asyncio
    async def test_endpoint_returns_400_not_silent_wrong_answer(self, client):
        r = await client.get(
            "/api/research/backtest",
            params={"symbol": "600519", "strategy": "ma_cross", "fast": 50, "slow": 5},
        )
        assert r.status_code == 400
        assert "fast" in r.json()["detail"]


class TestDebtPayoffPhantomBudget:
    ZERO_BALANCE_DEBT: ClassVar[dict] = {
        "name": "已结清车贷",
        "balance": 0,
        "rate": 0.05,
        "min_payment": 2000,
    }
    CREDIT_CARD: ClassVar[dict] = {
        "name": "信用卡",
        "balance": 10000,
        "rate": 0.18,
        "min_payment": 300,
    }

    def test_zero_balance_debt_does_not_fund_the_pool(self):
        """余额为 0 的债，它的月供不是可支配现金。

        旧实现把 min_by_name 全集里"当前未欠"的月供都算作释放额度，
        于是这条 balance=0、月供 2000 的记录让 1 万元 18% 的信用卡
        从 47 个月还清变成 5 个月，而 monthly_budget 仍写着 300。
        """
        with_zero = plan_payoff(
            [self.CREDIT_CARD, self.ZERO_BALANCE_DEBT],
            extra_payment=0,
            method="avalanche",
            start_year=2026,
            start_month=11,
        ).to_dict()
        without_zero = plan_payoff(
            [self.CREDIT_CARD], extra_payment=0, method="avalanche", start_year=2026, start_month=11
        ).to_dict()
        assert with_zero["months"] == without_zero["months"] == 47
        assert with_zero["total_interest"] == without_zero["total_interest"]
        first_month_paid = sum(with_zero["schedule"][0]["payments"].values())
        assert round(first_month_paid, 2) == with_zero["monthly_budget"]

    def test_freed_budget_still_works_for_real_payoffs(self):
        """雪球效应本身不能被误伤：真还清一笔后，它的月供要转投下一笔。"""
        plan = plan_payoff(
            [
                {"name": "小额", "balance": 500, "rate": 0.05, "min_payment": 200},
                {"name": "大额", "balance": 5000, "rate": 0.18, "min_payment": 100},
            ],
            extra_payment=0,
            method="snowball",
            start_year=2026,
            start_month=11,
        )
        d = plan.to_dict()
        # 小额第 3 个月结清；之后每月实付应仍为 300（含转投的 200）
        later = sum(d["schedule"][5]["payments"].values())
        assert round(later, 2) == pytest.approx(d["monthly_budget"], abs=0.01)
        assert d["months"] < 30


class TestDebtWarningCodes:
    def test_horizon_warning_carries_horizon_code(self):
        """文案说"50 年没还清"时，code 不能是 negative_amortization。

        前端只按 code 查 i18n，两者不同源会让界面显示与后端结论互相矛盾。
        """
        plan = plan_payoff(
            [{"name": "僵尸债", "balance": 5000, "rate": 0.0, "min_payment": 0}],
            extra_payment=0,
            method="avalanche",
            start_year=2026,
            start_month=11,
        )
        d = plan.to_dict(include_schedule=False)
        assert d["months"] == 600
        assert d["warning_codes"] == [{"code": "not_cleared_in_horizon"}]
        assert "50 年" in d["warnings"][0]

    def test_negative_amortization_keeps_its_code(self):
        plan = plan_payoff(
            [{"name": "房贷", "balance": 1_000_000, "rate": 0.05, "min_payment": 100}],
            extra_payment=0,
            method="avalanche",
            start_year=2026,
            start_month=11,
        )
        d = plan.to_dict(include_schedule=False)
        assert d["warning_codes"] == [{"code": "negative_amortization"}]

    def test_codes_and_messages_stay_in_sync(self):
        for debts in (
            [{"name": "a", "balance": 1000, "rate": 0.2, "min_payment": 10}],
            [{"name": "b", "balance": 1000, "rate": 0.0, "min_payment": 0}],
            [{"name": "c", "balance": 1000, "rate": 0.1, "min_payment": 200}],
        ):
            d = plan_payoff(debts, 0, "avalanche", 2026, 11).to_dict(include_schedule=False)
            assert len(d["warnings"]) == len(d["warning_codes"])


class TestLogTailDegrades:
    def test_read_log_lines_swallows_oserror(self, monkeypatch, tmp_path):
        """底层随机读抛 OSError（FUSE/网络盘 EINVAL、读期间被 truncate）时降级为空。

        用目录冒充日志文件：open(dir, "rb") 必然抛 IsADirectoryError（OSError 子类），
        无需依赖具体文件系统行为，也能覆盖"读不出来"这条路径。
        """
        from app import logging_utils

        fake = tmp_path / "moneyhelper.log"
        fake.mkdir()
        monkeypatch.setattr(logging_utils, "_LOG_FILE", fake)
        assert logging_utils.read_log_lines(10) == []

    @pytest.mark.asyncio
    async def test_watchdog_selfcheck_never_500(self, client, monkeypatch):
        from app import logging_utils

        def _boom(limit: int = 200):
            raise OSError(22, "Invalid argument")

        monkeypatch.setattr(logging_utils, "read_log_lines", _boom)
        monkeypatch.setattr("app.studio.watchdog.read_log_lines", _boom)
        r = await client.post("/api/studio/watchdog/run")
        assert r.status_code < 500


class TestStrategiesBenchmarkGuard:
    """首根收盘价为 0 时，三个策略的基准曲线不能抛 ZeroDivisionError。

    `_benchmark()` 早就用 `if closes[0] > 0` 挡住了，曲线部分却是裸除——
    同一份数据一半返回 None、一半 500，属于典型的"口径没走同一条路"。
    """

    def _closes_with_zero_head(self, n: int = 200) -> list[float]:
        c = _wave(n)
        c[0] = 0.0
        return c

    def _assert_curve_aligned(self, r, n: int) -> None:
        if r is None:
            return
        bm = r["curve"]["benchmark"]
        assert len(bm) == n
        # 首价为 0 时基准无意义，必须整条置零并与净值曲线等长（前端按索引对齐）
        assert bm == [0.0] * n
        assert len(r["curve"]["strategy"]) == n

    def test_grid(self):
        from app.calculations.strategies import backtest_grid

        closes = self._closes_with_zero_head()
        self._assert_curve_aligned(backtest_grid(closes), len(closes))

    def test_trend(self):
        from app.calculations.strategies import backtest_trend

        closes = self._closes_with_zero_head()
        self._assert_curve_aligned(backtest_trend(closes), len(closes))

    def test_vol_target(self):
        from app.calculations.strategies import backtest_vol_target

        closes = self._closes_with_zero_head()
        self._assert_curve_aligned(backtest_vol_target(closes), len(closes))

    def test_normal_prices_still_produce_real_benchmark(self):
        from app.calculations.strategies import _benchmark_curve

        curve = _benchmark_curve([10.0, 11.0, 12.0], 1000.0)
        assert curve == [1000.0, 1100.0, 1200.0]
        assert _benchmark_curve([0.0, 11.0], 1000.0) == [0.0, 0.0]

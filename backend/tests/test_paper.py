"""团队模拟盘引擎单测（v4.2 paper.py）。"""

from __future__ import annotations

import pytest
from app.calculations.paper import (
    build_equity_curve,
    estimate,
    fee_for,
    ranking,
    round_lots,
    team_summary,
    validate_trade,
)


def _trade(symbol="600519", side="buy", price=100.0, shares=100, fee=None) -> dict:
    amount = price * shares
    return {
        "symbol": symbol,
        "side": side,
        "price": price,
        "shares": shares,
        "fee": fee if fee is not None else fee_for(side, amount),
        "amount": amount,
    }


class TestRoundLots:
    def test_lots(self):
        assert round_lots(100) == 100
        assert round_lots(250) == 200
        assert round_lots(99) == 0
        assert round_lots(0) == 0


class TestFee:
    def test_buy_fee(self):
        # 100 元 × 100 股 = 10000，佣金 = 2.5 元 → 最低 5 元
        assert fee_for("buy", 10000) == 5.0
        # 大额：0.025%
        assert fee_for("buy", 1_000_000) == pytest.approx(250.0)

    def test_sell_fee(self):
        # 佣金 5 元 + 印花税 0.05% × 10000 = 5 → 10
        assert fee_for("sell", 10000) == 10.0

    def test_invalid(self):
        assert fee_for("hold", 100) == 0.0
        assert fee_for("buy", 0) == 0.0


class TestEstimate:
    def test_buy_then_hold(self):
        t = [_trade(shares=200)]  # 20000 元买入
        e = estimate(100000, t, prices={"600519": 110.0})
        assert e["cash"] == pytest.approx(100000 - 20000 - 5.0, abs=0.01)
        assert e["market_value"] == pytest.approx(22000.0)
        assert e["equity"] == pytest.approx(100000 + 2000 - 5.0, abs=0.01)
        assert e["position_count"] == 1
        assert e["holdings"][0]["symbol"] == "600519"
        assert e["holdings"][0]["cost"] == pytest.approx(20005 / 200, abs=1e-3)
        assert e["return_pct"] == pytest.approx((e["equity"] / 100000 - 1) * 100, abs=0.01)

    def test_sell_reduces(self):
        t = [_trade(shares=200), _trade(side="sell", shares=100, price=120.0)]
        e = estimate(100000, t, prices={"600519": 120.0})
        # 卖出 100 股：回笼 12000 - 费
        assert e["holdings"][0]["shares"] == pytest.approx(100)
        assert e["cash"] >= 100000 - 20005 + 12000 - 11

    def test_missing_price_stale(self):
        t = [_trade(shares=100)]
        e = estimate(100000, t, prices={})  # 无现价 → 用成交价，stale
        assert e["stale"] is True
        assert e["holdings"][0]["last"] == 100.0

    def test_price_available_not_stale(self):
        t = [_trade(shares=100)]
        e = estimate(100000, t, prices={"600519": 105.0})
        assert e["stale"] is False
        assert e["holdings"][0]["last"] == 105.0

    def test_weighted_avg_cost(self):
        t = [_trade(shares=100, price=90.0), _trade(shares=100, price=110.0)]
        e = estimate(100000, t, prices={"600519": 100.0})
        # 加权成本 ≈ (9000+5 + 11000+5) / 200 = 100.05
        assert e["holdings"][0]["cost"] == pytest.approx(100.05, abs=0.01)


class TestValidate:
    def test_buy_non_lot(self):
        err = validate_trade(100000, [], "buy", "600519", 100.0, 150)
        assert err is not None and "整手" in err

    def test_buy_insufficient_cash(self):
        err = validate_trade(1000, [], "buy", "600519", 100.0, 100)
        assert err is not None and "现金不足" in err

    def test_buy_ok(self):
        assert validate_trade(100000, [], "buy", "600519", 100.0, 100) is None

    def test_sell_insufficient(self):
        t = [_trade(shares=100)]
        err = validate_trade(100000, t, "sell", "600519", 100.0, 200)
        assert err is not None and "持仓不足" in err

    def test_sell_ok(self):
        t = [_trade(shares=200)]
        assert validate_trade(100000, t, "sell", "600519", 100.0, 100) is None

    def test_bad_side_and_price(self):
        assert validate_trade(100000, [], "hold", "600519", 1.0, 100) is not None
        assert validate_trade(100000, [], "buy", "600519", 0.0, 100) is not None
        assert validate_trade(100000, [], "buy", "600519", 1.0, 0) is not None


class TestRanking:
    def test_order(self):
        rows = [
            {"account_id": "a", "return_pct": 5.0, "equity": 100},
            {"account_id": "b", "return_pct": 12.0, "equity": 200},
            {"account_id": "c", "return_pct": 5.0, "equity": 300},
        ]
        r = ranking(rows)
        assert [x["account_id"] for x in r] == ["b", "c", "a"]


class TestTeamSummary:
    def test_aggregate(self):
        rows = [
            {"initial_cash": 100000, "equity": 110000, "position_count": 2},
            {"initial_cash": 100000, "equity": 90000, "position_count": 1},
        ]
        s = team_summary(rows)
        assert s["account_count"] == 2
        assert s["total_initial_cash"] == 200000
        assert s["total_equity"] == 200000
        assert s["total_pnl"] == 0
        assert s["return_pct"] == 0.0
        assert s["active_positions"] == 3

    def test_empty(self):
        s = team_summary([])
        assert s["account_count"] == 0
        assert s["return_pct"] == 0.0


class TestEquityCurve:
    def test_shape(self):
        snaps = [
            {"date": "2026-01-01", "equity": 100000},
            {"date": "2026-01-02", "equity": 110000},
            {"date": "2026-01-03", "equity": 105000},
        ]
        c = build_equity_curve(snaps, 100000)
        assert c["dates"] == ["2026-01-01", "2026-01-02", "2026-01-03"]
        assert c["equity"] == [1.0, 1.1, 1.05]
        assert c["bench"] == [1.0, 1.0, 1.0]

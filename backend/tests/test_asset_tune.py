"""4.19.0 个人资产调优：确定性候选、风险说明与无数据边界。"""

from __future__ import annotations

from app.calculations.asset_tune import build_asset_tune


def test_candidates_are_deterministic_and_explain_risk() -> None:
    out = build_asset_tune(
        emergency={"has_data": True, "months_covered": 1.5, "target_months": 3, "essential_monthly": 4000},
        debts=[{"name": "信用卡", "balance": 20000, "rate": 12}],
        cashflow={"income": 10000, "expense": 9500, "savings_rate": 5},
        positions=[
            {"symbol": "510880", "name": "红利ETF", "kind": "股票", "shares": 1000, "last": 60, "market_value": 60000}
        ],
        concentration={
            "threshold_pct": 40,
            "asset_breaches": [{"name": "红利ETF", "investable_pct": 100, "market_value": 60000}],
        },
    )
    kinds = [c["kind"] for c in out["candidates"]]
    assert kinds[:4] == ["debt", "liquidity", "concentration", "savings"] or kinds[:3] == ["debt", "liquidity", "concentration"]
    assert out["count"] >= 4
    assert all(c["requires_confirmation"] for c in out["candidates"])
    assert all(c["risk"] for c in out["candidates"])
    assert all(c["impact"] for c in out["candidates"])
    assert "不代下单" in out["boundary"]
    liquidity = next(c for c in out["candidates"] if c["kind"] == "liquidity")
    assert liquidity["amount"] == 6000
    debt = next(c for c in out["candidates"] if c["kind"] == "debt")
    assert debt["amount"] == 20000
    concentration = next(c for c in out["candidates"] if c["kind"] == "concentration")
    assert concentration["amount"] == 36000


def test_empty_inputs_do_not_invent_actions() -> None:
    out = build_asset_tune()
    assert out["candidates"] == []
    assert out["count"] == 0
    assert out["metrics"]["emergency_months"] == 0.0
    assert "不预测收益" in out["boundary"]


def test_rebalance_uses_targets_and_skips_small_drift() -> None:
    out = build_asset_tune(
        positions=[
            {"symbol": "A", "name": "甲", "kind": "股票", "shares": 1000, "last": 1, "market_value": 1000},
            {"symbol": "B", "name": "乙", "kind": "股票", "shares": 1000, "last": 1, "market_value": 1000},
        ],
        targets=[
            {"symbol": "A", "name": "甲", "target_pct": 20},
            {"symbol": "B", "name": "乙", "target_pct": 80},
        ],
        band_pct=5,
    )
    rebalance = [c for c in out["candidates"] if c["kind"] == "rebalance"]
    assert {c["symbol"]: c["amount"] for c in rebalance} == {"A": 600.0, "B": 600.0}

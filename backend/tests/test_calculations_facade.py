"""calculations 门面导出契约。

同名函数曾同时存在于 paper.py（快照曲线）与 portfolio_risk.py（持仓回溯曲线），
门面里后者静默覆盖前者：`from app.calculations import build_equity_curve` 的语义
取决于 import 顺序，调用方拿错签名就 AttributeError。这里把两种口径都钉死。
"""

from __future__ import annotations

from app.calculations import build_equity_curve, build_snapshot_curve
from app.calculations.paper import build_equity_curve as paper_curve


def test_snapshot_curve_alias_points_to_paper_engine() -> None:
    assert build_snapshot_curve is paper_curve


def test_snapshot_curve_shape() -> None:
    curve = build_snapshot_curve(
        [{"date": "2026-01-01", "equity": 100000}, {"date": "2026-01-02", "equity": 101000}],
        100000,
    )
    assert curve["equity"] == [1.0, 1.01]
    assert curve["bench"] == [1.0, 1.0]


def test_portfolio_curve_keeps_holdings_signature() -> None:
    curve = build_equity_curve(
        [{"symbol": "A", "shares": 10}],
        {"A": [{"date": "2026-01-01", "close": 10.0}, {"date": "2026-01-02", "close": 11.0}]},
        cash=0.0,
    )
    assert curve == [100.0, 110.0]

"""财报分析引擎单测（v4.0 财报模块）。"""

from __future__ import annotations

import pytest
from app.calculations.financial_statements import (
    analyze_statements,
    compute_period_metrics,
)


def _payload(periods: list[dict]) -> dict:
    return {"company": "测试公司", "currency": "CNY", "periods": periods}


def _period(revenue=1000.0, net=100.0, assets=2000.0, liab=1000.0, equity=1000.0, **kw) -> dict:
    base = {
        "period": "2024-12-31",
        "balance_sheet": {
            "total_assets": assets,
            "total_liabilities": liab,
            "total_equity": equity,
            "current_assets": 800.0,
            "current_liabilities": 500.0,
            "inventory": 200.0,
            "accounts_receivable": 150.0,
            "goodwill": 0.0,
        },
        "income_statement": {
            "revenue": revenue,
            "gross_profit": 400.0,
            "operating_profit": 150.0,
            "net_profit": net,
            "ebit": 160.0,
            "interest_expense": 20.0,
        },
        "cashflow_statement": {"operating_cashflow": 80.0},
    }
    for k, v in kw.items():
        # 支持覆盖任意三层字段：balance_sheet.xxx / income_statement.xxx / cashflow_statement.xxx
        if "." in k:
            sec, field = k.split(".", 1)
            base[sec][field] = v
        else:
            base[k] = v
    return base


class TestComputeMetrics:
    def test_profitability(self):
        m = compute_period_metrics(_period(revenue=1000.0, net=100.0, equity=500.0)["balance_sheet"],
                                   _period()["income_statement"], _period()["cashflow_statement"])
        # 毛利率 400/1000 = 40%
        assert m["gross_margin_pct"] == pytest.approx(40.0)
        # 净利率 100/1000 = 10%
        assert m["net_margin_pct"] == pytest.approx(10.0)
        # ROE = 100/500 = 20%
        assert m["roe_pct"] == pytest.approx(20.0)
        # 资产负债率 1000/2000 = 50%
        assert m["debt_ratio_pct"] == pytest.approx(50.0)

    def test_missing_fields_return_none(self):
        m = compute_period_metrics({"total_assets": 100.0}, {"revenue": 50.0}, {})
        assert m["gross_margin_pct"] is None
        assert m["roe_pct"] is None
        assert m["revenue"] == 50.0

    def test_zero_denominator_no_crash(self):
        m = compute_period_metrics({"total_assets": 0.0, "total_liabilities": 0.0, "total_equity": 0.0},
                                   {"revenue": 0.0}, {})
        assert m["gross_margin_pct"] is None
        assert m["debt_ratio_pct"] is None


class TestAnalyze:
    def test_two_periods_yoy(self):
        p = _payload(
            [
                _period(revenue=1000.0, net=100.0),
                _period(revenue=1200.0, net=150.0),
            ]
        )
        r = analyze_statements(p)
        assert r is not None
        assert r["period_count"] == 2
        assert r["periods"][1]["metrics"]["revenue_yoy_pct"] == pytest.approx(20.0)
        assert r["periods"][1]["metrics"]["net_profit_yoy_pct"] == pytest.approx(50.0)

    def test_invalid_payload(self):
        assert analyze_statements({}) is None
        assert analyze_statements({"periods": []}) is None
        assert analyze_statements({"periods": [{"period": "x"}]}) is None  # 三表全空

    def test_dupont_complete(self):
        r = analyze_statements(_payload([_period(revenue=1000.0, net=100.0, assets=2000.0, equity=1000.0)]))
        assert r["dupont"]["complete"] is True
        # ROE = 净利率10% × 周转率0.5 × 权益乘数2 = 10%
        assert r["dupont"]["roe_pct"] == pytest.approx(10.0)

    def test_alerts_trigger(self):
        # 经营现金流为负 + 商誉高企 + 流动比率<1 → 至少 3 条预警
        p = _payload(
            [
                _period(revenue=1000.0, net=100.0),
                _period(
                    revenue=900.0,
                    net=80.0,
                    **{
                        "balance_sheet.total_assets": 3000.0,
                        "balance_sheet.goodwill": 800.0,
                        "balance_sheet.current_assets": 300.0,
                        "balance_sheet.current_liabilities": 400.0,
                        "cashflow_statement.operating_cashflow": -20.0,
                        "income_statement.gross_profit": 250.0,  # 毛利率 40%→27.8% 下滑 >5pct
                    },
                ),
            ]
        )
        r = analyze_statements(p)
        codes = {a["code"] for a in r["alerts"]}
        assert "OCF_NEGATIVE" in codes
        assert "GOODWILL_RISK" in codes
        assert "LOW_LIQUIDITY" in codes
        assert "MARGIN_SLIP" in codes

    def test_report_text(self):
        r = analyze_statements(_payload([_period()]))
        assert r is not None
        assert "测试公司" in r["report_text"]
        assert "不构成投资建议" in r["report_text"]

    def test_trends_shape(self):
        r = analyze_statements(_payload([_period(), _period()]))
        assert len(r["trends"]["periods"]) == 2
        assert len(r["trends"]["revenue"]) == 2
        assert r["trends"]["gross_margin"] == [40.0, 40.0]

    def test_cashflow_stack(self):
        # 默认 _period 经营现金流 80；第二期给投资/筹资负值
        p = _payload(
            [
                _period(),
                _period(
                    **{
                        "cashflow_statement.operating_cashflow": 90.0,
                        "cashflow_statement.investing_cashflow": -120.0,
                        "cashflow_statement.financing_cashflow": 60.0,
                    }
                ),
            ]
        )
        r = analyze_statements(p)
        stack = r["trends"]["cashflow_stack"]
        assert stack["operating"] == [80.0, 90.0]
        assert stack["investing"] == [None, -120.0]
        assert stack["financing"] == [None, 60.0]
        # periods 明细也带三流
        assert r["periods"][1]["cashflow"]["investing"] == -120.0

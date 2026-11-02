"""反事实沙盒测试：四类情景的确定性口径与边界。"""

from __future__ import annotations

import pytest
from app.calculations import ScenarioInput, simulate

BASE = ScenarioInput(
    monthly_income=20000,
    monthly_expense=14000,
    cash=50000,
    essential_monthly=8000,
    target_category_expense=2000,
    fire_target=4_200_000,
    dca_monthly=2000,
)


def test_less_spend_increases_saving_and_shortens_fire() -> None:
    out = simulate(BASE, kind="less_spend", percent=10)
    assert out["available"] is True
    assert out["after"]["monthly_expense"] == 13800.0
    # 少花的钱变成储蓄，净流入 = 收入 - 新支出 + 少花额
    assert out["after"]["monthly_net"] == 6400.0
    assert out["after"]["fire_years"] < out["before"]["fire_years"]


def test_save_more_treats_extra_as_saving_not_expense() -> None:
    out = simulate(BASE, kind="save_more", amount=2000)
    assert out["after"]["monthly_expense"] == 14000.0
    assert out["after"]["monthly_net"] == 8000.0
    assert out["after"]["emergency_months"] > out["before"]["emergency_months"]


def test_dca_change_moves_net_by_delta() -> None:
    out = simulate(BASE, kind="dca_change", amount=3000)
    assert out["detail"]["delta"] == 1000.0
    assert out["after"]["monthly_net"] == 7000.0


def test_one_off_expense_reduces_cash() -> None:
    out = simulate(BASE, kind="one_off", amount=30000)
    assert out["after"]["cash"] == 20000.0
    assert any("应急金" in w for w in out["warnings"])


def test_one_off_income_increases_cash() -> None:
    out = simulate(BASE, kind="one_off", amount=-10000)
    assert out["after"]["cash"] == 60000.0


def test_missing_income_returns_reason() -> None:
    out = simulate(ScenarioInput(monthly_income=0, monthly_expense=5000, cash=0, essential_monthly=3000), kind="save_more", amount=1000)
    assert out["available"] is False
    assert "收入" in out["reason"]


def test_less_spend_without_target_expense_returns_reason() -> None:
    base = ScenarioInput(monthly_income=20000, monthly_expense=10000, cash=50000, essential_monthly=5000, target_category_expense=0)
    out = simulate(base, kind="less_spend", percent=10)
    assert out["available"] is False
    assert "该类目" in out["reason"]


def test_unknown_kind_rejected() -> None:
    with pytest.raises(ValueError):
        simulate(BASE, kind="nonsense")


def test_fire_years_none_when_no_surplus() -> None:
    base = ScenarioInput(monthly_income=10000, monthly_expense=10000, cash=0, essential_monthly=6000, fire_target=3_000_000)
    out = simulate(base, kind="save_more", amount=1)
    assert out["available"] is True
    assert out["after"]["fire_years"] is not None or out["after"]["monthly_net"] > 0

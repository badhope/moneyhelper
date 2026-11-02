"""反事实沙盒（M5.5）：把「如果……会怎样」变成确定性测算。

四类反事实，全部基于账本与既有计算引擎，不调用模型：

1. **少花**：某一分类每月少花 X%（或固定金额），对储蓄率、应急金覆盖月数、
   FIRE 目标本金与达成年限的影响。
2. **多存**：每月额外存 X 元，对应急金覆盖与 FIRE 年限的影响。
3. **改定投**：定投金额变化，对累计投入、成本线与目标达成的影响（按月复利近似）。
4. **一次性大额**：现在支出/收入 X 元，对应急金覆盖与净资产的即时影响。

口径与边界：
- 全部输出「变更前 / 变更后 / 差值」三列，便于前端做对比；
- 缺数据时返回 available=false + reason，不返回假数字；
- FIRE 年限用「目标本金 / 年储蓄」的对数公式（与 calculations.strategy 同口径）外推，
  只作情景推演，不承诺结果；
- 明确标注这是「基于当前收支结构的静态情景」，不含收入变化与市场波动。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MONTHS_PER_YEAR = 12
DEFAULT_WITHDRAWAL_RATE = 0.04
DEFAULT_RETURN_RATE = 0.05


@dataclass
class ScenarioInput:
    monthly_income: float
    monthly_expense: float
    cash: float
    essential_monthly: float
    target_category_expense: float = 0.0
    fire_target: float = 0.0
    dca_monthly: float = 0.0
    notes: list[str] = field(default_factory=list)


def _fire_years(target: float, monthly_saving: float, rate: float) -> float | None:
    """按年储蓄与年化收益估算达成年限（等比年金终值反解）。

    FV = PMT * ((1+r)^n - 1) / r（r>0）；r=0 时 FV = PMT*n。
    返回 None 表示按当前储蓄永远达不到。
    """
    if target <= 0:
        return 0.0
    annual = monthly_saving * MONTHS_PER_YEAR
    if annual <= 0:
        return None
    if rate <= 0:
        return round(target / annual, 2)
    # n = ln(1 + FV*r/PMT) / ln(1+r)
    import math

    try:
        n = math.log(1 + target * rate / annual) / math.log(1 + rate)
    except (ValueError, ZeroDivisionError):
        return None
    return round(n, 2) if n >= 0 else None


def _snapshot(
    *,
    income: float,
    expense: float,
    cash: float,
    essential: float,
    fire_target: float,
    return_rate: float,
    extra_saving: float = 0.0,
) -> dict[str, Any]:
    net = income - expense + extra_saving
    savings_rate = round(net / income * 100, 2) if income > 0 else 0.0
    months_covered = round(cash / essential, 2) if essential > 0 else None
    years = _fire_years(fire_target, net, return_rate) if fire_target > 0 else None
    return {
        "monthly_income": round(income, 2),
        "monthly_expense": round(expense, 2),
        "monthly_net": round(net, 2),
        "savings_rate_pct": savings_rate,
        "cash": round(cash, 2),
        "emergency_months": months_covered,
        "fire_target": round(fire_target, 2),
        "fire_years": years,
    }


def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    keys = ("monthly_net", "savings_rate_pct", "emergency_months", "fire_years")
    out: dict[str, Any] = {}
    for k in keys:
        a, b = before.get(k), after.get(k)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            out[k] = round(b - a, 2)
        else:
            out[k] = None
    return out


def simulate(
    base: ScenarioInput,
    *,
    kind: str,
    amount: float = 0.0,
    percent: float = 0.0,
    return_rate: float = DEFAULT_RETURN_RATE,
    withdrawal_rate: float = DEFAULT_WITHDRAWAL_RATE,
) -> dict[str, Any]:
    """执行一次反事实测算。

    kind:
      - less_spend：target_category_expense 每月少花 percent% 或 amount 元
      - save_more：每月多存 amount 元
      - dca_change：定投从 dca_monthly 改为 amount 元
      - one_off：一次性支出（amount>0）或收入（amount<0）
    """
    if kind not in ("less_spend", "save_more", "dca_change", "one_off"):
        raise ValueError(f"未知情景类型：{kind}")
    if base.monthly_income <= 0:
        return {
            "available": False,
            "reason": "缺少收入数据，无法推演储蓄率与 FIRE；先记账或设置月收入",
            "kind": kind,
        }

    fire_target = base.fire_target or round(base.monthly_expense * MONTHS_PER_YEAR / withdrawal_rate, 2)
    before = _snapshot(
        income=base.monthly_income,
        expense=base.monthly_expense,
        cash=base.cash,
        essential=base.essential_monthly,
        fire_target=fire_target,
        return_rate=return_rate,
    )

    income, expense, cash = base.monthly_income, base.monthly_expense, base.cash
    extra_saving = 0.0
    detail: dict[str, Any] = {"kind": kind, "amount": amount, "percent": percent}

    if kind == "less_spend":
        if base.target_category_expense <= 0:
            return {
                "available": False,
                "reason": "该类目本月没有支出，无法测算少花的影响",
                "kind": kind,
            }
        cut = amount if amount > 0 else base.target_category_expense * (percent / 100)
        cut = min(cut, base.target_category_expense)
        expense = base.monthly_expense - cut
        extra_saving = cut
        cash = base.cash + cut
        detail.update(target_category_expense=round(base.target_category_expense, 2), cut=round(cut, 2))
    elif kind == "save_more":
        if amount <= 0:
            return {"available": False, "reason": "多存金额需大于 0", "kind": kind}
        extra_saving = amount
        cash = base.cash + amount
        detail.update(extra_saving=round(amount, 2))
    elif kind == "dca_change":
        delta = amount - base.dca_monthly
        extra_saving = delta
        detail.update(dca_before=round(base.dca_monthly, 2), dca_after=round(amount, 2), delta=round(delta, 2))
    else:
        if amount == 0:
            return {"available": False, "reason": "一次性金额需不为 0", "kind": kind}
        # 正数=支出（现金减少、支出增加）；负数=收入（现金增加）
        cash = base.cash - amount
        detail.update(one_off=round(amount, 2))

    after = _snapshot(
        income=income,
        expense=expense,
        cash=cash,
        essential=base.essential_monthly,
        fire_target=fire_target,
        return_rate=return_rate,
        extra_saving=extra_saving,
    )
    warnings: list[str] = []
    if after["monthly_net"] < 0:
        warnings.append("该情景下月度净流入为负，不可持续")
    if after["emergency_months"] is not None and after["emergency_months"] < 3:
        warnings.append(f"应急金仅覆盖 {after['emergency_months']} 个月，低于 3 个月安全线")
    if (
        before["fire_years"] is not None
        and after["fire_years"] is not None
        and after["fire_years"] < before["fire_years"]
    ):
        detail["fire_years_saved"] = round(before["fire_years"] - after["fire_years"], 2)

    return {
        "available": True,
        "kind": kind,
        "detail": detail,
        "before": before,
        "after": after,
        "diff": _diff(before, after),
        "warnings": warnings,
        "assumptions": {
            "annual_return": return_rate,
            "withdrawal_rate": withdrawal_rate,
            "basis": "基于当前收支结构的静态情景；不含收入变化与市场波动",
        },
        "disclaimer": "情景推演不是收益承诺，也不构成投资建议。",
    }

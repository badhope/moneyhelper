"""债务清偿规划门面：雪崩法 / 雪球法 / 自定义顺序的确定性模拟。

结构与口径拆到 debt_payoff_types（数据契约与分位舍入口径）、debt_payoff_input
（入参归一）、debt_payoff_engine（逐月摊还引擎）；本模块保留两个对外入口
plan_payoff / compare_methods，并 re-export 测试与 MCP 直接引用的类型。
"""

from __future__ import annotations

from typing import Any


def plan_payoff(
    debts: list[dict[str, Any]] | list[DebtItem],
    extra_payment: float = 0.0,
    method: Method = "avalanche",
    custom_order: list[str] | None = None,
    start_year: int | None = None,
    start_month: int | None = None,
    include_schedule: bool = True,
) -> PayoffPlan:
    """生成清偿计划。

    debts: [{name, balance, rate, min_payment}] 或 DebtItem 列表。
    extra_payment: 每月除最低月供外愿意额外投入的金额（>= 0）。
    method: avalanche / snowball / custom。
    custom_order: method=custom 时的债务名称顺序。

    baseline_interest 是「只付最低月供、不额外还、释放额度也不再投」的对照值。
    baseline_available=False 表示连只付最低都还不完，此时 interest_saved 为 None
    （不做减法，也不硬写成 0——那会让用户以为「省不到钱」）。
    """
    if not _is_finite(extra_payment) or extra_payment < 0:
        raise ValueError("额外还款额需为 >= 0 的有限数值")

    items = _coerce_items(debts)

    from datetime import date as _date

    today = _date.today()
    y0 = start_year or today.year
    m0 = start_month or today.month

    ordered = _order(items, method, custom_order)
    months, interest, paid, schedule, milestones, warnings, warning_codes, cleared = _simulate(
        items, ordered, float(extra_payment), y0, m0, include_schedule
    )

    # 对照基线：只付最低月供，且不把释放出来的额度再投出去。
    # reallocate_freed=False 保证同一个数字与排序方法无关（否则 avalanche 与
    # snowball 会给出两个不同的「只付最低月供」总额，自证口径不成立）。
    _, base_interest, _, _, _, base_warn, _base_codes, base_cleared = _simulate(
        items, ordered, 0.0, y0, m0, collect_schedule=False, reallocate_freed=False
    )

    monthly_budget = _cents(
        sum(d.min_payment for d in items if d.balance > _EPS) + float(extra_payment)
    )

    baseline_available = base_cleared and not base_warn
    interest_saved: float | None = None
    if baseline_available and cleared:
        interest_saved = _cents(max(0.0, base_interest - interest))

    notes = [
        "月复利口径：每期利息 = 余额 × 年利率 ÷ 12，按分四舍五入；实际账单可能按日计息，会有小额差异",
        "月供大于余额的那部分会当期转投到下一笔债，不留在计划外",
    ]
    note_codes: list[dict[str, Any]] = [
        {"code": "monthly_compounding"},
        {"code": "surplus_reallocated"},
    ]
    if method == "avalanche":
        notes.append("雪崩法按年利率从高到低还，数学上总利息最低")
        note_codes.append({"code": "method_avalanche"})
    elif method == "snowball":
        notes.append("雪球法按余额从小到大还，先清小额以获得正反馈，总利息通常略高于雪崩法")
        note_codes.append({"code": "method_snowball"})
    if not baseline_available:
        notes.append("「只付最低月供」本身还不完，因此不给出「可省利息」对比")
        note_codes.append({"code": "baseline_unavailable"})

    plan = PayoffPlan(
        method=method,
        order=[d.name for d in ordered],
        monthly_budget=monthly_budget,
        extra_payment=_cents(float(extra_payment)),
        months=months,
        total_interest=interest,
        total_paid=paid,
        debt_free_date=_ym(y0, m0, months) if cleared else None,
        baseline_interest=base_interest if baseline_available else None,
        interest_saved=interest_saved,
        baseline_available=baseline_available,
        schedule=schedule,
        milestones=milestones,
        warnings=warnings,
        notes=notes,
        warning_codes=warning_codes,
        note_codes=note_codes,
    )
    if not warnings and not cleared:
        # 刚好在第 MAX_MONTHS 个月还清时 cleared 仍为 False（口径：不含边界），
        # 这里补一条同 code 的警告，保证「没有还清」永远有可读原因。
        plan.warnings.append("计划未能在 50 年内还清，请检查月供与额外还款额")
        plan.warning_codes = [{"code": "not_cleared_in_horizon"}]
    if cleared and float(extra_payment) <= 0 and not plan.warnings:
        plan.notes.append("未设置额外还款额：本计划即最低月供下的自然还清时间")
        plan.note_codes.append({"code": "no_extra_payment"})
    return plan

def compare_methods(
    debts: list[dict[str, Any]] | list[DebtItem],
    extra_payment: float = 0.0,
    start_year: int | None = None,
    start_month: int | None = None,
) -> dict[str, Any]:
    """并排比较雪崩法与雪球法：利息、月数、还清顺序。

    用户最常问的两个问题是「先还哪笔」和「能省多少」，一次给全，
    避免前端发两次请求后再自己算差值（前端算差值就会有两套口径）。

    任一方不可行时**不给差额**：拿一个「跑满 600 个月/提前中断」的部分利息
    去和另一方减，会得出「雪球法少付 11 万」这种反话（实测）。
    """
    a = plan_payoff(
        debts, extra_payment, "avalanche", None, start_year, start_month, include_schedule=False
    )
    s = plan_payoff(
        debts, extra_payment, "snowball", None, start_year, start_month, include_schedule=False
    )
    comparable = not a.warnings and not s.warnings
    if not comparable:
        return {
            "avalanche": a.to_dict(include_schedule=False),
            "snowball": s.to_dict(include_schedule=False),
            "interest_diff": None,
            "comparable": False,
            "verdict": "其中一种方法按当前预算无法还清，两种方法不可直接比较利息",
            "verdict_code": {"code": "not_comparable"},
        }
    diff = _cents(s.total_interest - a.total_interest)
    if abs(diff) < 0.01:
        verdict = "两种方法的利息支出基本相同：按余额从小到大还更容易坚持"
        verdict_code: dict[str, Any] = {"code": "same_interest"}
    elif diff > 0:
        verdict = f"雪崩法少付 {diff:.2f} 利息；雪球法的优势是更早清掉第一笔"
        verdict_code = {"code": "avalanche_cheaper", "amount": diff}
    else:
        verdict = f"本例中雪球法反而少付 {abs(diff):.2f} 利息（余额与利率排序一致时会发生）"
        verdict_code = {"code": "snowball_cheaper", "amount": abs(diff)}
    return {
        "avalanche": a.to_dict(include_schedule=False),
        "snowball": s.to_dict(include_schedule=False),
        "interest_diff": diff,
        "comparable": True,
        "verdict": verdict,
        "verdict_code": verdict_code,
    }


# 对外类型与小工具（calculations/__init__、MCP 与回归测试按这些名字引用）
from .debt_payoff_engine import (  # noqa: F401,E402
    _EPS,
    _order,
    _simulate,
    _ym,
)
from .debt_payoff_input import _coerce_items, _num_or  # noqa: F401,E402
from .debt_payoff_types import (  # noqa: F401,E402
    _CENT,
    MAX_MONTHS,
    MAX_RATE,
    MIN_RATE,
    DebtItem,
    Method,
    MonthRow,
    PayoffPlan,
    _cents,
    _is_finite,
)

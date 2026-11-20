"""逐月摊还模拟引擎：还款排序、月度循环、结清里程碑与年月换算。"""

from __future__ import annotations

from typing import Any

from .debt_payoff_types import (
    _EPS,
    MAX_MONTHS,
    DebtItem,
    Method,
    MonthRow,
    _cents,
)


def _order(items: list[DebtItem], method: Method, custom: list[str] | None) -> list[DebtItem]:
    """按方法给出还款优先级。custom 未列出的一律排到最后（保持原顺序）。"""
    if method == "avalanche":
        return sorted(items, key=lambda d: (-d.rate, -d.balance, d.name))
    if method == "snowball":
        return sorted(items, key=lambda d: (d.balance, -d.rate, d.name))
    if method == "custom":
        rank = {name: i for i, name in enumerate(custom or [])}
        return sorted(items, key=lambda d: (rank.get(d.name, len(rank)), d.name))
    raise ValueError(f"未知的还款方法：{method}（可选 avalanche / snowball / custom）")

def _simulate(
    items: list[DebtItem],
    order: list[DebtItem],
    extra: float,
    start_year: int,
    start_month: int,
    collect_schedule: bool,
    *,
    reallocate_freed: bool = True,
) -> tuple[int, float, float, list[MonthRow], list[dict[str, Any]], list[str], list[dict[str, Any]], bool]:
    """逐月摊还模拟。

    返回 (月数, 总利息, 总还款, 明细, 里程碑, 警告文案, 警告代码, 是否真正还清)。
    警告文案与代码成对产生：前端只认 code 去查 i18n，文案给 MCP/CLI/日志。
    两者必须在同一个地方同时写入，否则会出现「文案说 50 年没还清、
    code 却是 negative_amortization」这种前端译文与后端结论互相矛盾的输出（实测）。

    reallocate_freed=False 用于「只付最低月供」对照基线：结清一笔后不再把它的
    月供转投到别的债，此时还款总额恒定，排序对结果没有影响。
    """
    balances = {d.name: d.balance for d in items}
    outstanding = {d.name for d in order if d.balance > _EPS}
    min_by_name = {d.name: d.min_payment for d in items}
    total_interest = 0.0
    total_paid = 0.0
    schedule: list[MonthRow] = []
    milestones: list[dict[str, Any]] = []
    warnings: list[str] = []
    warning_codes: list[dict[str, Any]] = []
    cleared = False
    # 起始就欠着的债（balance > 0）。只有这些债结清后，它的月供才算"释放出来"。
    initially_outstanding = set(outstanding)

    if not outstanding:
        return 0, 0.0, 0.0, schedule, milestones, warnings, warning_codes, True

    month_no = 0
    while outstanding and month_no < MAX_MONTHS:
        month_no += 1
        opening_total = _cents(sum(balances[n] for n in outstanding))

        # 已结清负债的月供不再付出去，并入额外还款池（雪球效应来源）。
        # 只在 reallocate_freed 时为真：对照基线要的是「只付最低」。
        freed = 0.0
        if reallocate_freed:
            # 只统计"一开始就欠着、现在已结清"的债。
            # 旧写法遍历 min_by_name 全集，于是 balance=0 的债（用户填进来的
            # 已结清车贷/已销卡）从第 1 个月起就把它的月供当成可支配现金灌进
            # 还款池：实测一笔 balance=0、月供 2000 的条目让 1 万元 18% 信用卡
            # 从 47 个月还清变成 5 个月，而 monthly_budget 仍显示 300——
            # 既凭空多出不存在的钱，又与自身声明的预算自相矛盾。
            freed = sum(
                min_by_name[name]
                for name in initially_outstanding
                if name not in outstanding
            )
        budget_left = _cents(extra + freed)

        month_interest: dict[str, float] = {}
        month_payments: dict[str, float] = {}

        # 1) 利息滚入余额
        for d in items:
            if balances[d.name] <= _EPS:
                continue
            interest = _cents(balances[d.name] * d.rate / 12.0)
            balances[d.name] = _cents(balances[d.name] + interest)
            month_interest[d.name] = interest
            total_interest = _cents(total_interest + interest)

        # 2) 每笔付月供；月供大于余额时把差额退回还款池（不丢弃）
        for d in items:
            if balances[d.name] <= _EPS:
                continue
            due = min(d.min_payment, balances[d.name])
            surplus = _cents(d.min_payment - due)
            if surplus > 0:
                budget_left = _cents(budget_left + surplus)
            balances[d.name] = _cents(balances[d.name] - due)
            month_payments[d.name] = _cents(month_payments.get(d.name, 0.0) + due)
            total_paid = _cents(total_paid + due)

        # 3) 额外还款按优先级灌给第一笔未还清的债
        for d in order:
            if budget_left <= _EPS:
                break
            if balances[d.name] <= _EPS:
                continue
            pay = _cents(min(budget_left, balances[d.name]))
            balances[d.name] = _cents(balances[d.name] - pay)
            budget_left = _cents(budget_left - pay)
            month_payments[d.name] = _cents(month_payments.get(d.name, 0.0) + pay)
            total_paid = _cents(total_paid + pay)

        # 4) 结清检测 + 里程碑
        for d in order:
            if d.name in outstanding and balances[d.name] <= _EPS:
                outstanding.discard(d.name)
                milestones.append(
                    {
                        "month": month_no,
                        "name": d.name,
                        "date": _ym(start_year, start_month, month_no),
                    }
                )

        if collect_schedule:
            schedule.append(
                MonthRow(
                    month=month_no,
                    payments=dict(month_payments),
                    interest=dict(month_interest),
                    balances={k: _cents(v) for k, v in balances.items() if v > _EPS},
                )
            )

        # 5) 负摊还：当月总余额不降反升 → 这份预算永远还不完，立即停止。
        # 用「总余额方向」而不是「当期还款 vs 当期利息」：后者会在某笔债当月
        # 结清、实付被余额压低时误报（实测把 75 个月能还清的计划判成还不完）。
        closing_total = _cents(sum(balances[n] for n in outstanding))
        if outstanding and closing_total > opening_total + _EPS:
            warnings.append(
                "月供总额不足以覆盖利息（负摊还），该计划无法还清，请提高月供或额外还款额"
            )
            warning_codes.append({"code": "negative_amortization"})
            break

    else:
        if outstanding:
            warnings.append(
                f"模拟 {MAX_MONTHS} 个月（50 年）仍未还清，通常是月供低于利息；"
                "请提高月供或额外还款额"
            )
            warning_codes.append({"code": "not_cleared_in_horizon"})

    if month_no < MAX_MONTHS and not outstanding and not warnings:
        cleared = True

    return month_no, total_interest, total_paid, schedule, milestones, warnings, warning_codes, cleared

def _ym(year: int, month: int, offset: int) -> str:
    """从 (year, month) 起加 offset 个月，返回 YYYY-MM。"""
    total = year * 12 + (month - 1) + offset
    return f"{total // 12:04d}-{total % 12 + 1:02d}"

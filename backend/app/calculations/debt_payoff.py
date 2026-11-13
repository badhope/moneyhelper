"""债务清偿规划：雪崩法 / 雪球法 / 自定义顺序的确定性模拟。

为什么单独成模块：负债在系统里原本只参与两个用途——算 DTI、算月供合计。
用户真正的决策问题是「多出的这 800 块应该先还给谁、几月能还清、总共省多少利息」，
这需要逐月摊还模拟，而不是一个比率。

两种方法的差别是排序目标，不是算法：
- avalanche（雪崩）：按**年利率降序**，数学上总利息最低，是「省钱」最优解；
- snowball（雪球）：按**余额升序**，先清掉最小的一笔，靠「还完一笔」的心理反馈坚持，
  总利息通常略高于雪崩，但执行完成率更高。两种都给，让用户自己选，不替用户决定。

口径（写死在实现里，输出里也声明）：
- 月复利：每期利息 = 余额 × 年利率 / 12，按分四舍五入（ROUND_HALF_UP）。
- 每期先给每笔付 min(min_payment, 余额)；**月供大于余额时省下的差额退回还款池**，
  当期就投向下一笔未结清的债（不丢弃，否则逐月明细与月供合计对不上）。
- 剩余「额外还款额」按方法顺序灌给第一笔未还清的债；某笔结清后它的月供在
  后续月份并入额外还款池（这正是雪球效应的来源）。
- 负摊还判定看**当月总余额是否上升**（而不是「当期总还款 vs 当期总利息」——
  后者在某笔债当月结清、实付被余额压低时会误报，实测会把一份 75 个月能还清的
  计划判成「永远还不完」）。余额上升即立即停止模拟并明确报告，绝不输出
  「永远还不完但看起来像计划」的假结果。
- 「只付最低月供」的对照基线**不重投释放额度**（reallocate_freed=False），
  否则基线本身也带雪球效应，interest_saved 会被低估约一半，且基线会随
  排序方法变化——同一份负债得出两个「可省利息」。
- 所有金额 round 到分；输出含逐月明细，可被用户逐行核对。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

Method = Literal["avalanche", "snowball", "custom"]

MAX_MONTHS = 600  # 50 年上限：超过即视为不可能还清（防止无限循环）
_EPS = 0.005
MIN_RATE = 0.0
MAX_RATE = 1.0  # 年利率 100% 上限，挡住把 12 当 12% 传进来的输入错误
_CENT = Decimal("0.01")


def _cents(value: float) -> float:
    """按分四舍五入到两位小数（ROUND_HALF_UP）。

    不用内置 round()：它是银行家舍入（round(2.675, 2) == 2.67），与 docstring
    承诺的「四舍五入到分」不符，分位差异在长周期还款里会被放大成几毛钱的漂移。
    """
    return float(Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP))


@dataclass
class DebtItem:
    """一笔负债。balance 为未还本金，rate 为年利率小数（0.18 = 18%）。"""

    name: str
    balance: float
    rate: float
    min_payment: float

    def __post_init__(self) -> None:
        self.name = (self.name or "").strip()
        if not self.name:
            raise ValueError("负债名称不能为空")
        if not _is_finite(self.balance) or self.balance < 0:
            raise ValueError(f"{self.name}：未还本金需为 >= 0 的有限数值")
        if not _is_finite(self.rate) or not (MIN_RATE <= self.rate <= MAX_RATE):
            raise ValueError(f"{self.name}：年利率需在 0~1 之间（0.18 表示 18%）")
        if not _is_finite(self.min_payment) or self.min_payment < 0:
            raise ValueError(f"{self.name}：月供需为 >= 0 的有限数值")


@dataclass
class MonthRow:
    """单月还款明细（逐笔），用于前端展开与用户核对。"""

    month: int
    payments: dict[str, float]
    interest: dict[str, float]
    balances: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "month": self.month,
            "payments": self.payments,
            "interest": self.interest,
            "balances": self.balances,
        }


@dataclass
class PayoffPlan:
    method: Method
    order: list[str]
    monthly_budget: float
    extra_payment: float
    months: int
    total_interest: float
    total_paid: float
    debt_free_date: str | None
    baseline_interest: float | None
    interest_saved: float | None
    baseline_available: bool
    schedule: list[MonthRow] = field(default_factory=list)
    milestones: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # 结构化代码：前端按当前语言翻译，后端不拥有 UI 文案。
    # 字符串版本保留给 MCP / CLI / 日志（它们直接展示，无 i18n 层）。
    warning_codes: list[dict[str, Any]] = field(default_factory=list)
    note_codes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self, include_schedule: bool = True) -> dict[str, Any]:
        out = {
            "method": self.method,
            "order": list(self.order),
            "monthly_budget": _cents(self.monthly_budget),
            "extra_payment": _cents(self.extra_payment),
            "months": self.months,
            "years": _cents(self.months / 12.0),
            "total_interest": _cents(self.total_interest),
            "total_paid": _cents(self.total_paid),
            "debt_free_date": self.debt_free_date,
            "baseline_interest": (
                None if self.baseline_interest is None else _cents(self.baseline_interest)
            ),
            "interest_saved": None if self.interest_saved is None else _cents(self.interest_saved),
            "baseline_available": self.baseline_available,
            "milestones": list(self.milestones),
            "warnings": list(self.warnings),
            "notes": list(self.notes),
            "warning_codes": list(self.warning_codes),
            "note_codes": list(self.note_codes),
        }
        # 未收集明细时不能给 schedule_months=0——那会被读成「零个月」，
        # 而实际是 months 个月。字段整体省略，语义才自洽。
        if include_schedule:
            out["schedule"] = [r.to_dict() for r in self.schedule]
            out["schedule_months"] = len(self.schedule)
        return out


def _is_finite(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        # int 过大（如 10**400）转 float 会抛 OverflowError，也是非法输入
        return False
    return f == f and f not in (float("inf"), float("-inf"))


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


def _coerce_items(debts: list[dict[str, Any]] | list[DebtItem]) -> list[DebtItem]:
    """把 dict 列表转成 DebtItem，并拒绝重名。

    重名必须拒绝而不是覆盖：按名字做 dict 时后者会顶掉前者，本金凭空消失
    （实测两笔都叫「信用卡」时 1.5 万本金只剩 5000，且无任何提示）。
    """
    items: list[DebtItem] = []
    for d in debts:
        if isinstance(d, DebtItem):
            items.append(d)
            continue
        if not isinstance(d, dict):
            raise ValueError("负债项必须是对象（含 name/balance/rate/min_payment）")
        # 显式取值而不是 `or 0`：空串/空列表是明显的输入错误，
        # 静默当 0 会产出「这笔债已还清」的误导结论。
        for key in ("balance", "rate", "min_payment", "monthly"):
            raw = d.get(key)
            if raw is None:
                continue
            if isinstance(raw, (list, dict, tuple, bool)):
                raise ValueError(f"{d.get('name') or '负债'}：{key} 必须是数字")
            try:
                float(raw)
            except (TypeError, ValueError, OverflowError):
                raise ValueError(f"{d.get('name') or '负债'}：{key} 必须是数字或超出范围") from None
        items.append(
            DebtItem(
                name=str(d.get("name") or ""),
                balance=_num_or(d.get("balance"), 0.0, "balance"),
                rate=_num_or(d.get("rate"), 0.0, "rate"),
                min_payment=_num_or(d.get("min_payment"), _num_or(d.get("monthly"), 0.0, "monthly"), "min_payment"),
            )
        )
    if not items:
        raise ValueError("至少需要一笔负债")
    names = [i.name for i in items]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ValueError(f"负债名称重复：{'、'.join(dupes)}（名称用于区分每一笔，必须唯一）")
    return items


def _num_or(raw: Any, default: float, field_name: str) -> float:
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{field_name} 必须是数字或超出范围") from None


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

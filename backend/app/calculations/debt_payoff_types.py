"""债务清偿的数据契约与数值口径：Method/阈值/分位舍入/三张表结构。"""

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

def _is_finite(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        # int 过大（如 10**400）转 float 会抛 OverflowError，也是非法输入
        return False
    return f == f and f not in (float("inf"), float("-inf"))

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

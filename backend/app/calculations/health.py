"""财务健康评分：五维 0-100 分确定性评估。

子维度（每维 0-20 分）：
  1. savings_rate          储蓄率
  2. dti                   负债收入比 (Debt-to-Income)
  3. emergency_fund_months 应急金覆盖率（月）
  4. concentration_risk    集中度风险
  5. investment_diversity  投资多样性

常量来自 analysis.py：CONCENTRATION_MAX_PCT=40, DTI_WARN_PCT=40, SAVINGS_RATE_WARN_PCT=20

纯函数，所有输入由外部 I/O 获取后传入。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 与 analysis.py 保持一致
CONCENTRATION_MAX_PCT = 40.0
DTI_WARN_PCT = 40.0
SAVINGS_RATE_WARN_PCT = 20.0
EMERGENCY_TARGET_MONTHS = 6.0


@dataclass
class FinancialHealthScore:
    """财务健康评分结果。"""
    score: int                           # 总分 0-100
    grade: str                           # A / B / C / D / F
    breakdown: dict[str, dict[str, Any]]  # 各维度详情 {dim: {score, max, label, detail}}


@dataclass
class HealthInputs:
    """五维评分所需的全部输入数据。

    所有字段可选，缺失的维度按中性分（10/20）处理，避免因数据缺失给出误导性评价。
    """
    # 1. 储蓄率
    monthly_income: float = 0.0
    monthly_expense: float = 0.0

    # 2. DTI
    monthly_debt_payment: float = 0.0

    # 3. 应急金
    cash_balance: float = 0.0
    essential_monthly_expense: float = 0.0
    emergency_target_months: float = EMERGENCY_TARGET_MONTHS

    # 4. 集中度
    positions: list[dict[str, Any]] = field(default_factory=list)
    # 格式: [{"name", "kind", "market_value"}, ...]

    # 5. 投资多样性
    # 使用 positions 中的非现金持仓自动统计


def calculate_health_score(inputs: HealthInputs) -> FinancialHealthScore:
    """确定性五维财务健康评分。

    Args:
        inputs: HealthInputs 含所有原始数据

    Returns:
        FinancialHealthScore，score 为加权总分（每维等权重 20 分）
    """
    breakdown: dict[str, dict[str, Any]] = {}

    # ---- 维度 1: 储蓄率 (0-20) ---
    score_sr, detail_sr = _score_savings_rate(inputs.monthly_income, inputs.monthly_expense)
    breakdown["savings_rate"] = {
        "score": score_sr,
        "max": 20,
        "label": "储蓄率",
        "detail": detail_sr,
    }

    # ---- 维度 2: DTI (0-20) ---
    score_dti, detail_dti = _score_dti(inputs.monthly_debt_payment, inputs.monthly_income)
    breakdown["dti"] = {
        "score": score_dti,
        "max": 20,
        "label": "负债收入比",
        "detail": detail_dti,
    }

    # ---- 维度 3: 应急金覆盖 (0-20) ---
    score_em, detail_em = _score_emergency_fund(
        inputs.cash_balance,
        inputs.essential_monthly_expense,
        inputs.emergency_target_months,
    )
    breakdown["emergency_fund_months"] = {
        "score": score_em,
        "max": 20,
        "label": "应急金覆盖率",
        "detail": detail_em,
    }

    # ---- 维度 4: 集中度风险 (0-20) ---
    score_conc, detail_conc = _score_concentration(inputs.positions)
    breakdown["concentration_risk"] = {
        "score": score_conc,
        "max": 20,
        "label": "集中度风险",
        "detail": detail_conc,
    }

    # ---- 维度 5: 投资多样性 (0-20) ---
    score_div, detail_div = _score_diversity(inputs.positions)
    breakdown["investment_diversity"] = {
        "score": score_div,
        "max": 20,
        "label": "投资多样性",
        "detail": detail_div,
    }

    total = sum(d["score"] for d in breakdown.values())
    grade = _to_grade(total)

    return FinancialHealthScore(
        score=min(100, max(0, total)),
        grade=grade,
        breakdown=breakdown,
    )


# ---------------------------------------------------------------------------
# 各维度评分逻辑
# ---------------------------------------------------------------------------

def _score_savings_rate(income: float, expense: float) -> tuple[int, str]:
    """储蓄率评分：>=20% 满分，0% 零分，线性插值。"""
    if income <= 0:
        return 10, "无收入数据，无法计算储蓄率（中性分）"

    savings_rate = (income - expense) / income * 100
    if savings_rate >= SAVINGS_RATE_WARN_PCT:
        score = 20
    elif savings_rate >= 0:
        score = round(savings_rate / SAVINGS_RATE_WARN_PCT * 10)
        score = max(1, min(19, score))
    else:
        score = 0

    return score, f"储蓄率 {savings_rate:.1f}%（建议 >= {SAVINGS_RATE_WARN_PCT:.0f}%）"


def _score_dti(debt_payment: float, income: float) -> tuple[int, str]:
    """DTI 评分：0% 满分，>=40% 零分。"""
    if income <= 0:
        if debt_payment > 0:
            return 5, f"有月供 {debt_payment:.0f} 元但无收入数据，偏高（保守扣分）"
        return 10, "无收入与负债数据（中性分）"

    dti = debt_payment / income * 100
    if dti <= 0:
        return 20, "无负债，DTI = 0%"
    elif dti < 20 or dti < DTI_WARN_PCT:
        score = round(20 - dti / DTI_WARN_PCT * 10)
    else:
        score = 0

    score = max(0, min(20, score))
    return score, f"DTI = {dti:.1f}%（警戒线 {DTI_WARN_PCT:.0f}%）"


def _score_emergency_fund(
    cash: float,
    essential_monthly: float,
    target_months: float,
) -> tuple[int, str]:
    """应急金评分：>= 6 个月满分，0 月零分。"""
    if essential_monthly <= 0:
        return 10, "无必要支出数据，无法计算覆盖月数（中性分）"

    months = cash / essential_monthly
    if months >= target_months:
        return 20, f"应急金覆盖 {months:.1f} 个月（目标 {target_months:.0f} 个月），充足"
    elif months >= 3:
        score = round(months / target_months * 10)
        score = max(2, min(19, score))
    elif months > 0:
        score = round(months / 3 * 2)
        score = max(1, min(9, score))
    else:
        score = 0

    return score, f"应急金覆盖 {months:.1f} 个月（目标 {target_months:.0f} 个月）"


def _score_concentration(positions: list[dict[str, Any]]) -> tuple[int, str]:
    """集中度评分：无超限满分，每项超限扣 8 分。"""
    if not positions:
        return 10, "无持仓数据（中性分）"

    # 计算非现金持仓的集中度
    non_cash = [p for p in positions if p.get("kind") != "现金"]
    if not non_cash:
        return 20, "无投资持仓，集中度风险为零"

    total_mv = sum(float(p.get("market_value", 0)) for p in non_cash)
    if total_mv <= 0:
        return 10, "投资持仓市值为零（中性分）"

    breaches = []
    for p in non_cash:
        mv = float(p.get("market_value", 0))
        pct = mv / total_mv * 100
        if pct > CONCENTRATION_MAX_PCT:
            breaches.append(f"{p.get('name', '?')} {pct:.1f}%")

    n = len(breaches)
    if n == 0:
        return 20, f"无超限持仓（单一上限 {CONCENTRATION_MAX_PCT:.0f}%）"
    elif n == 1:
        return 12, f"1 项超限：{breaches[0]}"
    elif n == 2:
        return 6, f"2 项超限：{'；'.join(breaches)}"
    else:
        return 0, f"{n} 项超限：{'；'.join(breaches[:3])}..." if n > 3 else f"{n} 项超限：{'；'.join(breaches)}"


def _score_diversity(positions: list[dict[str, Any]]) -> tuple[int, str]:
    """投资多样性评分：按非现金持仓数量评分。"""
    non_cash = [p for p in positions if p.get("kind") != "现金"]
    n = len(non_cash)

    if n == 0:
        return 0, "无投资持仓"
    elif n == 1:
        return 5, "仅 1 项投资，高度集中"
    elif n == 2:
        return 10, "2 项投资，多样性较低"
    elif n <= 4:
        return 15, f"{n} 项投资，多样性适中"
    else:
        return 20, f"{n} 项投资，多样性良好"


def _to_grade(score: int) -> str:
    """总分转等级。"""
    if score >= 85:
        return "A"
    elif score >= 70:
        return "B"
    elif score >= 55:
        return "C"
    elif score >= 40:
        return "D"
    else:
        return "F"


# ---------------------------------------------------------------------------
# 与 analysis.health_check 的桥接
# ---------------------------------------------------------------------------

# 体检五维各 20 分。status 是 analysis 侧的定性判断（good/warn/bad），
# 这里给出对应的分值，保证「体检页 / 呈批件 / AI 回答」用的是同一套分数。
# unknown = 数据缺失，不参与计分（不是 0 分）。若当成 0 分会把「没录入」
# 惩罚成「很糟」，若当成满分则是凭空送分——两者都是假数据。
_STATUS_SCORE = {"good": 20, "warn": 10, "bad": 0}
_UNKNOWN_STATUSES = {"unknown", "n/a", "na", ""}


def health_score_from_dimensions(dimensions: list[dict[str, Any]]) -> tuple[int, str]:
    """把 analysis.health_check 产出的五维定性结论折算成 (总分, 等级)。

    维度上限统一 20 分（五项合计 100）。缺失的维度不参与计算，
    按已有维度占比折算，避免"少算一项就自动变成满分/零分"。
    """
    if not dimensions:
        return 0, "-"
    earned = 0
    possible = 0
    for dim in dimensions:
        status = str(dim.get("status") or "").lower()
        if status in _UNKNOWN_STATUSES:
            continue  # 数据缺失：既不送分也不扣分，只缩小分母
        weight = int(dim.get("max") or 20)
        possible += weight
        earned += _STATUS_SCORE.get(status, weight // 2)
    if possible <= 0:
        return 0, "-"
    score = round(earned / possible * 100)
    return min(100, max(0, score)), _to_grade(score)

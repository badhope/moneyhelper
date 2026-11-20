"""目标进度与财务体检：评分、风险因子与报告文案。

从 analysis.py 拆出。阈值常量来自 analysis_views，避免两处定义。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .analysis_views import (
    DTI_WARN_PCT,
    SAVINGS_RATE_WARN_PCT,
    _num,
)


def goal_progress(goals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """目标进度：百分比、缺口、距截止月剩余月数、建议月存。纯函数，可单测。"""
    now = datetime.now()
    out: list[dict[str, Any]] = []
    for g in goals:
        target = _num(g.get("target"))
        saved = _num(g.get("saved"))
        pct = round(saved / target * 100, 1) if target > 0 else 0.0
        months_left = None
        deadline = str(g.get("deadline") or "").strip()
        if deadline and len(deadline) == 7:
            try:
                ym = datetime.strptime(deadline, "%Y-%m")
                months_left = max(
                    0, (ym.year - now.year) * 12 + (ym.month - now.month)
                )
            except ValueError:
                months_left = None
        gap = max(0.0, target - saved)
        monthly = round(gap / months_left, 2) if months_left else None
        out.append(
            {
                "name": g.get("name") or "",
                "target": target,
                "saved": saved,
                "pct": pct,
                "gap": round(gap, 2),
                "deadline": deadline,
                "months_left": months_left,
                "monthly_suggest": monthly,
                "done": target > 0 and saved >= target,
            }
        )
    return out


def _dim_portfolio(
    market: dict[str, Any] | None, en: bool,
) -> dict[str, Any] | None:
    """资产配置维度：集中度超限 → warn；否则按市值与累计盈亏给 good。"""
    # 1) 资产配置
    conc = (market or {}).get("concentration") or {}
    breaches = conc.get("asset_breaches", [])
    if breaches:
        return {
            "key": "portfolio",
            "title": "Asset mix" if en else "资产配置",
            "status": "warn",
            "detail": (
                f"Total market value {market['total_market_value']:,.0f} CNY, {len(breaches)} "
                f"concentration breach(es): {'、'.join(b['name'] for b in breaches[:3])}"
                if en
                else (
                    f"总市值 {market['total_market_value']:,.0f} 元，存在 "
                    f"{len(breaches)} 项集中度超限：{'、'.join(b['name'] for b in breaches[:3])}"
                )
            ),
            "suggestion": (
                "Holdings/industry weights are too concentrated — consider diversifying to reduce volatility."
                if en
                else "单一持仓/行业占比过高，考虑分散配置降低波动。"
            ),
        }
    elif market:
        m = market
        word = "gain" if en else "浮盈"
        loss_word = "loss" if en else "浮亏"
        label = word if m["total_pnl"] >= 0 else loss_word
        return {
            "key": "portfolio",
            "title": "Asset mix" if en else "资产配置",
            "status": "good",
            "detail": (
                f"Total market value {m['total_market_value']:,.0f} CNY, cumulative {label} {abs(m['total_pnl']):,.0f} CNY, "
                "concentration within thresholds — well diversified."
                if en
                else (
                    f"总市值 {m['total_market_value']:,.0f} 元，累计{word} {abs(m['total_pnl']):,.0f} 元，"
                    "持仓集中度在阈值内，配置较为分散。"
                )
            ),
            "suggestion": "",
        }


def _dim_cashflow(
    ledger: dict[str, Any] | None, en: bool,
) -> dict[str, Any] | None:
    """现金流维度：本月无收入不评估；储蓄率低于建议线 warn，≥20% good。"""
    # 2) 现金流 / 储蓄率（本月无收入时储蓄率不可算，跳过该维度避免伪信号）
    if ledger and ledger.get("income", 0) > 0:
        sr = ledger.get("savings_rate", 0)
        net = ledger.get("net", 0)
        if sr < SAVINGS_RATE_WARN_PCT:
            return {
                "key": "cashflow",
                "title": "Cash flow" if en else "现金流",
                "status": "warn",
                "detail": (
                    f"Net this month {net:,.0f} CNY, savings rate {sr}% below the {SAVINGS_RATE_WARN_PCT}% target"
                    if en
                    else f"本月结余 {net:,.0f} 元，储蓄率 {sr}% 低于建议线 {SAVINGS_RATE_WARN_PCT}%"
                ),
                "suggestion": (
                    "Review non-essential spending (see spending categories) and push the savings rate above 20%."
                    if en
                    else "梳理非必要支出（可看支出分类），把储蓄率提到 20% 以上。"
                ),
            }
        elif sr >= 20:
            return {
                "key": "cashflow",
                "title": "Cash flow" if en else "现金流",
                "status": "good",
                "detail": (
                    f"Net this month {net:,.0f} CNY, savings rate {sr}% — healthy range."
                    if en
                    else f"本月结余 {net:,.0f} 元，储蓄率 {sr}%，处于健康区间。"
                ),
                "suggestion": "",
            }


def _dim_debt(
    ledger: dict[str, Any] | None, en: bool,
) -> dict[str, Any] | None:
    """负债维度：DTI 超线或有高息负债 → warn/bad；无债务记录 → unknown。"""
    # 3) 负债健康
    if ledger:
        dti = ledger.get("dti_pct", 0)
        high = ledger.get("high_rate_debts") or []
        if dti > DTI_WARN_PCT or high:
            detail_zh = f"负债月供占收入 {dti}%（建议线 {DTI_WARN_PCT}%）" + (f"，存在高息负债：{high[0]['name']}" if high else "")
            detail_en = f"Debt payments are {dti}% of income (target {DTI_WARN_PCT}%)" + (f", high-interest debt: {high[0]['name']}" if high else "")
            return {
                "key": "debt",
                "title": "Debt health" if en else "负债健康",
                "status": "warn" if not high else "bad",
                "detail": detail_en if en else detail_zh,
                "suggestion": (
                    "Pay off high-interest debt first (e.g. credit-card installments), then consider new debt."
                    if en
                    else "优先偿还高息负债（如信用卡分期），再考虑新增负债。"
                ),
            }
        elif ledger.get("debt_monthly", 0) == 0:
            # debt_monthly=0 有两种可能：确实没负债，或用户根本没录负债。
            # 后者给 good 等于凭空送 20 分（新用户记一笔账就能拿高分），
            # 所以按「负债条数」区分：有明细且都还清 = good；没明细 = unknown。
            has_debt_records = bool((ledger or {}).get("debt_count"))
            return {
                "key": "debt",
                "title": "Debt health" if en else "负债健康",
                "status": "good" if has_debt_records else "unknown",
                "detail": (
                    ("No outstanding debt — clean structure." if en else "已录入的负债均无未还月供，结构干净。")
                    if has_debt_records
                    else ("No debt records found — add mortgage/card balances for a real assessment."
                          if en else "未录入负债信息，无法评估负债健康度（有房贷/信用卡请补录）。")
                ),
                "suggestion": "" if has_debt_records else (
                    "Record outstanding debts so DTI and interest cost can be assessed."
                    if en else "补录未偿还负债，才能评估负债率与利息成本。"
                ),
            }


def _dim_emergency(
    ledger: dict[str, Any] | None, en: bool,
) -> dict[str, Any] | None:
    """应急金维度：覆盖月数达目标 good，否则 warn；无数据不评估。"""
    # 4) 应急金
    em = (ledger or {}).get("emergency") or {}
    if em.get("has_data"):
        ok = em.get("ok", True)
        detail_zh = (
            f"应急金可覆盖 {em.get('months_covered')} 个月必要支出（目标 {em.get('target_months')} 个月）"
            if ok
            else f"应急金仅覆盖 {em.get('months_covered')} 个月，低于目标 {em.get('target_months')} 个月"
        )
        detail_en = (
            f"Emergency fund covers {em.get('months_covered')} months of essential spending (target {em.get('target_months')} months)"
            if ok
            else f"Emergency fund covers only {em.get('months_covered')} months, below the {em.get('target_months')}-month target"
        )
        return {
            "key": "emergency",
            "title": "Emergency fund" if en else "应急金",
            "status": "good" if ok else "warn",
            "detail": detail_en if en else detail_zh,
            "suggestion": "" if ok else (
                "Top up the emergency fund with monthly surplus before other goals."
                if en
                else "每月结余优先补足应急金，再谈其它目标。"
            ),
        }


def _dim_goals(
    goals: list[dict[str, Any]] | None, ledger: dict[str, Any] | None, en: bool,
) -> dict[str, Any] | None:
    """目标进度维度：部分目标按当前结余赶不上截止日 → warn。"""
    # 5) 目标进度
    gs = goal_progress(goals or [])
    if gs:
        done = [g for g in gs if g["done"]]
        on_going = [g for g in gs if not g["done"]]
        if on_going:
            slow = [g for g in on_going if g.get("months_left") and g["monthly_suggest"] and g["monthly_suggest"] > (ledger or {}).get("net", 0)]
            detail_zh = (
                f"{len(done)} 个目标已完成；"
                + "、".join(f"{g['name']} {g['pct']}%" for g in on_going[:3])
                + ("（按当前结余，部分目标可能赶不上截止日）" if slow else "")
            )
            detail_en = (
                f"{len(done)} goal(s) achieved; "
                + ", ".join(f"{g['name']} {g['pct']}%" for g in on_going[:3])
                + (" (some goals may miss their deadline at the current net)" if slow else "")
            )
            return {
                "key": "goals",
                "title": "Goal progress" if en else "目标进度",
                "status": "warn" if slow else "good",
                "detail": detail_en if en else detail_zh,
                "suggestion": "" if not slow else (
                    "Increase monthly saving or extend goal deadlines."
                    if en
                    else "提高每月储蓄或延后目标截止月。"
                ),
            }
        else:
            return {
                "key": "goals",
                "title": "Goal progress" if en else "目标进度",
                "status": "good",
                "detail": "All goals achieved." if en else "全部目标已达成。",
                "suggestion": "",
            }



def health_check(
    market: dict[str, Any] | None,
    ledger: dict[str, Any] | None,
    flags: list[dict[str, Any]],
    goals: list[dict[str, Any]] | None = None,
    lang: str = "zh",
) -> dict[str, Any]:
    """结构化财务体检：资产配置 / 现金流 / 负债 / 应急金 / 目标进度 五维评分。

    每维度由 `_dim_*` 纯函数产出（status + 一句 human 可读结论），此处只做汇总与加权。
    lang：zh → 中文文案；en → 英文文案（界面语言跟随）。
    """
    en = lang != "zh"
    dims: list[dict[str, Any]] = []
    for dim in (
        _dim_portfolio(market, en),
        _dim_cashflow(ledger, en),
        _dim_debt(ledger, en),
        _dim_emergency(ledger, en),
        _dim_goals(goals, ledger, en),
    ):
        if dim:
            dims.append(dim)

    flags_texts = [f["text"] for f in flags]
    if not dims:
        # 空库不给「整体健康 100 分」的假象：没有任何数据可评估
        return {
            "score": 0,
            "grade": "-",
            "dimensions": [],
            "flags": flags_texts,
            "summary": (
                "Not enough data: record a few transactions and holdings for a meaningful check"
                if en
                else "数据不足：记几笔账、加几条持仓后体检才有意义"
            ),
        }
    # 五维加权评分：与 calculations/health.py 同一口径。
    # 旧实现用「100 - 20×坏维度数」是拍脑袋扣分——维度本身有轻重，
    # 一套口径才能让体检页、呈批件、AI 回答说的是同一个分数。
    from .calculations.health import health_score_from_dimensions

    weighted, grade = health_score_from_dimensions(dims)
    return {
        "score": weighted,
        "grade": grade,
        "dimensions": dims,
        "flags": flags_texts,
        "summary": (
            "overall healthy"
            if all(d["status"] == "good" for d in dims)
            else ("some areas need attention, handle them one by one" if en else "有几项需要关注，按建议逐条处理即可")
        ),
    }


HEALTH_WORDS = ("体检", "健康检查", "哪里需要改进", "财务状况怎么样", "综合评分")


HEALTH_STATUS_EN = {"good": "Healthy", "warn": "Attention", "bad": "Risk"}


def health_report_text(report: dict[str, Any], lang: str = "zh") -> str:
    """把 health_check 报告转成给用户看的文本（确定性体检输出，无需模型）。

    lang=en 时：评分/状态/维度标题本地化；维度结论与建议保持数据层中文（后续迭代全量英文化）。
    """
    if lang == "zh":
        lines = [f"财务体检综合评分 {report['score']} 分（{report['summary']}）。"]
        if not report["dimensions"]:
            lines.append("当前数据太少，暂时无法逐项评估——记几笔账、加几条持仓后体检会更完整。")
            return "\n".join(lines)
        for d in report["dimensions"]:
            status = {"good": "健康", "warn": "需关注", "bad": "风险"}.get(d["status"], d["status"])
            line = f"- {d['title']}（{status}）：{d['detail']}"
            if d.get("suggestion"):
                line += f"\n  建议：{d['suggestion']}"
            lines.append(line)
        return "\n".join(lines)
    lines = [f"Financial health score: {report['score']} ({report['summary']})."]
    if not report["dimensions"]:
        lines.append("Not enough data for itemized assessment — record a few transactions and holdings, then check again.")
        return "\n".join(lines)
    for d in report["dimensions"]:
        status = HEALTH_STATUS_EN.get(d["status"], d["status"])
        line = f"- {d['title']} ({status}): {d['detail']}"
        if d.get("suggestion"):
            line += f"\n  Suggestion: {d['suggestion']}"
        lines.append(line)
    return "\n".join(lines)

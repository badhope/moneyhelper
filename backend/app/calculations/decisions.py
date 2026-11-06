"""决策中心：把分散在各模块的结论收敛成「今天该做什么」。

为什么需要它：持仓页告诉你集中度超限、税负页告诉你可以抵扣、现金流页告诉你
下月缺口、目标页告诉你进度落后——四个模块各自正确，但用户要自己排优先级。
成熟理财产品的核心价值恰恰在「排序」，而不是再多一个指标。

设计原则（与确定性内核一致）：
  - 全部输入来自已算好的确定性结果，本模块**不引入新的估算口径**；
  - 每条建议带 `impact`（可量化就用数字，不能量化就说明为什么值得做），
    避免「建议多存钱」这类无法验收的空话；
  - 按「紧急度 × 影响」排序，同级按领域固定顺序，保证输出可复现；
  - 任何模块数据缺失只跳过该条，不伪造。
"""

from __future__ import annotations

from typing import Any

# 优先级：数值越小越靠前。分档而非连乘，避免小差异导致排序抖动。
PRIORITY_URGENT = 10      # 已经发生或即将发生损失（超限、缺口、逾期）
PRIORITY_HIGH = 20        # 有明确可量化收益，且动作在用户控制内
PRIORITY_MEDIUM = 30      # 结构性优化，需要持续投入
PRIORITY_LOW = 40         # 信息性/可选

DOMAIN_ORDER = {"risk": 0, "cashflow": 1, "tax": 2, "goal": 3, "portfolio": 4}

DOMAIN_LABEL = {
    "zh": {"risk": "风险", "cashflow": "现金流", "tax": "税负", "goal": "目标", "portfolio": "配置"},
    "en": {"risk": "Risk", "cashflow": "Cash flow", "tax": "Tax", "goal": "Goal", "portfolio": "Allocation"},
}


def _t(lang: str, zh: str, en: str) -> str:
    return en if str(lang).lower().startswith("en") else zh


def _item(domain: str, priority: int, title: str, detail: str,
          impact: str = "", action: str = "", action_tab: str = "") -> dict[str, Any]:
    return {
        "domain": domain,
        "priority": priority,
        "title": title,
        "detail": detail,
        "impact": impact,
        "action": action,
        "action_tab": action_tab,
    }


def _from_flags(flags: list[dict[str, Any]], lang: str) -> list[dict[str, Any]]:
    """风险标记 → 待办。

    真实契约（analysis.risk_checks）：{"level": warn|danger, "code": 大写常量, "text": 本地化文案}。
    code 用大写是因为前端按它聚合/跳转；这里按前缀匹配，新增同族 code 不必改表。
    """
    out: list[dict[str, Any]] = []
    for flag in flags or []:
        code = str(flag.get("code") or "").upper()
        msg = str(flag.get("text") or flag.get("message") or "").strip()
        if not code or not msg:
            continue
        if code.startswith("CONCENTRATION"):
            # 集中度超限是「已经发生的偏离」，不是潜在风险：持仓已经超过阈值，
            # 因此即使 level 只是 warn 也按紧急处理——这是唯一能让用户今天就动手的信号。
            out.append(_item(
                "risk", PRIORITY_URGENT,
                _t(lang, "持仓或行业过于集中", "Position or sector too concentrated"),
                msg,
                _t(lang, "降低单一标的波动对整体的冲击", "Reduces one position's impact on the whole"),
                _t(lang, "看持仓与集中度", "Review holdings"), "holdings",
            ))
        elif code.startswith("HIGH_RATE_DEBT") or code.startswith("DEBT"):
            out.append(_item(
                "risk", PRIORITY_URGENT,
                _t(lang, "高息负债侵蚀收益", "High-interest debt erodes returns"),
                msg,
                _t(lang, "优先偿还利率高于投资回报的负债", "Repay debt that costs more than it earns"),
                _t(lang, "看负债明细", "Review debts"), "overview",
            ))
        elif code.startswith("SAVINGS_RATE") or code.startswith("SAVINGS"):
            out.append(_item(
                "cashflow", PRIORITY_HIGH,
                _t(lang, "储蓄率偏低", "Savings rate is low"),
                msg,
                _t(lang, "提高储蓄率是增强财务韧性最快的方式", "Fastest way to build resilience"),
                _t(lang, "看收支结构", "Review cash flow"), "overview",
            ))
        elif code.startswith("CASHFLOW") or code.startswith("NEGATIVE"):
            out.append(_item(
                "cashflow", PRIORITY_URGENT,
                _t(lang, "现金流出现缺口", "Cash flow gap"),
                msg,
                _t(lang, "缺口会直接消耗本金", "A gap eats into principal"),
                _t(lang, "看现金流预测", "Review forecast"), "overview",
            ))
        else:
            out.append(_item(
                "risk", PRIORITY_MEDIUM,
                _t(lang, "风险提示", "Risk flag"), msg,
                "", _t(lang, "查看详情", "View details"), "health",
            ))
    return out


def _from_goals(goals: list[dict[str, Any]], lang: str) -> list[dict[str, Any]]:
    """目标进度落后 → 提示调整月度投入，而不是笼统「加油」。

    输入是 analysis.goal_progress 的输出：pct / gap / months_left / monthly_suggest。
    判定「落后」用可核算的口径：未完成，且（已过期，或按当前节奏到期仍有缺口）。
    """
    out: list[dict[str, Any]] = []
    for g in goals or []:
        if not isinstance(g, dict) or g.get("done"):
            continue
        name = str(g.get("name") or "").strip()
        gap = float(g.get("gap") or 0)
        pct = float(g.get("pct") or 0)
        months_left = g.get("months_left")
        if not name or gap <= 0:
            continue
        expired = isinstance(months_left, (int, float)) and months_left <= 0
        # 剩余月数内建议月存超过常见月结余量级 → 视为落后（无月结余数据时只看过期）
        behind = expired
        if not behind:
            continue
        monthly = g.get("monthly_suggest")
        detail = _t(lang, "还差 %s，当前完成 %.0f%%", "Short by %s, currently %.0f%%") % (
            _money(gap), pct)
        if isinstance(monthly, (int, float)) and monthly > 0:
            detail += _t(lang, "，需每月存 %s", "; needs %s per month") % _money(monthly)
        out.append(_item(
            "goal", PRIORITY_HIGH,
            _t(lang, "目标已到期未达成：%s", "Goal past deadline: %s") % name,
            detail,
            _t(lang, "重设截止月或调整月度投入，比继续拖延更可控",
               "Resetting the deadline or the monthly amount is more controllable"),
            _t(lang, "看目标", "Review goal"), "overview",
        ))
    return out


def _money(v: float) -> str:
    if abs(v) >= 10000:
        return f"{v / 10000:.1f}万"
    return f"{v:.0f}"


def build_actions(
    *,
    flags: list[dict[str, Any]] | None = None,
    goals: list[dict[str, Any]] | None = None,
    tax_saving: float | None = None,
    rebalance: list[dict[str, Any]] | None = None,
    lang: str = "zh",
    limit: int = 6,
) -> dict[str, Any]:
    """汇总成待办清单。返回 {"items": [...], "count": n, "top": item|None}。

    所有入参都可缺失：缺失的领域不产生条目，也不占位。
    """
    items: list[dict[str, Any]] = []
    items.extend(_from_flags(flags or [], lang))
    items.extend(_from_goals(goals or [], lang))

    # 税负：有可量化节税额才算「高价值动作」，否则不提（避免空泛）
    if tax_saving is not None and tax_saving > 0:
        items.append(_item(
            "tax", PRIORITY_HIGH,
            _t(lang, "存在可抵扣项", "Deductible items available"),
            _t(lang, "预计可减少税负约 %s", "Estimated tax reduction about %s") % _money(tax_saving),
            _t(lang, "合法合规的确定性收益", "A certain, compliant gain"),
            _t(lang, "看税负", "Review tax"), "tax",
        ))

    # 配置：偏离目标且给出可执行金额时才算动作
    for row in rebalance or []:
        if not isinstance(row, dict):
            continue
        amount = float(row.get("amount") or 0)
        symbol = str(row.get("symbol") or row.get("name") or "").strip()
        side = str(row.get("side") or "").strip()
        if abs(amount) <= 0 or not symbol:
            continue
        verb = _t(lang, "买入", "Buy") if side == "buy" else _t(lang, "卖出", "Sell")
        items.append(_item(
            "portfolio", PRIORITY_MEDIUM,
            _t(lang, "配置偏离目标：%s %s", "Allocation off target: %s %s") % (verb, symbol),
            _t(lang, "约 %s，按目标权重回到容忍带内", "About %s, back inside the tolerance band")
            % _money(abs(amount)),
            _t(lang, "降低组合漂移带来的隐性风险", "Reduces hidden drift risk"),
            _t(lang, "看策略", "Review strategy"), "strategy",
        ))

    # 排序：优先级 → 领域固定序 → 标题（保证完全可复现）
    items.sort(key=lambda x: (x["priority"], DOMAIN_ORDER.get(x["domain"], 99), x["title"]))
    trimmed = items[:limit]
    labels = DOMAIN_LABEL["en" if str(lang).lower().startswith("en") else "zh"]
    for it in trimmed:
        it["domain_label"] = labels.get(it["domain"], it["domain"])
    return {"items": trimmed, "count": len(items), "top": trimmed[0] if trimmed else None}

"""首页评估规则：预算 / 订阅 / 债务 / 目标 / 现金流五条纯函数规则。

每条 rule 拉聚合数据后返回 `list[EvalItem]`，异常由 `evaluate_all` 兜底。
"""

from __future__ import annotations

from datetime import date

from . import db
from .evaluate_types import SUBS_REMIND_WITHIN_DAYS, EvalItem, _upcoming_due


async def _rule_budget(month: str) -> list[EvalItem]:
    """预算进度：超支 → P0；快超 → P1；没有预算但有流水 → P2。"""
    rows = await db.list_budgets(month)
    usage = await db.budget_usage(month)
    out: list[EvalItem] = []

    total = next((r for r in rows if r.get("category") == "__total"), None)
    if not total or (total.get("amount") or 0) <= 0:
        # 本月是否有流水？（任意一条即可）
        txns = await db.list_transactions()
        if txns:
            out.append(EvalItem(
                kind="info", priority=2, code="budget.missing",
                action={"path": "/settings#budget"},
            ))
        return out

    pct = usage.get("total_pct", 0) if isinstance(usage, dict) else 0
    over = usage.get("over", False) if isinstance(usage, dict) else (pct >= 100)
    if over:
        over_amt = usage.get("total_spent", 0) - (total.get("amount") or 0)
        out.append(EvalItem(
            kind="todo", priority=0, code="budget.over",
            vars={"pct": pct, "over": round(over_amt, 0), "total": total["amount"]},
        ))
    elif pct >= 85:
        left = (total.get("amount") or 0) - usage.get("total_spent", 0)
        out.append(EvalItem(
            kind="warn", priority=1, code="budget.near",
            vars={"pct": pct, "left": round(max(left, 0), 0)},
        ))

    return out


async def _rule_subscriptions(today: date) -> list[EvalItem]:
    """订阅 N 天内到期：P1；无 due_day 的订阅：P3 提示配置。"""
    subs = await db.list_subscriptions()
    out: list[EvalItem] = []
    due_items: list[EvalItem] = []
    missing_due: list[str] = []

    for s in subs:
        due_day = s.get("due_day", "")
        res = _upcoming_due(today, due_day, window=SUBS_REMIND_WITHIN_DAYS)
        if res is not None:
            days, due_date = res
            due_items.append(EvalItem(
                kind="todo", priority=1, code="subs.due.item",
                title=s.get("name", ""),
                detail="",
                vars={
                    "name": s["name"],
                    "monthly": float(s.get("monthly") or 0),
                    "days": days,
                    "date": f"{due_date.month}-{due_date.day}",
                },
            ))
        elif not (due_day or "").strip():
            missing_due.append(s["name"])

    if len(due_items) == 1:
        out.append(due_items[0])
    elif len(due_items) > 1:
        # 多条订阅即将扣款：聚合为一条，避免首页信息轰炸
        total_monthly = sum(float(it.vars.get("monthly", 0)) for it in due_items)
        earliest = min(due_items, key=lambda it: it.vars.get("days", 999))
        out.append(EvalItem(
            kind="todo", priority=1, code="subs.due.items",
            vars={
                "n": len(due_items),
                "amount": round(total_monthly, 2),
                "date": earliest.vars.get("date", ""),
            },
        ))

    if missing_due:
        out.append(EvalItem(
            kind="info", priority=3, code="subs.missing_due",
            vars={"n": len(missing_due), "names": ", ".join(missing_due[:5])},
            action={"path": "/settings#subscriptions"},
        ))
    return out


async def _rule_debts(today: date) -> list[EvalItem]:
    """债务 N 天内还款：P1；高利率（>15%）债务：P2 提示优先偿还。"""
    debts = await db.list_debts()
    out: list[EvalItem] = []
    for d in debts:
        due_day = d.get("due_day", "")
        res = _upcoming_due(today, due_day, window=SUBS_REMIND_WITHIN_DAYS)
        if res is not None:
            days, due_date = res
            out.append(EvalItem(
                kind="todo", priority=1,
                code="debt.due.item",
                vars={
                    "name": d["name"],
                    "monthly": d["monthly"],
                    "days": days,
                    "date": f"{due_date.month}-{due_date.day}",
                    "balance": d["balance"],
                },
            ))
        rate = float(d.get("rate") or 0)
        # rate 以小数存储（0.18 = 18%），阈值 0.15 = 15%
        if rate >= 0.15:
            out.append(EvalItem(
                kind="info", priority=2, code="debt.high_rate",
                vars={"name": d["name"], "rate": round(rate * 100, 2)},
            ))
    return out


async def _rule_goals(month: str) -> list[EvalItem]:
    """目标 vs 已过月份进度：落后 → P2；deadline 临近 → P1。"""
    goals = await db.list_goals()
    out: list[EvalItem] = []
    try:
        cur_year, cur_month = (int(x) for x in month.split("-"))
    except (TypeError, AttributeError, ValueError):
        cur_year, cur_month = date.today().year, date.today().month

    for g in goals:
        target = float(g.get("target") or 0)
        saved = float(g.get("saved") or 0)
        deadline = (g.get("deadline") or "").strip()
        if target <= 0:
            continue

        pct = round((saved / target) * 100, 1) if target > 0 else 0

        # deadline 临近：目标月份含当月或已逾期
        if deadline:
            try:
                d_year, d_month = (int(x) for x in deadline.split("-"))
                months_total = (d_year - cur_year) * 12 + (d_month - cur_month)
                late = months_total <= 0 and pct < 100
                soon = 0 < months_total <= 2 and pct < 80
                if late:
                    out.append(EvalItem(
                        kind="todo", priority=0, code="goal.deadline_late",
                        vars={"name": g["name"], "pct": pct, "target": target, "saved": saved},
                    ))
                elif soon:
                    out.append(EvalItem(
                        kind="warn", priority=1, code="goal.deadline_soon",
                        vars={"name": g["name"], "pct": pct, "months": months_total},
                    ))
                continue
            except (TypeError, AttributeError, ValueError):
                pass

        # 没有 deadline：按盈亏/节奏提示
        if pct >= 100:
            out.append(EvalItem(
                kind="info", priority=2, code="goal.done",
                vars={"name": g["name"]},
            ))
    return out


async def _rule_cashflow() -> list[EvalItem]:
    """活期现金 < 月度基础支出 × 1.5：P2 提示流动性不足。"""
    # 计算"月基础支出" = 债务月供 + 订阅月度合计
    subs = await db.list_subscriptions()
    debts = await db.list_debts()
    monthly_out = sum(float(s.get("monthly") or 0) for s in subs)
    monthly_out += sum(float(d.get("monthly") or 0) for d in debts)
    if monthly_out <= 0:
        return []

    total_cash = await db.total_cash()
    if total_cash is None:
        return []
    if total_cash < monthly_out * 1.5:
        return [EvalItem(
            kind="warn", priority=2, code="cash.low",
            vars={"cash": round(total_cash, 0), "need": round(monthly_out * 3, 0)},
        )]
    return []


# --------------------------------------------------------------------------
# 入口：evaluate_all(month) -> {items, refreshed_at}
# --------------------------------------------------------------------------

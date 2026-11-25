"""个人财务数字身份证与月度结账复盘。

两块都只读本地账本，不调用模型算钱：
- 数字身份证：把「我是谁、我的钱在哪、数据从哪来、模型能做什么」收敛成一张可复核的卡片；
- 月度复盘：按自然月给出收支、环比、预算、异常、下月动作，数字全部确定性计算。

边界：身份证不读取身份证号、银行卡号、支付密码；账号接入只统计已授权连接，
不展示账号备注，也不把“已连接”说成“可代操作”。
"""

from __future__ import annotations

import calendar
import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Any

from . import analysis, db
from .analysis_health import goal_progress
from .analysis_views import _num
from .calculations._shared import pick_lang
from .calculations.cashflow_detect import detect_anomalies
from .connect import store
from .connect.catalog import get_connector
from .timeutil import now_iso as _now


def _label(zh: str, en: str, lang: str) -> str:
    """旧调用点按 (中, 英, 语言) 传参；真源是 calculations._shared.pick_lang。"""
    return pick_lang(lang, zh, en)


def _fingerprint(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "MH-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()


def _month_bounds(month: str) -> tuple[date, date]:
    if not isinstance(month, str) or len(month) != 7 or month[4] != "-":
        raise ValueError("month 需为 YYYY-MM")
    year_s, mon_s = month[:4], month[5:]
    if not (year_s.isdigit() and mon_s.isdigit()):
        raise ValueError(f"month 不是合法年月：{month}")
    year, mon = int(year_s), int(mon_s)
    if not 1 <= mon <= 12:
        raise ValueError(f"month 不是合法年月：{month}（月份 01-12）")
    last = calendar.monthrange(year, mon)[1]
    return date(year, mon, 1), date(year, mon, last)


def _previous_month(month: str) -> str:
    start, _ = _month_bounds(month)
    prev = start - timedelta(days=1)
    return prev.strftime("%Y-%m")


def _cashflow(txs: list[dict[str, Any]], essential_categories: list[str]) -> dict[str, Any]:
    income = sum(float(t.get("amount") or 0) for t in txs if float(t.get("amount") or 0) > 0)
    expense = sum(-float(t.get("amount") or 0) for t in txs if float(t.get("amount") or 0) < 0)
    by_cat: dict[str, float] = {}
    essential = 0.0
    for t in txs:
        amount = float(t.get("amount") or 0)
        if amount >= 0:
            continue
        cat = str(t.get("category") or "").strip() or "未分类"
        spent = -amount
        by_cat[cat] = by_cat.get(cat, 0.0) + spent
        if cat in essential_categories:
            essential += spent
    net = income - expense
    return {
        "income": round(income, 2),
        "expense": round(expense, 2),
        "net": round(net, 2),
        "savings_rate": round(net / income * 100, 1) if income else 0.0,
        "by_category": [
            {"category": k, "amount": round(v, 2)}
            for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])
        ],
        "essential": round(essential, 2),
        "transaction_count": len(txs),
        "uncategorized": sum(1 for t in txs if not str(t.get("category") or "").strip()),
    }


def _delta_pct(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _money_word(value: float) -> str:
    return f"{value:,.2f}"


async def identity_card(lang: str = "zh", display_name: str = "") -> dict[str, Any]:
    """生成本机财务数字身份证。只读；不暴露账号备注、密码、卡号。"""
    dash = await analysis.collect_dashboard(lang=lang)
    settings = await db.get_settings()
    debts = await db.list_debts()
    subs = await db.list_subscriptions()
    goals = await db.list_goals()
    trend = await db.monthly_trend(12)
    total_tx = await db.count_transactions()
    connections = await store.list_connections()
    current_budget = await db.budget_usage(datetime.now().astimezone().strftime("%Y-%m"))

    positions = dash.get("positions") or []
    assets = float((dash.get("totals") or {}).get("total_market_value") or 0)
    cash = sum(float(p.get("market_value") or 0) for p in positions if p.get("kind") == "现金")
    liabilities = sum(float(d.get("balance") or 0) for d in debts)
    net_worth = assets - liabilities
    invested = max(0.0, assets - cash)
    cashflow = dash.get("cashflow") or {}
    emergency = dash.get("emergency") or {}
    flags = dash.get("flags") or []

    controls: dict[str, int] = {k: 0 for k in ("read", "import", "handoff", "manual", "confirm")}
    for c in connections:
        connector = get_connector(str(c.get("connector_id") or ""))
        tier = str((connector or {}).get("control") or "manual")
        controls[tier] = controls.get(tier, 0) + 1

    active_months = sum(
        1 for m in trend if float(m.get("income") or 0) > 0 or float(m.get("expense") or 0) > 0
    )
    last_tx = (dash.get("transactions") or [{}])[0].get("date") if dash.get("transactions") else ""
    last_sync = max((str(c.get("last_sync_at") or "") for c in connections), default="")
    demo = bool((dash.get("source") or {}).get("demo"))
    seeded = bool((dash.get("source") or {}).get("seeded"))
    mode = "demo" if demo else ("seed" if seeded else "real")

    payload = {
        "display_name": display_name or _label("本机用户", "Local user", lang),
        "mode": mode,
        "assets": round(assets, 2),
        "cash": round(cash, 2),
        "invested": round(invested, 2),
        "liabilities": round(liabilities, 2),
        "net_worth": round(net_worth, 2),
        "monthly_income": float(cashflow.get("income") or 0),
        "monthly_expense": float(cashflow.get("expense") or 0),
        "monthly_net": float(cashflow.get("net") or 0),
        "transactions": total_tx,
        "positions": len(positions),
        "connections": len(connections),
        "goals": len(goals),
    }
    fp = _fingerprint(payload)

    ai_can = (
        ["读取本机账本", "整理流水与分类", "起草月报与交易指令", "生成可复核摘要"]
        if lang == "zh"
        else ["Read the local ledger", "Organize transactions", "Draft reports and trade intents", "Generate verifiable summaries"]
    )
    ai_cannot = (
        ["代登录任何平台", "代转账或代下实盘单", "读取身份证号/卡号/密码", "绕过平台风控"]
        if lang == "zh"
        else ["Log in to any platform", "Transfer money or place live orders", "Read ID/card numbers or passwords", "Bypass platform risk controls"]
    )

    return {
        "generated_at": _now(),
        "fingerprint": fp,
        "profile": {
            "display_name": payload["display_name"],
            "mode": mode,
            "mode_label": _label({"real": "真实账本", "demo": "演示账本", "seed": "示例账本"}[mode], {"real": "Real ledger", "demo": "Demo ledger", "seed": "Sample ledger"}[mode], lang),
            "base_currency": "CNY",
            "storage": _label("本机 SQLite；不读取身份证号、卡号、密码", "Local SQLite; no ID, card number or password is read", lang),
        },
        "financials": {
            "assets": round(assets, 2),
            "cash": round(cash, 2),
            "invested": round(invested, 2),
            "liabilities": round(liabilities, 2),
            "net_worth": round(net_worth, 2),
            "monthly_income": round(float(cashflow.get("income") or 0), 2),
            "monthly_expense": round(float(cashflow.get("expense") or 0), 2),
            "monthly_net": round(float(cashflow.get("net") or 0), 2),
            "savings_rate": float(cashflow.get("savings_rate") or 0),
            "expected_monthly_income": _num(settings.get("monthly_income")),
            "emergency_months": float(emergency.get("months_covered") or 0),
            "emergency_target_months": float(emergency.get("target_months") or 0),
            "dti_pct": float((dash.get("debts") or {}).get("dti_pct") or 0),
            "risk_flags": len(flags),
        },
        "coverage": {
            "positions": len(positions),
            "transactions": total_tx,
            "active_months": active_months,
            "subscriptions": len(subs),
            "debts": len(debts),
            "goals": len(goals),
            "connections": len(connections),
            "budget_set": bool(current_budget.get("total_budget")),
            "accounts_by_control": controls,
        },
        "risk": {
            "count": len(flags),
            "items": [
                {"code": str(f.get("code") or ""), "level": str(f.get("level") or "warn"), "text": str(f.get("text") or "")}
                for f in flags[:4]
            ],
            "concentration_breaches": len((dash.get("concentration") or {}).get("asset_breaches") or []),
        },
        "permissions": {
            "local_only": True,
            "revocable": True,
            "account_connections": len(connections),
            "controls": controls,
            "ai_can": ai_can,
            "ai_cannot": ai_cannot,
        },
        "provenance": {
            "ledger": _label("本地账本（SQLite）", "Local ledger (SQLite)", lang),
            "quotes": str((dash.get("source") or {}).get("quotes") or ""),
            "last_transaction": last_tx,
            "last_connection_sync": last_sync,
            "demo": demo,
            "seeded": seeded,
        },
        "boundaries": [
            _label("身份证号不读取、不保存、不出现在导出。", "No ID number is read, stored or exported.", lang),
            _label("账号接入不存密码、不模拟登录、不绕过风控。", "Account connections never store passwords, simulate login or bypass risk controls.", lang),
            _label("模型只能读取、整理、起草；转账与实盘下单由你确认。", "The model may read, organize and draft; transfers and live orders stay with you.", lang),
        ],
    }


async def monthly_review(month: str, lang: str = "zh") -> dict[str, Any]:
    """按自然月生成确定性复盘。month=YYYY-MM；未来月份直接拒绝。"""
    start, end = _month_bounds(month)
    today = date.today()
    if start > today:
        raise ValueError(_label("不能复盘未来月份", "Cannot review a future month", lang))
    in_progress = start <= today <= end
    as_of = min(today, end)
    days_in_period = as_of.day
    settings = await db.get_settings()
    cats = [c.strip() for c in str(settings.get("essential_categories") or "居住,餐饮,交通").split(",") if c.strip()]
    savings_target = _num(settings.get("savings_goal"), 20.0)
    emergency_target = _num(settings.get("emergency_target_months"), 6.0)

    txs = await db.list_transactions_by_month(month)
    current = _cashflow(txs, cats)
    prev_month = _previous_month(month)
    prev_txs = await db.list_transactions_by_month(prev_month)
    previous = _cashflow(prev_txs, cats)
    budget = await db.budget_usage(month)
    subs = await db.list_subscriptions()
    debts = await db.list_debts()
    goals = goal_progress(await db.list_goals())

    # 异常检测：用目标月前 180 天的同商户样本，但只输出目标月内命中的记录。
    anomaly_start = as_of - timedelta(days=179)
    anomaly_txs = await db.list_transactions_between(anomaly_start.isoformat(), as_of.isoformat())
    anomaly_all = detect_anomalies(anomaly_txs, as_of=as_of, lookback_days=180)
    anomalies = [a for a in anomaly_all.get("items", []) if str(a.get("date") or "").startswith(month)]

    days_with_tx = len({str(t.get("date") or "") for t in txs if t.get("date")})
    coverage_pct = round(days_with_tx / max(1, days_in_period) * 100, 1)
    sub_total = round(sum(float(s.get("monthly") or 0) for s in subs), 2)
    debt_total = round(sum(float(d.get("balance") or 0) for d in debts), 2)
    debt_monthly = round(sum(float(d.get("monthly") or 0) for d in debts), 2)
    income_for_dti = current["income"] or _num(settings.get("monthly_income"))
    dti_pct = round(debt_monthly / income_for_dti * 100, 1) if income_for_dti else 0.0

    # 应急金只用现金类持仓，不用总资产；没有现金记录时明确为 0。
    positions = await db.list_positions()
    cash = sum(
        float(p.get("shares") or 0) * float(p.get("last") or 0)
        for p in positions
        if p.get("kind") == "现金"
    )
    emergency_months = round(cash / current["essential"], 1) if current["essential"] else 0.0

    over_categories = [c for c in (budget.get("categories") or []) if c.get("over")]
    top_over = max(over_categories, key=lambda c: float(c.get("spent") or 0) - float(c.get("budget") or 0), default=None)
    top_categories = [
        {"category": c["category"], "amount": c["amount"], "share_pct": round(c["amount"] / current["expense"] * 100, 1) if current["expense"] else 0.0}
        for c in current["by_category"][:8]
    ]
    goals_gap = round(sum(float(g.get("gap") or 0) for g in goals), 2)
    goals_behind = [
        g for g in goals
        if g.get("monthly_suggest") is not None and float(g["monthly_suggest"]) > current["net"]
    ]
    top_subs = sorted(subs, key=lambda s: -float(s.get("monthly") or 0))[:3]

    checks = [
        {"id": "ledger", "label": _label("本月有流水", "Transactions recorded", lang), "ok": len(txs) > 0},
        {"id": "income", "label": _label("收入已记录", "Income recorded", lang), "ok": current["income"] > 0},
        {"id": "expense", "label": _label("支出已记录", "Expenses recorded", lang), "ok": current["expense"] > 0},
        {"id": "category", "label": _label("没有未分类流水", "No uncategorized transactions", lang), "ok": current["uncategorized"] == 0 and len(txs) > 0},
        {"id": "budget", "label": _label("本月预算已设置", "Budget set for this month", lang), "ok": bool(budget.get("total_budget"))},
    ]
    passed = sum(1 for c in checks if c["ok"])
    completeness = round(passed / len(checks) * 100, 1)

    actions: list[dict[str, Any]] = []

    def add_action(code: str, title: str, detail: str, amount: float | None = None) -> None:
        actions.append({
            "code": code,
            "title": title,
            "detail": detail,
            "amount": round(amount, 2) if amount is not None else None,
        })

    if not txs:
        add_action(
            "NO_DATA",
            _label("先补录本月流水", "Record this month's transactions first", lang),
            _label("本月 0 笔流水，任何复盘结论都会失真；先导入账单或手动记几笔收入与支出。",
               "0 transactions this month makes any review unreliable; import a statement or add income and expenses first.", lang),
        )
    if not budget.get("total_budget"):
        add_action(
            "BUDGET_UNSET",
            _label("先给必要支出设预算", "Set a budget for essential spending", lang),
            _label("本月预算未设置；先给居住、餐饮、交通等必要支出设一个月度上限，下月复盘才有超支判断。",
               "No budget is set; add a monthly cap for essentials such as housing, food and transport so overspending can be judged next month.", lang),
        )
    if current["income"] > 0 and current["net"] < 0:
        add_action(
            "CASHFLOW_DEFICIT",
            _label("先把支出压回收入以内", "Bring spending back below income", lang),
            _label(f"本月支出比收入多 {_money_word(-current['net'])} 元；下月先找出一笔可延后的大额支出。",
               f"Spending exceeded income by {_money_word(-current['net'])} CNY; defer one large non-essential item next month.", lang),
            -current["net"],
        )
    if current["income"] > 0 and current["savings_rate"] < savings_target:
        gap = max(0.0, (savings_target - current["savings_rate"]) / 100 * current["income"])
        add_action(
            "SAVINGS_BELOW_TARGET",
            _label("发薪先锁定结余", "Lock in savings on payday", lang),
            _label(f"结余率 {current['savings_rate']}% 低于目标 {savings_target:g}%；下月发薪先转 {_money_word(gap)} 元。",
               f"Savings rate {current['savings_rate']}% is below the {savings_target:g}% target; move {_money_word(gap)} CNY out on payday.", lang),
            gap,
        )
    if top_over:
        over = float(top_over.get("spent") or 0) - float(top_over.get("budget") or 0)
        add_action(
            "BUDGET_OVER",
            _label(f"把「{top_over['category']}」压回预算", f"Bring {top_over['category']} back under budget", lang),
            _label(f"该分类超预算 {_money_word(over)} 元；下月先设一个每周上限。",
               f"This category is {_money_word(over)} CNY over budget; set a weekly cap next month.", lang),
            over,
        )
    if anomalies:
        total_anom = sum(float(a.get("amount") or 0) for a in anomalies)
        add_action(
            "ANOMALY_REVIEW",
            _label(f"核对 {len(anomalies)} 笔异常支出", f"Review {len(anomalies)} anomalous transactions", lang),
            _label(f"合计 {_money_word(total_anom)} 元；先看是否为一次性大额、误扣或重复扣款。",
               f"Total {_money_word(total_anom)} CNY; check for one-off purchases, mistaken or duplicate charges.", lang),
            total_anom,
        )
    if current["essential"] > 0 and emergency_months < emergency_target:
        target_cash = emergency_target * current["essential"]
        add_action(
            "EMERGENCY_GAP",
            _label("补应急金", "Top up the emergency fund", lang),
            _label(f"现金覆盖 {emergency_months} 个月，低于目标 {emergency_target:g} 个月；缺口约 {_money_word(max(0.0, target_cash - cash))} 元。",
               f"Cash covers {emergency_months} months vs the {emergency_target:g}-month target; gap about {_money_word(max(0.0, target_cash - cash))} CNY.", lang),
            max(0.0, target_cash - cash),
        )
    if sub_total > 0:
        add_action(
            "SUBSCRIPTION_AUDIT",
            _label(f"审计 {len(subs)} 项订阅", f"Audit {len(subs)} subscriptions", lang),
            _label(f"月支出 {_money_word(sub_total)} 元；逐项确认过去 30 天是否真的用过。",
               f"{_money_word(sub_total)} CNY per month; confirm each was actually used in the last 30 days.", lang),
            sub_total,
        )
    if goals_behind:
        need = sum(float(g["monthly_suggest"]) for g in goals_behind)
        add_action(
            "GOAL_BEHIND",
            _label("目标进度需要重排", "Reschedule lagging goals", lang),
            _label(f"{len(goals_behind)} 个目标按当前结余会落后，合计每月需 {_money_word(need)} 元；延长截止月或降低目标。",
               f"{len(goals_behind)} goals will lag at the current surplus, needing {_money_word(need)} CNY/month; extend deadlines or lower targets.", lang),
            need,
        )
    if not actions:
        add_action(
            "MAINTAIN",
            _label("保持，并把结余转走", "Keep it up and move the surplus", lang),
            _label(f"本月没有硬性异常；把结余 {_money_word(max(0.0, current['net']))} 元转入应急金或目标账户。",
               f"No hard exceptions this month; move the {_money_word(max(0.0, current['net']))} CNY surplus to emergency savings or goals.", lang),
            max(0.0, current["net"]),
        )
    actions = actions[:3]

    headline = _label(
        f"{month}{'（截至 ' + as_of.isoformat()[5:] + '）' if in_progress else ''}：收入 {_money_word(current['income'])}，支出 {_money_word(current['expense'])}，结余 {_money_word(current['net'])}；储蓄率 {current['savings_rate']}%。",
        f"{month}{' (to ' + as_of.isoformat()[5:] + ')' if in_progress else ''}: income {_money_word(current['income'])}, expense {_money_word(current['expense'])}, net {_money_word(current['net'])}; savings rate {current['savings_rate']}%.",
        lang,
    )
    verdict_parts = []
    if current["income"] <= 0:
        verdict_parts.append(_label("本月没有收入记录，复盘只能看支出。", "No income was recorded, so this review only covers spending.", lang))
    elif current["net"] < 0:
        verdict_parts.append(_label(f"支出超过收入 {_money_word(-current['net'])} 元。", f"Spending exceeded income by {_money_word(-current['net'])} CNY.", lang))
    else:
        verdict_parts.append(_label(f"结余为正，储蓄率 {current['savings_rate']}%。", f"Surplus is positive; savings rate {current['savings_rate']}%.", lang))
    if over_categories:
        verdict_parts.append(_label(f"{len(over_categories)} 个分类超预算。", f"{len(over_categories)} categories are over budget.", lang))
    if anomalies:
        verdict_parts.append(_label(f"{len(anomalies)} 笔异常支出待核对。", f"{len(anomalies)} anomalous transactions need review.", lang))
    elif len(txs) > 0:
        verdict_parts.append(_label("没有发现明显异常支出。", "No obvious anomalous spending found.", lang))
    verdict = " ".join(verdict_parts)

    payload = {
        "month": month,
        "income": current["income"],
        "expense": current["expense"],
        "net": current["net"],
        "savings_rate": current["savings_rate"],
        "transactions": len(txs),
        "budget_total": budget.get("total_budget"),
        "over_count": len(over_categories),
        "anomaly_count": len(anomalies),
        "connections": 0,
    }
    fp = _fingerprint(payload)

    return {
        "month": month,
        "generated_at": _now(),
        "fingerprint": fp,
        "status": "in_progress" if in_progress else "closed",
        "period": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "as_of": as_of.isoformat(),
            "days_in_period": days_in_period,
        },
        "headline": headline,
        "verdict": verdict,
        "savings_target": savings_target,
        "cashflow": {
            **current,
            "top_categories": top_categories,
            "previous": {
                "month": prev_month,
                **previous,
                "income_delta_pct": _delta_pct(current["income"], previous["income"]),
                "expense_delta_pct": _delta_pct(current["expense"], previous["expense"]),
                "net_delta": round(current["net"] - previous["net"], 2),
            },
        },
        "budget": {
            "total": float(budget.get("total_budget") or 0),
            "spent": float(budget.get("total_spent") or 0),
            "pct": float(budget.get("total_pct") or 0),
            "over": bool(budget.get("over")),
            "over_categories": over_categories,
            "categories": budget.get("categories") or [],
        },
        "categories": top_categories,
        "subscriptions": {
            "count": len(subs),
            "monthly_total": sub_total,
            "annual_total": round(sub_total * 12, 2),
            "top": [
                {"name": str(s.get("name") or ""), "monthly": float(s.get("monthly") or 0)}
                for s in top_subs
            ],
        },
        "debts": {
            "count": len(debts),
            "balance": debt_total,
            "monthly": debt_monthly,
            "dti_pct": dti_pct,
        },
        "goals": {
            "count": len(goals),
            "done": sum(1 for g in goals if g.get("done")),
            "behind": len(goals_behind),
            "gap": goals_gap,
        },
        "anomalies": {
            "count": len(anomalies),
            "total": round(sum(float(a.get("amount") or 0) for a in anomalies), 2),
            "items": anomalies[:5],
        },
        "coverage": {
            "transactions": len(txs),
            "days_with_transactions": days_with_tx,
            "days_in_period": days_in_period,
            "coverage_pct": coverage_pct,
            "uncategorized": current["uncategorized"],
            "budget_set": bool(budget.get("total_budget")),
        },
        "closing": {
            "checks": checks,
            "passed": passed,
            "total": len(checks),
            "completeness_pct": completeness,
            "ready": passed >= len(checks) - 1,
            "note": _label("这是复盘前的数据体检，不是会计锁账；不会冻结流水。", "A pre-review data check, not an accounting lock; transactions are not frozen.", lang),
        },
        "actions": actions,
        "disclaimer": _label(
            "数字来自本机账本；预算、分类与储蓄目标口径以设置页为准；不构成投资建议。",
            "Figures come from the local ledger; budget, category and savings targets follow Settings; not investment advice.",
            lang,
        ),
    }

"""确定性分析内核：持仓、现金流、负债、应急金、风控规则。

原则：数字只来自数据，规则永远比模型可靠。模型只负责把这里的结果"讲成人话"，
模板叙述则保证无模型时也能给出完整、可复核的回答。

本模块不碰网络（行情由 quotes 层负责），纯函数均可单测。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

from . import db, quotes

DISCLAIMER = "以上为基于你的组合与账本数据的洞察，不构成投资建议。"
DISCLAIMER_EN = "This is an insight based on your portfolio and ledger data, not investment advice."
CONCENTRATION_MAX_PCT = 40.0
DTI_WARN_PCT = 40.0
SAVINGS_RATE_WARN_PCT = 20.0
HIGH_RATE_DEBT = 0.08

# /api/dashboard 的短 TTL 缓存（M5.3）。
# 为什么需要：仪表盘被前端 4 个组件 + 对话 + MCP 同时拉，原来每次都要
# 读全表流水、算风控、打两次外部行情。10 秒内的重复请求应该复用同一份快照。
# 为什么不长：行情会变，用户改完持仓立刻刷新必须看到新数字。
_DASHBOARD_TTL_SECONDS = 10.0
_dashboard_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _month_prefix() -> str:
    return datetime.now().strftime("%Y-%m")


# --------------------------------------------------------------------------
# 市场视角
# --------------------------------------------------------------------------


def market_view(
    positions: list[dict[str, Any]], live: dict[str, float]
) -> dict[str, Any]:
    """持仓明细 + 市值/盈亏 + 集中度（按标的、按行业）。"""
    rows, total_mv, total_cost = [], 0.0, 0.0
    for p in positions:
        last = live.get(p["symbol"], float(p["last"]))
        mv = p["shares"] * last
        cost = p["shares"] * p["cost"]
        total_mv += mv
        total_cost += cost
        rows.append(
            {
                "symbol": p["symbol"],
                "name": p["name"],
                "kind": p["kind"],
                "industry": p["industry"],
                "shares": p["shares"],
                "last": round(last, 4),
                # 注意：cost / market_value 都是**总额**（单价 × 股数），
                # 前端若需要单价必须读 cost_per_share，不能直接把 cost 回填到"每股成本"输入框。
                "cost": round(cost, 2),
                "cost_per_share": round(float(p["cost"]), 6),
                "market_value": round(mv, 2),
                "pnl": round(mv - cost, 2),
                "pnl_pct": round((mv - cost) / cost * 100, 2) if cost else 0.0,
            }
        )

    # 集中度分母用「非现金市值」：现金占大头时不应稀释真实投资资产占比，
    # 否则单只股票的相对集中度被低估、可能漏报超限。若无非现金资产则回退总市值。
    non_cash_mv = sum(r["market_value"] for r in rows if r["kind"] != "现金")
    concentration_denom = non_cash_mv or total_mv

    # 两个口径必须分开，否则会同时出两种错：
    # - pct：相对**总市值**，各项之和 = 100%，供资产分布饼图与持仓表使用
    # - investable_pct：相对**非现金市值**，用于集中度判定（现金不该稀释股票权重）
    # 历史 bug：现金行也拿 non_cash_mv 当分母 → 所有 pct 之和 = 126%，
    # 且现金显示 26.3%（真实应为 20.8%），前端同屏出现两个不同百分比。
    by_asset = []
    for r in rows:
        by_asset.append(
            {
                "name": r["name"],
                "kind": r["kind"],
                "pct": round(r["market_value"] / total_mv * 100, 1) if total_mv else 0.0,
                "investable_pct": round(r["market_value"] / concentration_denom * 100, 1)
                if concentration_denom
                else 0.0,
                "market_value": r["market_value"],
            }
        )
    by_asset.sort(key=lambda x: -x["pct"])

    agg: dict[str, float] = {}
    for r in rows:
        agg[r["industry"]] = agg.get(r["industry"], 0.0) + r["market_value"]
    by_industry = [
        {
            "industry": k,
            "pct": round(v / total_mv * 100, 1) if total_mv else 0.0,
            "investable_pct": round(v / concentration_denom * 100, 1) if concentration_denom else 0.0,
        }
        for k, v in sorted(agg.items(), key=lambda kv: -kv[1])
    ]

    return {
        "positions": rows,
        "total_market_value": round(total_mv, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": round(total_mv - total_cost, 2),
        "total_pnl_pct": round((total_mv - total_cost) / total_cost * 100, 2)
        if total_cost
        else 0.0,
        "concentration": {
            "threshold_pct": CONCENTRATION_MAX_PCT,
            "by_asset": by_asset,
            "by_industry": by_industry,
            "asset_breaches": [
                a
                for a in by_asset
                if a["investable_pct"] > CONCENTRATION_MAX_PCT and a["kind"] != "现金"
            ],
            "industry_breaches": [
                i
                for i in by_industry
                if i["investable_pct"] > CONCENTRATION_MAX_PCT and i["industry"] != "现金"
            ],
        },
    }


# --------------------------------------------------------------------------
# 账本视角
# --------------------------------------------------------------------------


def ledger_view(
    transactions: list[dict[str, Any]],
    subscriptions: list[dict[str, Any]],
    debts: list[dict[str, Any]],
    settings: dict[str, str],
    positions: list[dict[str, Any]],
    live: dict[str, float],
) -> dict[str, Any]:
    """本月现金流 + 订阅 + 负债 + 应急金。所有"本月"口径都按 date 前缀过滤。"""
    month = _month_prefix()
    txs = [t for t in transactions if str(t.get("date", "")).startswith(month)]

    income = sum(t["amount"] for t in txs if t["amount"] > 0)
    expense = sum(-t["amount"] for t in txs if t["amount"] < 0)
    by_cat: dict[str, float] = {}
    for t in txs:
        if t["amount"] < 0:
            by_cat[t["category"]] = by_cat.get(t["category"], 0.0) + -t["amount"]
    ranked = sorted(by_cat.items(), key=lambda kv: -kv[1])

    subs_total = sum(s["monthly"] for s in subscriptions)
    income_num = _num(settings.get("monthly_income"))
    debt_monthly = sum(d["monthly"] for d in debts)
    dti = round(debt_monthly / income_num * 100, 1) if income_num else 0.0

    cash = sum(
        p["shares"] * live.get(p["symbol"], float(p["last"]))
        for p in positions
        if p["kind"] == "现金"
    )
    cats = [
        c.strip()
        for c in settings.get("essential_categories", "居住,餐饮,交通").split(",")
        if c.strip()
    ]
    essential = sum(
        -t["amount"] for t in txs if t["amount"] < 0 and t["category"] in cats
    )
    target = _num(settings.get("emergency_target_months"))
    has_data = essential > 0
    months = round(cash / essential, 1) if essential else 0.0

    return {
        "month": month,
        "income": round(income, 2),
        "expense": round(expense, 2),
        "net": round(income - expense, 2),
        "savings_rate": round((income - expense) / income * 100, 1) if income else 0.0,
        "by_category": [{"category": k, "amount": round(v, 2)} for k, v in ranked[:6]],
        "subscription_monthly": round(subs_total, 2),
        "subscription_annual": round(subs_total * 12, 2),
        "debt_monthly": round(debt_monthly, 2),
        "dti_pct": dti,
        "high_rate_debts": [d for d in debts if d["rate"] >= HIGH_RATE_DEBT],
        "emergency": {
            "cash": round(cash, 2),
            "essential_monthly": round(essential, 2),
            "essential_categories": cats,
            "months_covered": months,
            "target_months": target,
            "has_data": has_data,
            "ok": (months >= target if target else True) if has_data else True,
        },
    }


def _num(raw: Any, default: float = 0.0) -> float:
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# 风控规则（确定性，不依赖模型）
# --------------------------------------------------------------------------


def risk_checks(
    market: dict[str, Any] | None,
    ledger: dict[str, Any] | None,
    lang: str = "zh",
) -> list[dict[str, str]]:
    """风控告警 flags：每条带稳定 `code`（供前端聚合/跳转）；`text` 按 lang 输出英/中。

    仅字符串分支切换，无额外 I/O，不影响性能/响应。
    """
    en = lang != "zh"
    flags: list[dict[str, str]] = []

    if market:
        conc = market.get("concentration") or {}
        for b in conc.get("asset_breaches", []):
            flags.append(
                {
                    "level": "warn",
                    "code": "CONCENTRATION",
                    "text": (
                        f"{b['name']} {b.get('investable_pct') or b['pct']}% of investable assets — above the {conc.get('threshold_pct')}% single-position cap"
                        if en
                        else f"{b['name']} 占比 {b.get('investable_pct') or b['pct']}% 超过 {conc.get('threshold_pct')}% 单一持仓阈值"
                    ),
                }
            )
        for b in conc.get("industry_breaches", []):
            flags.append(
                {
                    "level": "warn",
                    "code": "CONCENTRATION",
                    "text": (
                        f"{b['industry']} industry {b.get('investable_pct') or b['pct']}% of investable assets — above the {conc.get('threshold_pct')}% cap"
                        if en
                        else f"{b['industry']} 行业占比 {b.get('investable_pct') or b['pct']}% 超过 {conc.get('threshold_pct')}% 阈值"
                    ),
                }
            )

    if ledger:
        em = ledger.get("emergency") or {}
        if em and em.get("has_data") and not em.get("ok"):
            flags.append(
                {
                    "level": "warn",
                    "code": "EMERGENCY_FUND",
                    "text": (
                        f"Emergency fund covers only {em.get('months_covered')} months — below the {em.get('target_months')} month target"
                        if en
                        else f"应急金仅覆盖 {em.get('months_covered')} 个月，低于 {em.get('target_months')} 个月目标"
                    ),
                }
            )
        for d in ledger.get("high_rate_debts", []):
            flags.append(
                {
                    "level": "warn",
                    "code": "HIGH_RATE_DEBT",
                    "text": (
                        f"{d['name']} at {d['rate'] * 100:.1f}% — high-interest debt"
                        if en
                        else f"{d['name']} 利率 {d['rate'] * 100:.1f}%，属高息负债"
                    ),
                }
            )
        if ledger.get("dti_pct", 0) > DTI_WARN_PCT:
            flags.append(
                {
                    "level": "warn",
                    "code": "DTI",
                    "text": (
                        f"Debt-to-income {ledger['dti_pct']}% — above the {DTI_WARN_PCT:.0f}% warning line"
                        if en
                        else f"负债收入比 {ledger['dti_pct']}% 超过 {DTI_WARN_PCT:.0f}% 警戒线"
                    ),
                }
            )
        # 无收入记录时储蓄率不可计算，报「0% 偏低」是数据缺失的伪信号
        if ledger.get("income", 0) > 0 and ledger.get("savings_rate", 100) < SAVINGS_RATE_WARN_PCT:
            flags.append(
                {
                    "level": "warn",
                    "code": "SAVINGS_RATE",
                    "text": (
                        f"Savings rate {ledger.get('savings_rate')}% is low (aim ≥ {SAVINGS_RATE_WARN_PCT:.0f}%)"
                        if en
                        else f"储蓄率 {ledger.get('savings_rate')}% 偏低（建议不低于 {SAVINGS_RATE_WARN_PCT:.0f}%）"
                    ),
                }
            )
    return flags


def next_step_advice(flags: list[dict[str, str]], has_data: bool = True, lang: str = "zh") -> str:
    """基于确定性风控告警，给一句「下一步可以做什么」的主动引导（差异化「主动理财 Agent」）。

    厂商 Agent 大多是「回答完就停」；Moneyhelper 识别出风险后会结合 code 主动给一句可执行的
    动作建议（记账/储蓄/目标/加自选），不编数字、不给买卖指令。纯确定性、按 code 匹配。
    无风险或空库时返回空串（不硬塞引导，避免噪音）。
    """
    if not has_data or not flags:
        return ""
    en = lang != "zh"
    # 按 code 去重，按重要程度排序，最多给 2 条，避免刷屏
    order = ("EMERGENCY_FUND", "HIGH_RATE_DEBT", "SAVINGS_RATE", "DTI", "CONCENTRATION")
    seen: set[str] = set()
    picked: list[str] = []
    for code in order:
        if any(f.get("code") == code for f in flags) and code not in seen:
            seen.add(code)
            picked.append(code)
    if not picked:
        return ""
    tips: list[str] = []
    for code in picked[:2]:
        if code == "EMERGENCY_FUND":
            tips.append(
                "Set a monthly savings target so your emergency fund reaches 6 months of essentials"
                if en else "可以设一个每月储蓄目标，把应急金补到 6 个月的必要支出"
            )
        elif code == "HIGH_RATE_DEBT":
            tips.append(
                "List your high-interest debts and plan to repay the highest-rate one first"
                if en else "把高息负债逐条列进「记账」，优先还利率最高的一笔"
            )
        elif code == "SAVINGS_RATE":
            tips.append(
                "Try auto-saving a fixed amount each payday to lift your savings rate above 20%"
                if en else "试试每月发薪日固定存一笔，把储蓄率提到 20% 以上"
            )
        elif code == "DTI":
            tips.append(
                "Review recurring debt payments and keep total debt service below 30% of income"
                if en else "盘一下负债月供，尽量让每月还款不超过收入的 30%"
            )
        elif code == "CONCENTRATION":
            tips.append(
                "Consider rebalancing so no single holding or industry exceeds the 40% cap"
                if en else "可考虑再平衡，让单一持仓或行业不超过 40% 上限"
            )
    if not tips:
        return ""
    prefix = "A next step you could take: " if en else "下一步你可以："
    return prefix + "；".join(tips) + ("." if en else "。")


# --------------------------------------------------------------------------
# 模板叙述（无模型时的完整回答；模型存在时用于兜底）
# --------------------------------------------------------------------------


NO_DATA_ANSWER = (
    "你还没有录入任何数据，所以我给不出数字。现在可以做的是：\n"
    "- 去「记账」用一句话记一笔（例如「昨天打车 32 元」）；\n"
    "- 或添加持仓后，我帮你算盈亏、集中度和风险。\n"
    "录入之后，这些问题就能直接回答：我的钱花到哪了、持仓有什么风险、应急金够不够。"
)
NO_DATA_ANSWER_EN = (
    "You haven't recorded any data yet, so I can't give you numbers. What you can do now:\n"
    "- Record a transaction in Ledger with one sentence (e.g. \"Taxi 32 yuan yesterday\");\n"
    "- Or add holdings, then I can calculate P&L, concentration and risk.\n"
    "Once you do, I can answer: where my money went, risks in my holdings, and whether the emergency fund is enough."
)


def no_data_answer(lang: str = "zh") -> str:
    """空库引导文案（跟随界面语言）。"""
    return NO_DATA_ANSWER if lang == "zh" else NO_DATA_ANSWER_EN


def template_answer(
    market: dict[str, Any] | None,
    ledger: dict[str, Any] | None,
    flags: list[dict[str, str]],
    has_data: bool = True,
    lang: str = "zh",
) -> str:
    # 空库不给零值报告（「总市值 0 元 + 储蓄率 0% 偏低」是新用户劝退组合）
    if not has_data:
        return no_data_answer(lang)

    en = lang != "zh"
    parts: list[str] = []

    if market:
        m = market
        # 方向必须按盈亏正负切换：亏损时写"浮盈 -12.58%"自相矛盾。
        if en:
            word = "up" if m["total_pnl"] >= 0 else "down"
        else:
            word = "浮盈" if m["total_pnl"] >= 0 else "浮亏"
        line = (
            f"Your portfolio value is ¥{m['total_market_value']:,.0f}, {word} "
            f"¥{abs(m['total_pnl']):,.0f} ({m['total_pnl_pct']}%)."
            if en
            else f"你的组合总市值 {m['total_market_value']:,.0f} 元，{word} "
            f"{abs(m['total_pnl']):,.0f} 元（{m['total_pnl_pct']}%）。"
        )
        conc = m["concentration"]
        if conc["by_asset"]:
            top = conc["by_asset"][0]
            if en:
                note = f"Largest holding {top['name']} is {top.get('investable_pct') or top['pct']}% of investable assets."
                if (top.get("investable_pct") or top["pct"]) > conc["threshold_pct"]:
                    note += f" That's above the {conc['threshold_pct']}% concentration cap."
            else:
                note = f"最大单一持仓 {top['name']} 占可投资资产的 {top.get('investable_pct') or top['pct']}%。"
                if (top.get("investable_pct") or top["pct"]) > conc["threshold_pct"]:
                    note += f" 已超过 {conc['threshold_pct']}% 集中度阈值。"
            line += note
        parts.append(line)

    if ledger:
        ld = ledger
        em = ld["emergency"]
        if em.get("has_data"):
            em_line = (
                f"Emergency fund covers {em['months_covered']} months (target {em['target_months']})."
                if en
                else f"应急金可覆盖 {em['months_covered']} 个月（目标 {em['target_months']} 个月）。"
            )
        else:
            em_line = (
                f"No essential expenses recorded this month — emergency fund coverage can't be "
                f"estimated (cash ¥{em['cash']:,.0f})."
                if en
                else f"本月暂无必要支出记录，应急金（现金 {em['cash']:,.0f} 元）覆盖月数暂无法估算。"
            )
        parts.append(
            (
                f"{ld['month']} income ¥{ld['income']:,.0f}, expenses ¥{ld['expense']:,.0f}, "
                f"net ¥{ld['net']:,.0f} (savings rate {ld['savings_rate']}%). "
                f"Subscriptions ¥{ld['subscription_monthly']:,.0f}/mo, debt ¥{ld['debt_monthly']:,.0f}/mo "
                f"({ld['dti_pct']}% of income). {em_line}"
            )
            if en
            else (
                f"{ld['month']} 收入 {ld['income']:,.0f} 元、支出 {ld['expense']:,.0f} 元，"
                f"结余 {ld['net']:,.0f} 元（储蓄率 {ld['savings_rate']}%）。"
                f"订阅月支出 {ld['subscription_monthly']:,.0f} 元，"
                f"负债月供 {ld['debt_monthly']:,.0f} 元（占收入 {ld['dti_pct']}%），"
                f"{em_line}"
            )
        )

    if flags:
        parts.append(
            (
                f"Found {len(flags)} item(s) to watch: "
                + "; ".join(f["text"] for f in flags)
                + "."
            )
            if en
            else (
                "发现 "
                + str(len(flags))
                + " 项需关注："
                + "；".join(f["text"] for f in flags)
                + "。"
            )
        )
    else:
        parts.append(
            "No significant risks found — your financial situation looks stable."
            if en
            else "未发现明显风险项，当前财务状况整体稳健。"
        )

    return "\n\n".join(parts)


# --------------------------------------------------------------------------
# 一站式：取数 + 计算（供服务层与 /api/dashboard 共用）
# --------------------------------------------------------------------------


async def collect_dashboard(lang: str = "zh", *, use_cache: bool = True) -> dict[str, Any]:
    """仪表盘所需全部数据：持仓/账本/负债/风控/来源。lang 决定 flags 与来源标签语言。

    短 TTL 缓存（默认 10s）：同一租户 + 语言在窗口内复用同一份快照，
    避免多个组件并发拉取时重复打行情、重复扫流水。写操作后调用方应
    invalidate_dashboard_cache() 立即失效（见 routes/ledger.py 的写端点）。
    """
    # 缓存键必须带 DB 路径：同进程内切换数据库（测试用临时库、升级演练）
    # 时不能命中另一个库的旧快照。
    # 注意读 db._core.DB_PATH 而不是 db.DB_PATH：后者是 import 时的静态副本，
    # 测试 monkeypatch 改的是 _core 里的值，读副本会导致缓存跨测试泄漏。
    from .db import _core as db_core
    from .db.tenant import current_user_id

    key = f"{getattr(db_core, 'DB_PATH', '')}:{current_user_id()}:{lang}"
    if use_cache:
        hit = _dashboard_cache.get(key)
        if hit and time.monotonic() - hit[0] < _DASHBOARD_TTL_SECONDS:
            return hit[1]

    en = lang != "zh"
    positions = await db.list_positions()
    live = await quotes.live_quotes(positions)
    settings = await db.get_settings()
    mode = settings.get("quote_source_mode", "auto")

    # 行情源标注：快照模式固定标快照；auto/eastmoney 按本次实际生效来源标注（按 lang 本地化）
    if mode == "snapshot":
        quotes_label = "Snapshot price" if en else "组合库快照价"
    elif quotes.last_source() == "eastmoney":
        quotes_label = "Eastmoney live price" if en else "东方财富实时价"
    else:
        quotes_label = ("Snapshot price (live source unavailable)" if en else "组合库快照价（实时源不可用，自动降级）")

    m = market_view(positions, live)
    month = _month_prefix()
    cats = [
        c.strip()
        for c in settings.get("essential_categories", "居住,餐饮,交通").split(",")
        if c.strip()
    ]
    # M5.3：本月现金流走 SQL 聚合；流水明细只取最近 500 条 + 总数，
    # 账本十万行时不必把整库搬进内存再序列化给浏览器。
    cashflow = await db.month_cashflow(month, cats)
    txs = await db.list_transactions()
    total_tx = await db.count_transactions()
    subs = await db.list_subscriptions()
    debts = await db.list_debts()
    led = ledger_view(txs, subs, debts, settings, positions, live)
    # 用 SQL 聚合值覆盖 Python 全表扫描的结果，保证两条路径口径一致且更快
    led["income"] = cashflow["income"]
    led["expense"] = cashflow["expense"]
    led["net"] = cashflow["net"]
    led["savings_rate"] = cashflow["savings_rate"]
    led["by_category"] = cashflow["by_category"]
    flags = risk_checks(m, led, lang)
    goals = goal_progress(await db.list_goals())
    # 三个外部行情请求并行：最坏路径由串行的 8s+4s+12s 压缩为取最大者
    indices, today_pnl = await asyncio.gather(quotes.indices_quotes(), quotes.portfolio_today_pnl(positions))

    out = {
        "positions": m["positions"],
        "goals": goals,
        "totals": {
            "total_market_value": m["total_market_value"],
            "total_cost": m["total_cost"],
            "total_pnl": m["total_pnl"],
            "total_pnl_pct": m["total_pnl_pct"],
        },
        "concentration": m["concentration"],
        "cashflow": {
            k: led[k]
            for k in (
                "month",
                "income",
                "expense",
                "net",
                "savings_rate",
                "by_category",
            )
        },
        "subscriptions": {
            "items": subs,
            "monthly_total": led["subscription_monthly"],
            "annual_total": led["subscription_annual"],
        },
        "debts": {
            "items": debts,
            "monthly_total": led["debt_monthly"],
            "dti_pct": led["dti_pct"],
        },
        "emergency": led["emergency"],
        "flags": flags,
        "indices": indices,
        "today_pnl": today_pnl,
        "transactions": txs[:500],
        "transactions_total": total_tx,
        "source": {
            "portfolio": "Local portfolio (SQLite)" if en else "本地组合库（SQLite）",
            "ledger": "Local ledger (SQLite)" if en else "本地账本（SQLite）",
            "quotes": quotes_label,
            "seeded": settings.get("data_note", "") == "seed",
        },
    }
    if use_cache:
        _dashboard_cache[key] = (time.monotonic(), out)
    return out


def invalidate_dashboard_cache() -> None:
    """清空仪表盘缓存。任何写操作（记账/持仓/设置）后调用，保证下次读取是新数据。"""
    _dashboard_cache.clear()


# ---------------------------------------------------------------------------
# 财务目标 / 体检
# ---------------------------------------------------------------------------


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


def health_check(
    market: dict[str, Any] | None,
    ledger: dict[str, Any] | None,
    flags: list[dict[str, Any]],
    goals: list[dict[str, Any]] | None = None,
    lang: str = "zh",
) -> dict[str, Any]:
    """结构化财务体检：资产配置 / 现金流 / 负债 / 应急金 / 目标进度 五维评分。

    每维度返回 status（good/warn/bad）+ 一句 human 可读结论。纯函数，供工具与 REST 复用。
    lang：zh → 中文文案；en → 英文文案（界面语言跟随）。
    """
    en = lang != "zh"
    dims: list[dict[str, Any]] = []

    # 1) 资产配置
    conc = (market or {}).get("concentration") or {}
    breaches = conc.get("asset_breaches", [])
    if breaches:
        dims.append({
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
        })
    elif market:
        m = market
        word = "gain" if en else "浮盈"
        loss_word = "loss" if en else "浮亏"
        label = word if m["total_pnl"] >= 0 else loss_word
        dims.append({
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
        })

    # 2) 现金流 / 储蓄率（本月无收入时储蓄率不可算，跳过该维度避免伪信号）
    if ledger and ledger.get("income", 0) > 0:
        sr = ledger.get("savings_rate", 0)
        net = ledger.get("net", 0)
        if sr < SAVINGS_RATE_WARN_PCT:
            dims.append({
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
            })
        elif sr >= 20:
            dims.append({
                "key": "cashflow",
                "title": "Cash flow" if en else "现金流",
                "status": "good",
                "detail": (
                    f"Net this month {net:,.0f} CNY, savings rate {sr}% — healthy range."
                    if en
                    else f"本月结余 {net:,.0f} 元，储蓄率 {sr}%，处于健康区间。"
                ),
                "suggestion": "",
            })

    # 3) 负债健康
    if ledger:
        dti = ledger.get("dti_pct", 0)
        high = ledger.get("high_rate_debts") or []
        if dti > DTI_WARN_PCT or high:
            detail_zh = f"负债月供占收入 {dti}%（建议线 {DTI_WARN_PCT}%）" + (f"，存在高息负债：{high[0]['name']}" if high else "")
            detail_en = f"Debt payments are {dti}% of income (target {DTI_WARN_PCT}%)" + (f", high-interest debt: {high[0]['name']}" if high else "")
            dims.append({
                "key": "debt",
                "title": "Debt health" if en else "负债健康",
                "status": "warn" if not high else "bad",
                "detail": detail_en if en else detail_zh,
                "suggestion": (
                    "Pay off high-interest debt first (e.g. credit-card installments), then consider new debt."
                    if en
                    else "优先偿还高息负债（如信用卡分期），再考虑新增负债。"
                ),
            })
        elif ledger.get("debt_monthly", 0) == 0:
            dims.append({
                "key": "debt",
                "title": "Debt health" if en else "负债健康",
                "status": "good",
                "detail": "No debt payments — clean financial structure." if en else "当前无负债月供，财务结构干净。",
                "suggestion": "",
            })

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
        dims.append({
            "key": "emergency",
            "title": "Emergency fund" if en else "应急金",
            "status": "good" if ok else "warn",
            "detail": detail_en if en else detail_zh,
            "suggestion": "" if ok else (
                "Top up the emergency fund with monthly surplus before other goals."
                if en
                else "每月结余优先补足应急金，再谈其它目标。"
            ),
        })

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
            dims.append({
                "key": "goals",
                "title": "Goal progress" if en else "目标进度",
                "status": "warn" if slow else "good",
                "detail": detail_en if en else detail_zh,
                "suggestion": "" if not slow else (
                    "Increase monthly saving or extend goal deadlines."
                    if en
                    else "提高每月储蓄或延后目标截止月。"
                ),
            })
        else:
            dims.append({
                "key": "goals",
                "title": "Goal progress" if en else "目标进度",
                "status": "good",
                "detail": "All goals achieved." if en else "全部目标已达成。",
                "suggestion": "",
            })

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

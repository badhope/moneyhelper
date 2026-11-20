"""确定性分析内核：持仓、现金流、负债、应急金、风控规则。

原则：数字只来自数据，规则永远比模型可靠。模型只负责把这里的结果"讲成人话"，
模板叙述则保证无模型时也能给出完整、可复核的回答。

本模块不碰网络（行情由 quotes 层负责），纯函数均可单测。
"""

from __future__ import annotations

import asyncio
from typing import Any

from cachetools import TTLCache

from . import db, quotes
from .calculations import decisions as _decisions

DISCLAIMER = "以上为基于你的组合与账本数据的洞察，不构成投资建议。"
DISCLAIMER_EN = "This is an insight based on your portfolio and ledger data, not investment advice."

# /api/dashboard 的短 TTL 缓存（M5.3）。
# 为什么需要：仪表盘被前端 4 个组件 + 对话 + MCP 同时拉，原来每次都要
# 读全表流水、算风控、打两次外部行情。10 秒内的重复请求应该复用同一份快照。
# 为什么不长：行情会变，用户改完持仓立刻刷新必须看到新数字。
_DASHBOARD_TTL_SECONDS = 10.0
_dashboard_cache: TTLCache[str, dict[str, Any]] = TTLCache(
    maxsize=64, ttl=_DASHBOARD_TTL_SECONDS
)


# --------------------------------------------------------------------------
# 市场视角
# --------------------------------------------------------------------------




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
                        else f"{b['name']} 占持仓 {b.get('investable_pct') or b['pct']}% 超过 {conc.get('threshold_pct')}% 单一持仓阈值"
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
                        else f"{b['industry']} 行业占持仓 {b.get('investable_pct') or b['pct']}% 超过 {conc.get('threshold_pct')}% 阈值"
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
        if hit is not None:
            return hit

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
    # 只取本月流水做账本视图：ledger_view 内部第一步就按 month 过滤，
    # 传全表等于把十万行搬进内存再丢掉 99%。明细用 LIMIT 单独取。
    # 账本视图只需要当月；但前端「流水明细」要能翻到历史月份，
    # 所以明细单独取最近 N 条（不是全表，也不是只有当月）。
    txs = await db.list_transactions_by_month(month)
    recent_txs = await db.list_transactions(limit=500)
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
        # 决策中心：把风险标记与目标进度收敛成可执行待办（纯函数，不新增估算口径）
        "actions": _build_actions(flags, goals, lang),
        "transactions": recent_txs,
        "transactions_total": total_tx,
        "source": {
            "portfolio": "Local portfolio (SQLite)" if en else "本地组合库（SQLite）",
            "ledger": "Local ledger (SQLite)" if en else "本地账本（SQLite）",
            "quotes": quotes_label,
            "seeded": settings.get("data_note", "") == "seed",
        },
    }
    # 每日净值快照：总览是用户每天必开的页面，在这里落一条快照最省事，
    # 也让「净值序列 / 变动归因 / TWR」有真实历史可用。
    # 失败绝不能影响总览——快照只是日志性质的历史记录。
    try:
        from . import networth_series

        # 现金 = kind 为「现金」的持仓市值；其余为非现金市值。
        # 口径与持仓页一致（现金不参与集中度但计入总资产）。
        cash_mv = sum(
            float(p.get("shares") or 0) * float(live.get(p["symbol"], p.get("last") or 0))
            for p in positions
            if p.get("kind") == "现金"
        )
        total_mv = float(m["total_market_value"])
        # 负债总额：负债明细里的未还本金（不是月供）
        total_liab = sum(float(d.get("balance") or 0) for d in debts)
        await networth_series.save_snapshot(
            total_assets=total_mv,
            total_liabilities=total_liab,
            cash=cash_mv,
            market_value=max(0.0, total_mv - cash_mv),
            source="eastmoney" if quotes.last_source() == "eastmoney" else "snapshot",
        )
    except Exception:  # noqa: BLE001 — 快照失败不影响总览
        pass

    if use_cache:
        _dashboard_cache[key] = out
    return out


def _build_actions(flags: list[dict[str, Any]], goals: list[dict[str, Any]],
                   lang: str) -> dict[str, Any]:
    """决策中心入口：只依赖已算好的 flags/goals，失败时返回空清单不阻断仪表盘。"""
    try:
        return _decisions.build_actions(flags=flags, goals=goals, lang=lang)
    except Exception:  # noqa: BLE001 — 待办清单失败不该让整个总览 500
        return {"items": [], "count": 0, "top": None}


def invalidate_dashboard_cache() -> None:
    """清空仪表盘缓存。任何写操作（记账/持仓/设置）后调用，保证下次读取是新数据。"""
    _dashboard_cache.clear()


# ---------------------------------------------------------------------------
# 财务目标 / 体检
# ---------------------------------------------------------------------------

from .analysis_health import (  # noqa: F401,E402 — 对外同名导出
    HEALTH_STATUS_EN,
    HEALTH_WORDS,
    goal_progress,
    health_check,
    health_report_text,
)
from .analysis_views import (  # noqa: F401,E402 — 对外同名导出
    CONCENTRATION_MAX_PCT,
    DTI_WARN_PCT,
    HIGH_RATE_DEBT,
    SAVINGS_RATE_WARN_PCT,
    _month_prefix,
    _num,
    ledger_view,
    market_view,
)


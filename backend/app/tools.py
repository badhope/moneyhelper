"""Agent 工具层：把确定性分析内核暴露成 LLM 可调用的工具（function calling）。

设计原则：
- 所有工具都是确定性计算（数字来自本地数据），模型只决定"调哪个工具、以什么参数调"，
  不负责产出数字 —— 延续「确定性内核优先」。
- 工具结果返回时截断为摘要级（关键数字 + 前几条明细），控制 token 与外发体量。
- 工具失败返回明确错误串，由 agent 循环决定是否重试/降级。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import httpx

from . import analysis, backup, db, nlparse, scheduler, tool_schemas
from .calculations import (
    backtest_text,
    estimate,
    fee_for,
    ranking,
    run_backtest,
    team_summary,
    technical_analysis,
    trend_text,
    validate_trade,
)
from .db._core import data_dir
from .logging_utils import get_logger
from .provenance import record_provenance
from .quotes import invalidate_quotes_cache, quote_now
from .quotes import kline as fetch_kline

_action_log = get_logger("tools.action")

Emit = Callable[[dict[str, Any]], Awaitable[None]]

# 备份包与数据库同目录（默认 backend/data，Docker 卷 moneyhelper-data），
# 容器重建不丢；路径本身不落库。
BACKUP_DIR = data_dir() / "backups"

# tool_set_setting 可写的键白名单：防止模型/动作带任意 key 往 settings 表写脏键。
# 值与枚举校验仍在各分支内完成；列表以外的 key 一律拒绝。
SETTING_KEYS_ALLOWED = frozenset({
    "monthly_income", "emergency_target_months", "essential_categories",
    "quote_source_mode", "report_time", "voice_input", "show_export",
    "expand_process", "show_suggestions", "auto_refresh", "auto_refresh_seconds",
    "compact_numbers", "color_scheme", "default_tab", "savings_goal",
    "report_focus", "lang",
    "ai_base_url", "ai_api_key", "ai_model",  # 这三个在下方被显式拒绝
})

# ---------------------------------------------------------------------------
# 工具执行体（纯函数，可单测）
# ---------------------------------------------------------------------------


def _compact_market(market: dict[str, Any]) -> dict[str, Any]:
    """market_view 结果压成给模型的摘要：总额 + 前 5 持仓 + 集中度告警。"""
    return {
        "total_market_value": market["total_market_value"],
        "total_cost": market["total_cost"],
        "total_pnl": market["total_pnl"],
        "total_pnl_pct": market["total_pnl_pct"],
        "top_positions": [
            {
                "name": p["name"],
                "symbol": p["symbol"],
                "market_value": p["market_value"],
                "pnl": p["pnl"],
                "pnl_pct": p["pnl_pct"],
            }
            for p in market["positions"][:5]
        ],
        "concentration_warnings": [
            a["name"] for a in market["concentration"]["asset_breaches"]
        ],
    }


def _compact_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    return {
        "month": ledger["month"],
        "income": ledger["income"],
        "expense": ledger["expense"],
        "net": ledger["net"],
        "savings_rate": ledger["savings_rate"],
        "top_categories": ledger["by_category"][:5],
        "subscription_monthly": ledger["subscription_monthly"],
        "debt_monthly": ledger["debt_monthly"],
        "dti_pct": ledger["dti_pct"],
        "emergency": ledger["emergency"],
    }


async def tool_get_market_view(_args: dict[str, Any]) -> str:
    """查持仓与行情：总市值、盈亏、集中度。无参数。"""
    positions = await db.list_positions()
    from .quotes import live_quotes

    live = await live_quotes(positions)
    if not positions:
        return json.dumps(
            {"empty": True, "hint": "还没有持仓，提示用户去添加持仓后再问"}, ensure_ascii=False
        )
    return json.dumps(_compact_market(analysis.market_view(positions, live)), ensure_ascii=False)


async def tool_get_ledger_view(_args: dict[str, Any]) -> str:
    """查账本：本月收支、结余、储蓄率、订阅、负债、应急金。无参数。"""
    settings = await db.get_settings()
    positions = await db.list_positions()
    from .quotes import live_quotes

    live = await live_quotes(positions)
    txs = await db.list_transactions()
    if not txs:
        return json.dumps(
            {"empty": True, "hint": "还没有流水，提示用户先记账再问"}, ensure_ascii=False
        )
    led = analysis.ledger_view(
        txs,
        await db.list_subscriptions(),
        await db.list_debts(),
        settings,
        positions,
        live,
    )
    return json.dumps(_compact_ledger(led), ensure_ascii=False)


async def tool_get_risk_flags(_args: dict[str, Any]) -> str:
    """查风控规则：集中度、应急金、高息负债、负债收入比、储蓄率告警。无参数。"""
    positions = await db.list_positions()
    from .quotes import live_quotes

    live = await live_quotes(positions)
    settings = await db.get_settings()
    m = analysis.market_view(positions, live)
    led = analysis.ledger_view(
        await db.list_transactions(),
        await db.list_subscriptions(),
        await db.list_debts(),
        settings,
        positions,
        live,
    )
    flags = analysis.risk_checks(m, led)
    return json.dumps(
        {"count": len(flags), "flags": [f["text"] for f in flags]},
        ensure_ascii=False,
    )


async def tool_get_budget(args: dict[str, Any]) -> str:
    """查预算：某月预算设置与实时使用率。参数：month（YYYY-MM，可省略=本月）。"""
    month = str(args.get("month") or "").strip() or datetime.now().strftime("%Y-%m")
    rows = await db.list_budgets(month)
    budgets = {
        ("总预算" if r["category"] == "__total" else r["category"]): r["amount"]
        for r in rows
    }
    spent = await db.month_expense_by_category(month)
    # 与 /api/budgets 同口径：投资/还款是储蓄与转移支付，不计入预算使用
    for cat in ("投资", "还款"):
        spent.pop(cat, None)
    total_spent = round(sum(spent.values()), 2)
    total_budget = budgets.get("总预算", 0.0)
    return json.dumps(
        {
            "month": month,
            "budgets": budgets,
            "spent_by_category": spent,
            "total_spent": total_spent,
            "total_budget": total_budget,
            "over": total_budget > 0 and total_spent > total_budget,
        },
        ensure_ascii=False,
    )


async def tool_get_trend(args: dict[str, Any]) -> str:
    """查收支趋势：最近 N 个月（默认 6）收入/支出/结余。参数：months（1-24）。"""
    try:
        months = max(1, min(int(args.get("months") or 6), 24))
    except (TypeError, ValueError):
        months = 6
    return json.dumps(await db.monthly_trend(months), ensure_ascii=False)


async def tool_record_transaction(args: dict[str, Any]) -> str:
    """一句话记账：把用户说的话解析为流水并入账。参数：text（一句话，含金额）。"""
    text = str(args.get("text") or "").strip()
    if not text:
        return "缺少 text 参数"
    parsed = nlparse.parse(text)
    if parsed is None:
        parsed = await nlparse.parse_with_ai(text)
    if parsed is None:
        return "无法从这句话里解析出金额，请让用户改说「昨天打车 32 元」这类格式"
    await db.add_transaction(
        parsed["date"], parsed["item"], parsed["category"], parsed["amount"]
    )
    # 异步审计
    await record_provenance(
        action="add_transaction",
        entity_type="transaction",
        entity_id=f"{parsed['date']}:{parsed['item']}:{parsed['amount']}",
        before=None,
        after=parsed,
        source="mcp",
    )
    return json.dumps(
        {
            "ok": True,
            "date": parsed["date"],
            "item": parsed["item"],
            "category": parsed["category"],
            "amount": parsed["amount"],
        },
        ensure_ascii=False,
    )


async def tool_get_kline(args: dict[str, Any]) -> str:
    """查某标的的 K 线走势。参数：symbol（6 位代码），period（daily/weekly/monthly，默认 daily），limit（默认 60）。"""
    symbol = str(args.get("symbol") or "").strip()
    if not symbol:
        return "缺少 symbol 参数"
    period = str(args.get("period") or "daily").strip()
    try:
        limit = max(10, min(int(args.get("limit") or 60), 500))
    except (TypeError, ValueError):
        limit = 60
    data = await fetch_kline(symbol, period, limit)
    if not data:
        return f"无法获取 {symbol} 的行情（可能不是 A 股/ETF 代码，或行情源不可用）"
    # 只回传近 N 个收盘价点，控制 token
    points = [
        {"date": p["date"], "close": p["close"], "pct_change": p.get("pct_change")}
        for p in data["points"][-30:]
    ]
    return json.dumps(
        {"symbol": symbol, "period": period, "source": data["source"], "points": points},
        ensure_ascii=False,
    )


async def tool_research_analyze(args: dict[str, Any]) -> str:
    """技术面研报：MA/MACD/RSI/BOLL/KDJ 指标快照 + 信号 + 多空倾向 + 文字结论。

    参数：symbol（6 位代码），period（daily/weekly/monthly），limit（取数根数，默认 180）。
    """
    symbol = str(args.get("symbol") or "").strip()
    if not symbol:
        return "缺少 symbol 参数"
    period = str(args.get("period") or "daily").strip()
    try:
        limit = max(60, min(int(args.get("limit") or 180), 500))
    except (TypeError, ValueError):
        limit = 180
    data = await fetch_kline(symbol, period, limit)
    if not data:
        return f"无法获取 {symbol} 的行情（可能不是 A 股/ETF 代码，或行情源不可用）"
    ta = technical_analysis(data["points"])
    if ta is None:
        return f"{symbol} 历史数据不足 20 根，无法给出技术分析"
    return json.dumps(
        {
            "symbol": symbol,
            "period": period,
            "point_count": ta["point_count"],
            "last": ta["last"],
            "bias": ta["bias"],
            "signals": ta["signals"][-8:],
            "conclusion": trend_text(ta, "zh"),
            "disclaimer": "技术面分析仅基于历史行情统计，不构成投资建议。",
        },
        ensure_ascii=False,
    )


async def tool_research_backtest(args: dict[str, Any]) -> str:
    """策略回测：双均线（ma_cross）或定投（dca），输出收益/回撤/夏普/胜率/资金曲线要点。

    参数：symbol（6 位代码），strategy（ma_cross/dca），fast/slow（均线周期）、
    invest_amount/freq_days（定投金额与间隔）。
    """
    symbol = str(args.get("symbol") or "").strip()
    if not symbol:
        return "缺少 symbol 参数"
    strategy = str(args.get("strategy") or "ma_cross").strip()
    if strategy not in ("ma_cross", "dca"):
        return "strategy 仅支持 ma_cross / dca"
    try:
        fast = max(2, min(int(args.get("fast") or 5), 60))
        slow = max(5, min(int(args.get("slow") or 20), 120))
        invest_amount = max(1.0, float(args.get("invest_amount") or 1000.0))
        freq_days = max(1, min(int(args.get("freq_days") or 5), 60))
    except (TypeError, ValueError):
        return "回测参数非法"
    data = await fetch_kline(symbol, "daily", 750)
    if not data:
        return f"无法获取 {symbol} 的行情（可能不是 A 股/ETF 代码，或行情源不可用）"
    points = data["points"]
    closes = [float(p["close"]) for p in points if p.get("close") is not None]
    dates = [p.get("date", "") for p in points]
    if len(closes) < 60:
        return f"{symbol} 历史数据不足 60 根，无法回测"
    result = (
        run_backtest(closes, dates, "ma_cross", fast=fast, slow=slow)
        if strategy == "ma_cross"
        else run_backtest(closes, dates, "dca", invest_amount=invest_amount, freq_days=freq_days)
    )
    if result is None:
        return f"{symbol} 历史数据不足，无法回测"
    return json.dumps(
        {
            "symbol": symbol,
            "strategy": strategy,
            "result": {
                k: v
                for k, v in result.items()
                if k not in ("curve", "trades")  # 资金曲线太大，不进模型上下文
            },
            "conclusion": backtest_text(result, "zh"),
            "disclaimer": "回测结果仅基于历史行情统计，不代表未来收益，不构成投资建议。",
        },
        ensure_ascii=False,
    )


async def tool_statements_analyze(args: dict[str, Any]) -> str:
    """财报分析：输入标准化三表 JSON，输出 20+ 财务指标、杜邦拆解、异常预警与文字报告。

    参数：payload = {company, currency, periods:[{period, balance_sheet, income_statement,
    cashflow_statement}]}。字段缺失的指标会标注「数据不足」，不会编造数值。
    """
    payload = args.get("payload")
    if not isinstance(payload, dict):
        return "payload 必须是 JSON 对象"
    from .calculations import analyze_statements

    result = analyze_statements(payload)
    if result is None:
        return "财报数据无效：需要 periods 数组，且至少一期包含 balance_sheet / income_statement / cashflow_statement"
    return json.dumps(
        {
            "company": result["company"],
            "period_count": result["period_count"],
            "latest": result["latest"],
            "trends": {k: v for k, v in result["trends"].items() if k != "periods"},
            "dupont": result["dupont"],
            "alerts": result["alerts"],
            "report": result["report_text"],
            "disclaimer": "本报告为报表口径还原与规则引擎输出，不构成投资建议。",
        },
        ensure_ascii=False,
    )


async def tool_research_forecast(args: dict[str, Any]) -> str:
    """统计预测：对某只 A 股/ETF 输出未来 N 期线性趋势、波动率与蒙特卡洛分位区间。

    参数：symbol（6 位代码），period（daily/weekly/monthly），days（预测根数 1-60）。
    输出为历史统计情景推演（固定随机种子可复现），不构成投资建议。
    """
    symbol = str(args.get("symbol") or "").strip()
    if not symbol:
        return "缺少 symbol 参数"
    period = str(args.get("period") or "daily").strip()
    if period not in ("daily", "weekly", "monthly"):
        return "period 仅支持 daily / weekly / monthly"
    try:
        days = max(1, min(int(args.get("days") or 20), 60))
    except (TypeError, ValueError):
        days = 20
    data = await fetch_kline(symbol, period, 750)
    if not data:
        return f"无法获取 {symbol} 的行情（可能不是 A 股/ETF 代码，或行情源不可用）"
    closes = [float(p["close"]) for p in data["points"] if p.get("close") is not None]
    dates = [p.get("date", "") for p in data["points"]]
    if len(closes) < 30:
        return f"{symbol} 历史数据不足 30 根，无法给出统计预测"
    from .calculations import forecast, forecast_text

    result = forecast(closes, dates=dates, horizon=days)
    if result is None:
        return f"{symbol} 历史数据不足，无法给出统计预测"
    return json.dumps(
        {
            "symbol": symbol,
            "period": period,
            "horizon": result["horizon"],
            "last_close": result["last_close"],
            "bias": result["bias"],
            "slope_pct": result["slope_pct"],
            "vol_annual_pct": result["vol_annual_pct"],
            "mean_reversion_pct": result["mean_reversion_pct"],
            "band": {
                "median": result["median"][-days:],
                "p5": result["p5"][-days:],
                "p95": result["p95"][-days:],
            },
            "conclusion": forecast_text(result, "zh"),
            "disclaimer": "预测为统计情景推演，不构成投资建议。",
        },
        ensure_ascii=False,
    )


async def tool_paper_open(args: dict[str, Any]) -> str:
    """团队模拟盘开户：为成员创建虚拟账户（独立初始资金）。"""
    try:
        acc = await db.open_account(
            str(args.get("name") or "模拟账户"),
            float(args.get("initial_cash") or 100000),
        )
    except ValueError as e:
        return f"开户失败：{e}"
    return json.dumps(
        {
            "ok": True,
            "account_id": acc["account_id"],
            "name": acc["name"],
            "initial_cash": acc["initial_cash"],
            "hint": "用 paper_trade 开始交易（买入需 100 股整手）",
        },
        ensure_ascii=False,
    )


async def tool_paper_trade(args: dict[str, Any]) -> str:
    """团队模拟盘下单：买入/卖出，自动扣费、更新净值与排行。"""
    account_id = str(args.get("account_id") or "").strip()
    if not account_id:
        return "缺少 account_id 参数"
    acc = await db.get_account(account_id)
    if not acc:
        return f"账户 {account_id} 不存在（可用 paper_overview 查看账户列表）"
    symbol = str(args.get("symbol") or "").strip().upper()
    if not symbol.isdigit() or len(symbol) != 6:
        return "symbol 必须是 6 位 A 股代码"
    side = str(args.get("side") or "").strip()
    try:
        price = float(args.get("price") or 0)
        shares = float(args.get("shares") or 0)
    except (TypeError, ValueError):
        return "price/shares 非法"
    trades = await db.get_trades(account_id)
    err = validate_trade(acc["initial_cash"], trades, side, symbol, price, shares)
    if err:
        return f"下单被拒：{err}"
    amount = price * shares
    fee = fee_for(side, amount)
    await db.add_trade(
        account_id,
        {"symbol": symbol, "name": "", "side": side, "price": price, "shares": shares, "fee": fee},
    )
    est = estimate(acc["initial_cash"], await db.get_trades(account_id))
    await db.save_snapshot(account_id, est["equity"], est["cash"], est["market_value"])
    return json.dumps(
        {
            "ok": True,
            "account_id": account_id,
            "symbol": symbol,
            "side": side,
            "price": price,
            "shares": shares,
            "fee": fee,
            "equity": est["equity"],
            "cash": est["cash"],
            "return_pct": est["return_pct"],
            "holdings": est["holdings"][:8],
            "disclaimer": "模拟盘数据不构成投资建议。",
        },
        ensure_ascii=False,
    )


async def tool_paper_overview(_args: dict[str, Any]) -> str:
    """团队模拟盘总览：账户排行（收益率）、团队汇总、各账户持仓摘要。"""
    accounts = await db.list_accounts()
    if not accounts:
        return json.dumps(
            {"empty": True, "hint": "还没有模拟账户，可用 paper_open 开户"},
            ensure_ascii=False,
        )
    enriched = []
    for acc in accounts:
        trades = await db.get_trades(acc["account_id"])
        est = estimate(acc["initial_cash"], trades)
        enriched.append(
            {
                "account_id": acc["account_id"],
                "name": acc["name"],
                "initial_cash": acc["initial_cash"],
                "trade_count": len(trades),
                "equity": est["equity"],
                "return_pct": est["return_pct"],
                "total_pnl": est["total_pnl"],
                "position_count": est["position_count"],
                "top_holdings": [h["symbol"] for h in est["holdings"][:3]],
            }
        )
    ranked = ranking(enriched)
    return json.dumps(
        {
            "ranking": ranked,
            "summary": team_summary(ranked),
            "valuation_source": "last_trade",
            "disclaimer": "模拟盘数据不构成投资建议。",
        },
        ensure_ascii=False,
    )


async def tool_get_goals(_args: dict[str, Any]) -> str:
    """查财务目标：目标金额、已存金额、进度、距截止月、建议月存。无参数。"""
    goals = await db.list_goals()
    if not goals:
        return json.dumps(
            {"empty": True, "hint": "用户还没有设置财务目标，可提示用户到「记账 → 目标」添加"}, ensure_ascii=False
        )
    return json.dumps(analysis.goal_progress(goals), ensure_ascii=False)


async def tool_get_user_memory(args: dict[str, Any]) -> str:
    """查用户长期记忆：用户主动告知的长期信息（偏好、家庭、计划等）。
    可选 kind 过滤（fact / preference / goal_related）；可选 query 做 BM25 关键词检索
    （无 embedding Key 的确定性语义检索降级）；每次读取刷新 last_used（主动遗忘依据）。"""
    rows = await db.list_memory()
    kind = str((args or {}).get("kind") or "").strip()
    query = str((args or {}).get("query") or "").strip()
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    if query:
        rows = db.memory_retrieve(query, rows, top_k=5)
    if not rows:
        return json.dumps({"empty": True, "hint": "暂无长期记忆"}, ensure_ascii=False)
    # 刷新被使用的记忆时间戳（主动遗忘：久未使用的记忆才建议清理）
    try:
        for r in rows:
            await db.touch_memory(r["id"])
    except Exception:  # noqa: BLE001 — 时间戳刷新失败不影响返回
        pass
    return json.dumps(
        [{"content": r["content"], "kind": r["kind"]} for r in rows],
        ensure_ascii=False,
    )


async def tool_get_lessons(_args: dict[str, Any]) -> str:
    """查经验库：之前工具调用的踩坑记录（供反思复用，避免重复犯错）。无参数。"""
    rows = await db.list_reflections(limit=10)
    if not rows:
        return json.dumps({"empty": True, "hint": "暂无踩坑经验"}, ensure_ascii=False)
    return json.dumps(
        [{"tool": r["tool"], "lesson": r["lesson"], "created_at": r["created_at"]} for r in rows],
        ensure_ascii=False,
    )


async def tool_save_user_memory(args: dict[str, Any]) -> str:
    """记住一条用户长期信息（如「明年计划买房」「每月收入 2 万」）。参数：content（要记住的内容）。"""
    content = str(args.get("content") or "").strip()
    if not content:
        return "缺少 content 参数"
    out = await db.add_memory(content)
    return json.dumps({"ok": True, "deduped": out.get("deduped", False)}, ensure_ascii=False)


async def tool_get_health_check(_args: dict[str, Any]) -> str:
    """跑一次结构化财务体检：资产配置 / 现金流 / 负债 / 应急金 / 目标进度 五维评分与建议。无参数。"""
    positions = await db.list_positions()
    from .quotes import live_quotes

    live = await live_quotes(positions)
    settings = await db.get_settings()
    m = analysis.market_view(positions, live)
    led = analysis.ledger_view(
        await db.list_transactions(),
        await db.list_subscriptions(),
        await db.list_debts(),
        settings,
        positions,
        live,
    )
    flags = analysis.risk_checks(m, led)
    report = analysis.health_check(m, led, flags, await db.list_goals())
    return json.dumps(report, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 投资策略工具：把确定性引擎的结果交给模型叙述。
# 模型永远不自己算风险指标——它只解读这里返回的数字。
# ---------------------------------------------------------------------------

_BENCHMARK_NAMES = {"sh000300": "沪深300", "sh000001": "上证指数", "sz399001": "深证成指", "sz399006": "创业板指"}


async def tool_get_portfolio_risk(args: dict[str, Any]) -> str:
    """组合风险指标：波动率/夏普/索提诺/最大回撤/Beta/Alpha/与基准对比。"""
    from .calculations import build_equity_curve, compute_risk_metrics
    from .quotes import index_kline, kline

    bench = str(args.get("benchmark") or "sh000300").strip() or "sh000300"
    if bench not in _BENCHMARK_NAMES:
        return f"不支持的基准 {bench}，可选：{'、'.join(_BENCHMARK_NAMES)}"
    positions = await db.list_positions()
    holdings = []
    cash = 0.0
    for p in positions:
        if str(p.get("kind") or "") == "现金":
            cash += float(p.get("shares", 0) or 0) * float(p.get("last", 0) or 0)
        else:
            holdings.append(
                {"symbol": str(p.get("symbol") or ""), "shares": float(p.get("shares", 0) or 0)}
            )
    if not holdings:
        return "当前没有非现金持仓，无法计算组合风险。"
    history: dict[str, list[dict[str, Any]]] = {}
    for h in holdings:
        k = await kline(h["symbol"], "daily", 750)
        if k and k.get("points"):
            history[h["symbol"]] = k["points"]
    curve = build_equity_curve(holdings, history, cash)
    if len(curve) < 20:
        return "行情历史不足（至少需要 20 个交易日），暂时算不出可靠的风险指标。"
    bi = await index_kline(bench, 750)
    bench_values = None
    if bi and bi.get("points"):
        bench_values = [float(p["close"]) for p in bi["points"] if p.get("close")]
        if len(bench_values) > len(curve):
            bench_values = bench_values[-len(curve) :]
    m = compute_risk_metrics(curve, bench_values)
    d = m.to_dict()
    d["benchmark_name"] = _BENCHMARK_NAMES.get(bench, bench)
    d["basis"] = "按当前持仓回溯的模拟净值，不是实盘历史成交净值"
    return json.dumps(d, ensure_ascii=False)


async def tool_get_rebalance_plan(args: dict[str, Any]) -> str:
    """再平衡：目标配置偏离度 + 建议买入/卖出金额与股数。"""
    from .calculations import compute_rebalance

    try:
        band = float(args.get("band_pct") or 5.0)
    except (TypeError, ValueError):
        band = 5.0
    positions = await db.list_positions()
    targets = await db.list_allocation_targets()
    if not targets:
        return (
            "还没有设置目标配置，无法给出再平衡建议。"
            "请先在「持仓 → 目标配置」里设置各标的的目标权重（合计 100%）。"
        )
    plan = compute_rebalance(positions, targets, band)
    return json.dumps(plan.to_dict(), ensure_ascii=False)


async def tool_get_valuation(args: dict[str, Any]) -> str:
    """估值位置分位：当前价在近期区间中的位置（0=最低，100=最高）。"""
    from .calculations import compute_valuation
    from .quotes import kline

    raw = str(args.get("symbols") or "").strip()
    wanted = [s.strip() for s in raw.split(",") if s.strip()]
    positions = await db.list_positions()
    chosen = []
    for p in positions:
        sym = str(p.get("symbol") or "")
        if not sym or str(p.get("kind") or "") == "现金":
            continue
        if wanted and sym not in wanted:
            continue
        chosen.append(p)
    if not chosen:
        return "没有可评估的持仓（目标标的为空或不在持仓中）。"
    out = []
    for p in chosen:
        k = await kline(str(p.get("symbol")), "daily", 750)
        if not k:
            continue
        closes = [float(pt["close"]) for pt in (k.get("points") or []) if pt.get("close")]
        v = compute_valuation(str(p.get("symbol")), str(p.get("name") or ""), closes, 750)
        if v:
            out.append(v.to_dict())
    if not out:
        return "行情不可用，暂时算不出估值分位。"
    out.sort(key=lambda x: x["percentile"])
    return json.dumps(
        {
            "items": out,
            "note": "位置分位 = 当前价在近 750 个交易日区间中的位置；只描述贵不贵，不预测涨跌",
        },
        ensure_ascii=False,
    )


async def tool_get_dca_plans(_args: dict[str, Any]) -> str:
    """定投计划：每期金额、累计投入、成本线、当前盈亏、下一期日期。"""
    from .calculations import compute_dca_stats, next_run_date
    from .quotes import kline, quote_now

    plans = await db.list_dca_plans()
    if not plans:
        return "还没有定投计划。可以说「每月 10 号定投 3000 沪深300」来创建。"
    out = []
    for plan in plans:
        sym = str(plan.get("symbol") or "")
        k = await kline(sym, "daily", 750)
        closes = [
            {"date": p.get("date"), "close": p.get("close")}
            for p in ((k or {}).get("points") or [])
            if p.get("close")
        ]
        px = None
        if not closes:
            q = await quote_now(sym)
            px = (q or {}).get("price")
        stats = compute_dca_stats(plan, closes, float(px) if px else None)
        try:
            nxt = next_run_date(int(plan.get("day", 1) or 1), str(plan.get("frequency") or "monthly"))
            nxt_s = nxt.isoformat()
        except (ValueError, TypeError):
            nxt_s = None
        out.append({**plan, "stats": stats, "next_run": nxt_s})
    return json.dumps({"items": out}, ensure_ascii=False)


async def tool_get_fire_plan(_args: dict[str, Any]) -> str:
    """FIRE 进度：目标本金、储蓄率、预计达成年限。"""
    from datetime import date as _date

    from .calculations import compute_fire

    txns = await db.list_transactions()
    month_prefix = _date.today().strftime("%Y-%m")
    monthly = [t for t in txns if str(t.get("date", "")).startswith(month_prefix)]
    income = sum(float(t.get("amount", 0)) for t in monthly if float(t.get("amount", 0)) > 0)
    expense = -sum(float(t.get("amount", 0)) for t in monthly if float(t.get("amount", 0)) < 0)
    positions = await db.list_positions()
    debts = await db.list_debts()
    net = sum(float(p.get("shares", 0) or 0) * float(p.get("last", 0) or 0) for p in positions) - sum(
        float(d.get("balance", 0) or 0) for d in debts
    )
    if income <= 0 and expense <= 0:
        return "账本里还没有本月收支记录，无法估算 FIRE 进度。"
    sr = None if income <= 0 else (income - expense) / income * 100
    return json.dumps(compute_fire(expense, income, sr, net), ensure_ascii=False)


# ---------------------------------------------------------------------------
# 行情 / 自选 / 持仓工具：让「一句话工作流」成立——
# 搜标的 → 看行情 → 加入自选 → 看 K 线/风险 → 记录买入，全程由模型编排。
# ---------------------------------------------------------------------------

_SEARCH_URL = "https://searchapi.eastmoney.com/api/suggest/get"
_SEARCH_HEADERS = {"User-Agent": "Mozilla/5.0 (moneyhelper)", "Referer": "https://quote.eastmoney.com/"}


async def tool_search_symbol(args: dict[str, Any]) -> str:
    """搜 A股/基金/指数（东财 suggest）；网络失败返回明确提示。"""
    kw = str(args.get("query") or "").strip()
    if not kw:
        return "需要提供搜索关键词，例如「茅台」「600519」"
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(
                _SEARCH_URL,
                params={"input": kw, "type": "14", "token": os.getenv("EASTMONEY_SEARCH_TOKEN", "D43BF722C8E33BDC906FB84D85E326E8")},
                headers=_SEARCH_HEADERS,
            )
            resp.raise_for_status()
            data = (resp.json() or {}).get("data") or {}
        rows = ((data.get("QuotationCodeTable") or {}).get("Data") or [])[:8]
    except Exception:  # noqa: BLE001 — 搜索失败给可读提示
        return "搜索服务暂时不可用（网络或行情源问题），请稍后再试"
    lines = []
    for r in rows:
        code = str(r.get("Code") or "").strip()
        name = str(r.get("Name") or "").strip()
        if not code or not name:
            continue
        stype = str(r.get("SecurityTypeName") or "")
        kind = "基金" if "基金" in stype else ("指数" if "指" in stype else "股票")
        lines.append(f"{name}（{code}，{kind}）")
    if not lines:
        return f"没有找到「{kw}」，试试完整代码或名称"
    return "搜索结果：\n" + "\n".join(lines)


async def tool_get_quote(args: dict[str, Any]) -> str:
    """单只标的实时行情（东财优先、新浪备源）。"""
    symbol = str(args.get("symbol") or "").strip().upper()
    if not symbol:
        return "需要提供代码，例如 600519"
    q = await quote_now(symbol)
    if q is None:
        return f"无法获取 {symbol} 的行情（可能不是 A股/ETF，或网络不可用）"
    name = q.get("name") or symbol
    pct = q.get("change_pct")
    pct_txt = f"{pct:+.2f}%" if pct is not None else "—"
    src = {"eastmoney": "东财", "sina": "新浪"}.get(q.get("source"), q.get("source", ""))
    return f"{name}（{symbol}）现价 {q['price']}，涨跌 {pct_txt}（来源：{src}）"


async def tool_add_watchlist(args: dict[str, Any]) -> str:
    """把标的加入自选（无名称时自动取实时名称）。"""
    symbol = str(args.get("symbol") or "").strip().upper()
    if not symbol:
        return "需要提供代码，例如 600519"
    name = str(args.get("name") or "").strip()
    if not name:
        q = await quote_now(symbol)
        name = (q or {}).get("name") or symbol
    try:
        await db.add_watchlist(symbol, name, str(args.get("kind") or "股票"))
    except Exception as exc:  # noqa: BLE001
        return f"添加自选失败：{exc}"
    return f"已把 {name}（{symbol}）加入自选。可以继续问它的行情、K 线或风险。"


async def tool_remove_watchlist(args: dict[str, Any]) -> str:
    symbol = str(args.get("symbol") or "").strip().upper()
    if not symbol:
        return "需要提供代码"
    await db.delete_watchlist(symbol)
    return f"已把 {symbol} 移出自选"


# 进程内持仓写锁：防止 tool_sell_position / tool_append_position 的 read-then-write 竞态
_position_write_lock = asyncio.Lock()


async def tool_sell_position(args: dict[str, Any]) -> str:
    """卖出/减仓持仓：给出代码与数量（可省略数量=全部清仓）。"""
    symbol = str(args.get("symbol") or "").strip().upper()
    if not symbol:
        return "需要提供代码，例如 600519"
    async with _position_write_lock:
        positions = await db.list_positions()
        cur = next((p for p in positions if p["symbol"] == symbol), None)
        if cur is None:
            return f"持仓里没有 {symbol}，无需卖出。当前持仓：{', '.join(p['symbol'] for p in positions) or '（空）'}"
        try:
            shares = float(args.get("shares") or 0)
        except (TypeError, ValueError):
            shares = 0
        before = dict(cur)
        if shares <= 0 or shares >= cur["shares"]:
            await db.delete_position(symbol)
            await record_provenance(
                action="sell_position",
                entity_type="position",
                entity_id=symbol,
                before=before,
                after=None,
                source="mcp",
                    )
            return f"已清仓卖出 {cur['name']}（{symbol}）：{cur['shares']:g} 份全部平仓，持仓已移除。"
        new_shares = cur["shares"] - shares
        after = {**cur, "shares": new_shares}
        await db.add_position(
            {
                "symbol": cur["symbol"],
                "name": cur["name"],
                "kind": cur["kind"],
                "industry": cur["industry"],
                "shares": new_shares,
                "cost": cur["cost"],
                "last": cur["last"],
                "buy_date": cur.get("buy_date"),
                "fee": cur.get("fee", 0),
            }
        )
        await record_provenance(
            action="sell_position",
            entity_type="position",
            entity_id=symbol,
            before=before,
            after=after,
            source="mcp",
            )
        return (
            f"已卖出 {cur['name']}（{symbol}）{shares:g} 份，剩余 {new_shares:g} 份（成本 {cur['cost']:g} 不变）。"
            "可在持仓页查看最新盈亏。"
        )


async def tool_trigger_morning_report(_args: dict[str, Any], lang: str = "zh") -> str:
    """触发生成今日晨报（组合+账本+目标体检，空库会提示没有数据）。"""
    try:
        result = await scheduler.generate_report()
    except Exception as exc:  # noqa: BLE001 — 手动触发失败要给可读错误
        if lang != "zh":
            return f"Morning report generation failed: {type(exc).__name__}: {exc}"
        return f"晨报生成失败：{type(exc).__name__}: {exc}"
    if result.get("skipped"):
        if lang != "zh":
            return (
                "Not enough data yet for a morning report (need at least one holding or transaction). "
                "Record an entry or add a holding, and I'll run your check-up."
            )
        return "还没有足够的数据生成晨报（需要至少一条持仓或流水）。先记一笔账或添加持仓，我再来帮你体检。"
    if lang != "zh":
        return result.get("answer", "Morning report generated.") + "\n(archived to Ask AI → Morning report history)"
    return result.get("answer", "晨报已生成。") + "\n（已归档到「问AI」→ 晨报历史）"


async def tool_backup_now(_args: dict[str, Any], lang: str = "zh") -> dict[str, str]:
    """生成一份本地加密备份包（PBKDF2+Fernet）。

    返回 {"answer":..., "passphrase":...}：answer 不含明文口令（防 SSE 帧截获）；
    passphrase 单独返回，仅由前端从 final 事件取出单独展示（口令绝不写入问答历史/日志）。
    """
    data = await db.export_data()
    passphrase = secrets.token_urlsafe(16)  # ~128 bit 熵，匹配 PBKDF2 600k 迭代离线防护
    payload = backup.encrypt_export(data, passphrase)
    import datetime as _dt

    path = BACKUP_DIR / f"moneyhelper-backup-{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    if lang != "zh":
        answer = (
            f"Local encrypted backup created: {path.name}\n"
            "Restoring: Settings → Data & state → Restore backup.\n"
            "The decryption passphrase will be shown separately — please save it now."
        )
    else:
        answer = (
            f"已生成本地加密备份：{path.name}\n"
            "恢复方法：设置 → 数据与状态 → 恢复备份。\n"
            "解密口令将单独展示——请现在妥善保存。"
        )
    return {"answer": answer, "passphrase": passphrase}


async def tool_set_setting(args: dict[str, Any], lang: str = "zh") -> str:
    """修改应用设置（涨跌颜色/默认首页/语言/数字格式/快捷建议/晨报时间）。"""
    en = lang != "zh"
    key = str(args.get("key") or "").strip()
    value = args.get("value")
    if not key or value is None:
        if en:
            return "Please provide a key and a value, e.g. set default home to Holdings, or set the color scheme to green-up."
        return "需要提供 key 与 value，例如：改默认首页为持仓页、涨跌颜色改成绿涨红跌"
    raw = str(value)
    if len(raw) > 2000:
        return "Value too long (max 2000 characters)" if en else "设置值过长（最多 2000 字符）"
    if key not in SETTING_KEYS_ALLOWED:
        return (f"Unsupported config key: {key}" if en else f"不支持修改配置项：{key}（仅支持设置页存在的配置）")
    # AI 接入配置含密钥/端点，只允许在设置页（/api/settings）修改，工具层一律拒绝，
    # 防止把模型调用重定向到攻击者端点造成数据外带。
    if key in ("ai_base_url", "ai_api_key", "ai_model"):
        return (f"{key} is AI-connection config — edit it in Settings → AI answers" if en else f"{key} 属于 AI 接入配置，请到「设置 → AI 回答」中修改")
    if key == "color_scheme" and raw not in ("cn", "us"):
        return "color_scheme must be cn (red-up/green-down) or us (green-up/red-down)" if en else "涨跌颜色只能是 cn（红涨绿跌）或 us（绿涨红跌）"
    if key == "default_tab" and raw not in ("overview", "holdings", "market", "ledger", "chat", "features"):
        return "default_tab must be overview/holdings/market/ledger/chat/features" if en else "默认首页只能是 总览/持仓/行情/记账/问AI/功能"
    if key == "lang" and raw not in ("zh", "en"):
        return "lang must be zh or en" if en else "语言只能是 zh 或 en"
    if key in ("compact_numbers", "show_suggestions") and raw not in ("on", "off"):
        return f"{key} must be on or off" if en else f"{key} 只能是 on 或 off"
    if key in ("morning_report_time", "report_time"):
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", raw):
            return "Morning report time must be HH:MM (24-hour)" if en else "晨报时间需为 HH:MM（24 小时制）"
        key = "report_time"  # 模型常用 morning_report_time 说法，统一落到真实键名
    try:
        await db.set_setting(key, raw)
    except Exception as exc:  # noqa: BLE001
        return f"Setting failed: {exc}" if en else f"设置失败：{exc}"
    await invalidate_quotes_cache()
    if key == "report_time":
        try:
            await scheduler.notify_settings_changed()
        except Exception:  # noqa: BLE001 — 重排失败不影响设置已保存
            pass
    if en:
        return f"Updated setting: {key} = {raw} (changes that need a restart were applied immediately)."
    return f"已更新设置：{key} = {raw}（下次启动生效的部分已即时应用）。"


async def tool_get_watchlist(_args: dict[str, Any]) -> str:
    items = await db.list_watchlist()
    if not items:
        return "自选列表是空的。可以让我帮你搜索并添加，例如「帮我看看茅台并加入自选」"
    lines = []
    for i in items:
        q = await quote_now(i["symbol"])
        if q:
            pct = q.get("change_pct")
            pct_txt = f"{pct:+.2f}%" if pct is not None else "—"
            lines.append(f"{i['name']}（{i['symbol']}）现价 {q['price']} {pct_txt}")
        else:
            lines.append(f"{i['name']}（{i['symbol']}）行情暂不可用")
    return "你的自选：\n" + "\n".join(lines)


async def tool_record_position(args: dict[str, Any]) -> str:
    """记录一笔买入持仓（份额/成本/现价必填；现价可从实时行情自动补）。"""
    symbol = str(args.get("symbol") or "").strip().upper()
    if not symbol:
        return "需要提供代码，例如 600519"
    try:
        shares = float(args.get("shares") or 0)
        cost = float(args.get("cost") or 0)
        last = float(args.get("last") or 0)
    except (TypeError, ValueError):
        return "份额/成本/现价需要是数字"
    if shares <= 0 or cost <= 0:
        return "需要份额（>0）与成本价（>0）"
    if last <= 0:
        q = await quote_now(symbol)
        last = float((q or {}).get("price") or 0)
    if last <= 0:
        return "无法取得现价，请提供 last 现价"
    name = str(args.get("name") or "").strip()
    if not name:
        q = await quote_now(symbol)
        name = (q or {}).get("name") or symbol
    position_data = {
        "symbol": symbol,
        "name": name,
        "kind": str(args.get("kind") or "股票"),
        "industry": str(args.get("industry") or "其他"),
        "shares": shares,
        "cost": cost,
        "last": last,
        "buy_date": str(args.get("buy_date") or "") or None,
        "fee": 0,
    }
    try:
        await db.add_position(position_data)
    except Exception as exc:  # noqa: BLE001
        return f"记录失败：{exc}"
    await record_provenance(
        action="add_position",
        entity_type="position",
        entity_id=symbol,
        before=None,
        after=position_data,
        source="mcp",
    )
    return (
        f"已记录买入 {name}（{symbol}）：{shares:g} 份 × 成本 {cost:g}，现价 {last:g}。"
        "可在总览/持仓页查看最新盈亏。"
    )


# ---------------------------------------------------------------------------
# 工具注册表：OpenAI function calling 的 JSON Schema + 执行体
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 工具注册表：入参 schema 来自 tool_schemas.py（单一真源，M2.1）
# ---------------------------------------------------------------------------
#
# 改造前这里是 270 行手写的 JSON Schema 字面量，与 mcp_server.py 的函数签名
# 各自维护同一份额外真相，两份已经漂移。现在 schema 只在 tool_schemas.py
# 定义一次，此处仅声明「哪些工具属于财务技能包」以及它们的描述文案。
# 描述文案保留在这里而非模型里：它是给模型的调用指引，与参数定义是两件事。

FINANCE_TOOL_NAMES: tuple[tuple[str, str], ...] = (
    ("get_market_view",
     "查询用户持仓组合：总市值、累计盈亏、前几大持仓、集中度告警。适合回答关于持仓、盈亏、资产、集中度的问题。"),
    ("get_ledger_view",
     "查询用户账本：本月收入、支出、结余、储蓄率、支出分类、订阅、负债、应急金。适合回答关于钱花到哪、结余、负债、应急金的问题。"),
    ("get_risk_flags",
     "运行风控规则：集中度超限、应急金不足、高息负债、负债收入比偏高、储蓄率偏低等告警。适合回答「我有什么风险」「哪里需要关注」。"),
    ("get_budget",
     "查询预算设置与实时使用情况。适合回答关于预算、超支、还剩多少钱能花的问题。"),
    ("get_trend",
     "查询近几个月收支趋势（收入/支出/结余）。适合回答「钱花得越来越多吗」「这个月和上个月比」等问题。"),
    ("record_transaction",
     "一句话记账：把用户的记账指令（如「昨天打车 32 元」「工资 8000 已到账」）解析并写入账本。仅当用户明确表达记账意图时调用。"),
    ("get_kline",
     "查询某标的的K线走势（A股/ETF）。适合回答「某只股票最近走势如何」。"),
    ("get_goals",
     "查询用户的财务目标：目标金额、已存金额、进度百分比、距截止月、建议月存。适合回答「我存够了吗」「目标进展如何」「还差多少」。"),
    ("get_user_memory",
     "查询用户的长期记忆：用户主动告知的长期信息（家庭、职业、偏好、未来计划等）。回答涉及用户背景或长期规划时先查记忆；可用 query 按关键词检索相关记忆，或用 kind 过滤类型（fact/preference/goal_related）。"),
    ("save_user_memory",
     "记住一条用户的长期信息（如「明年计划买房」「每月收入 2 万」「有一个孩子」）。当用户在对话中主动透露可用于未来的背景信息时调用；临时性、一次性信息不要记。"),
    ("get_lessons",
     "查询经验库：之前工具调用的踩坑记录（工具失败后反思时参考，避免重复犯同样的错误）。"),
    ("get_health_check",
     "跑一次结构化财务体检：资产配置 / 现金流 / 负债 / 应急金 / 目标进度 五个维度的评分与建议。适合回答「帮我体检一下」「我的财务状况怎么样」「哪里需要改进」。"),
    ("search_symbol",
     "搜索 A股/基金/指数（按代码或名称，如「茅台」「600519」）。用于用户想了解某只标的但不知道代码，或要先找到标的再决定看行情/加自选。"),
    ("get_quote",
     "查询单只标的实时行情：现价、涨跌幅、来源（东财/新浪）。适合「茅台现在多少钱」「今天涨了吗」等问题。"),
    ("add_to_watchlist",
     "把某只标的加入自选（用户表达「关注/盯一下/加自选」时调用）。成功后用户可在行情页自选 Tab 看到。"),
    ("remove_from_watchlist",
     "把某只标的自自选移除（用户表达「不看了/移除自选」时调用）。"),
    ("get_watchlist",
     "查询用户自选列表及其实时行情。适合「我的自选现在怎么样」「自选里谁涨了」。"),
    ("record_position",
     "记录一笔买入持仓（用户表达「买了/买入/建仓/补仓」并给出代码或名称与数量成本时调用）。成功后总览与持仓页自动更新。"),
    ("sell_position",
     "卖出/减仓持仓（用户表达「卖出/卖掉/清仓/减仓/抛售」并给出代码时调用；数量省略=全部清仓）。成功后持仓页自动更新。"),
    ("trigger_morning_report",
     "立即生成今日晨报（组合+账本+财务目标体检）。用户说「生成晨报/今日晨报/帮我体检」时调用。空库会提示先有数据。"),
    ("backup_now",
     "生成本地加密备份包（口令只显示一次）。用户说「备份/导出存档」时调用。"),
    ("set_setting",
     "修改应用偏好：涨跌颜色 color_scheme（cn 红涨绿跌 / us 绿涨红跌）、默认首页 default_tab（overview/holdings/market/ledger/chat）、语言 lang（zh/en）、数字格式 compact_numbers、快捷建议 show_suggestions（on/off）、晨报时间 morning_report_time（HH:MM）。"),
    ("get_portfolio_risk",
     "计算组合风险指标：年化波动率、夏普、索提诺、最大回撤、Calmar、Beta/Alpha、VaR、与沪深300等基准的对比。适合回答「我的组合风险大吗」「收益跑赢大盘了吗」「波动大不大」。"),
    ("get_rebalance_plan",
     "给出再平衡建议：对照用户设定的目标配置，列出偏离度与应买/应卖金额、约多少股。适合回答「该怎么调仓」「仓位要不要调整」。需用户已设置目标配置。"),
    ("get_valuation",
     "查估值位置分位：当前价在近 750 个交易日区间中的位置（0=最低，100=最高），并给出低位/中枢/高位分区。适合回答「现在贵不贵」「是不是高位」。只描述位置，不预测涨跌。"),
    ("get_dca_plans",
     "查定投计划与回测：每期金额、累计投入、持仓份额、成本线、当前盈亏、下一期扣款日。适合回答「我的定投赚了吗」「下次什么时候扣」。"),
    ("get_fire_plan",
     "计算 FIRE 进度：目标本金（年支出/提取率）、当前完成度、储蓄率、按复利估算的达成年限。适合回答「我什么时候能财务自由」「还要存多少」。"),
    ("research_analyze",
     "技术面研报：对某只 A 股/ETF 计算 MA/MACD/RSI/BOLL/KDJ 指标，输出多空倾向与规则信号。适合回答「帮我分析一下 XX 的技术面」「XX 现在该不该看」「XX 趋势如何」。"),
    ("research_backtest",
     "策略回测：对某只 A 股/ETF 跑双均线或定投策略的历史回测（收益/回撤/夏普/胜率）。适合回答「双均线策略在 XX 上表现如何」「定投 XX 划不划算」。"),
    ("statements_analyze",
     "财报分析：输入标准化三表 JSON，输出 20+ 财务指标、杜邦拆解、同比趋势与异常预警。适合用户提供公司财务数据时做深度分析。"),
    ("research_forecast",
     "统计预测：对某只 A 股/ETF 输出未来 N 期线性趋势、年化波动率与蒙特卡洛分位区间（固定种子可复现）。适合回答「XX 未来走势区间大概多少」「预测一下 XX 的价格带」。输出为统计情景推演，不是保证价位。"),
    ("paper_open",
     "团队模拟盘开户：为成员创建虚拟账户（独立初始资金）。适合「给小组开个模拟账户」「团队炒股开户」。"),
    ("paper_trade",
     "团队模拟盘下单：买入/卖出虚拟持仓（A股整手、含佣金与印花税），自动更新净值与团队排行。适合「模拟买入 600519 100 股」「帮我模拟卖出」。"),
    ("paper_overview",
     "团队模拟盘总览：账户收益率排行、团队汇总、各账户持仓摘要。适合「团队炒股战绩如何」「模拟盘谁跑得好」。"),
)

TOOLS: list[dict[str, Any]] = [
    tool_schemas.function_schema(name, desc) for name, desc in FINANCE_TOOL_NAMES
]


TOOL_IMPL: dict[str, Any] = {
    "get_market_view": tool_get_market_view,
    "get_ledger_view": tool_get_ledger_view,
    "get_risk_flags": tool_get_risk_flags,
    "get_budget": tool_get_budget,
    "get_trend": tool_get_trend,
    "record_transaction": tool_record_transaction,
    "get_kline": tool_get_kline,
    "get_goals": tool_get_goals,
    "get_user_memory": tool_get_user_memory,
    "save_user_memory": tool_save_user_memory,
    "get_lessons": tool_get_lessons,
    "get_health_check": tool_get_health_check,
    "search_symbol": tool_search_symbol,
    "get_quote": tool_get_quote,
    "add_to_watchlist": tool_add_watchlist,
    "remove_from_watchlist": tool_remove_watchlist,
    "get_watchlist": tool_get_watchlist,
    "record_position": tool_record_position,
    "sell_position": tool_sell_position,
    "trigger_morning_report": tool_trigger_morning_report,
    "backup_now": tool_backup_now,
    "set_setting": tool_set_setting,
    "get_portfolio_risk": tool_get_portfolio_risk,
    "get_rebalance_plan": tool_get_rebalance_plan,
    "get_valuation": tool_get_valuation,
    "get_dca_plans": tool_get_dca_plans,
    "get_fire_plan": tool_get_fire_plan,
    "research_analyze": tool_research_analyze,
    "research_backtest": tool_research_backtest,
    "statements_analyze": tool_statements_analyze,
    "research_forecast": tool_research_forecast,
    "paper_open": tool_paper_open,
    "paper_trade": tool_paper_trade,
    "paper_overview": tool_paper_overview,
}

# 工具返回体量上限：超过即截断（防止把整库明细喂给模型）
TOOL_RESULT_MAX_CHARS = 2500


def _fn(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    """统一生成 OpenAI function schema（新增工具的统一注册入口）。"""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


async def tool_get_now(_args: dict[str, Any]) -> str:
    """返回当前日期与时间（服务器本地时区）。领域无关的通用工具。"""
    import datetime as _dt

    now = _dt.datetime.now()
    return f"现在是 {now.strftime('%Y-%m-%d %H:%M:%S')}（服务器本地时间）。"


def _load_ddgs() -> Any:
    """导入 duckduckgo_search 模块并立即恢复被其 import 副作用替换的事件循环策略。

    该包在 Windows 上 import 时执行 set_event_loop_policy(WindowsSelectorEventLoopPolicy)
    （见其 __init__.py），会把宿主（uvicorn / pytest-asyncio）正在用的 Proactor 循环变成
    孤儿（"unclosed event loop"）。我们只用它的同步 DDGS，不需要换策略。
    """
    prev_policy = asyncio.get_event_loop_policy()
    try:
        import duckduckgo_search
    finally:
        asyncio.set_event_loop_policy(prev_policy)
    return duckduckgo_search


async def tool_web_search(args: dict[str, Any]) -> str:
    """联网搜索（免 key，DuckDuckGo 即时答案 API）；失败返回明确提示，绝不抛错。

    供 general（非财务）分支使用：让「通用 agent」能回答最新新闻/时事等需要外部信息的问题。
    用 DuckDuckGo（而非旧版 Bing HTML 抓取）是因为其结构化 JSON 接口更稳定、不被反爬策略影响。
    """
    q = str((args or {}).get("q") or "").strip()
    if not q:
        return "缺少搜索关键词（q）。"
    # duckduckgo_search 同步调用在异步上下文：run_in_executor 避免阻塞事件循环
    try:
        DDGS = _load_ddgs().DDGS

        loop = asyncio.get_running_loop()

        def _search() -> list[dict[str, str]]:
            with DDGS() as ddgs:
                return [
                    {"title": r.get("title", ""), "snippet": r.get("body", "")}
                    for r in ddgs.text(q, region="wt-wt", safesearch="moderate", max_results=5)
                    if r.get("title")
                ]

        results = await loop.run_in_executor(None, _search)
    except Exception as exc:  # noqa: BLE001 — 联网失败必须兜底，绝不拖垮对话
        return f"联网搜索暂时不可用：{type(exc).__name__}。请稍后再试。"
    if not results:
        return f"未找到「{q}」的相关结果，换个说法再试试。"
    lines = [f"- {r['title']}" + (f"：{r['snippet']}" if r.get("snippet") else "") for r in results]
    return "搜索结果：\n" + "\n".join(lines)


# 通用技能包：领域无关工具（时间 / 联网搜索），供 general（非财务）分支装配，
# 让「通用 Agent 内核」不依赖任何财务能力 —— 这是「先 Agent、后财务」的落点。
GENERAL_TOOL_NAMES: tuple[tuple[str, str], ...] = (
    (
        "get_now",
        "查询当前日期与时间（服务器本地时区）。适合回答「今天几号」「现在几点」等时间问题。",
    ),
    (
        "web_search",
        "联网搜索，返回相关结果标题。适合回答最新新闻、时事、科普等需要外部信息的问题。",
    ),
)
GENERAL_TOOLS: list[dict[str, Any]] = [
    tool_schemas.function_schema(name, desc) for name, desc in GENERAL_TOOL_NAMES
]
GENERAL_IMPL: dict[str, Any] = {"get_now": tool_get_now, "web_search": tool_web_search}


# ---------------------------------------------------------------------------
# 统一技能注册表：所有工具的单一真源（name → schema/impl/mode）。
# 财务工具 mode="finance"，通用工具 mode="general"；技能包（FINANCE_*/GENERAL_*）
# 全部由本注册表派生，作为「技能包装配」的唯一入口，后续新增工具只需在此登记。
# NOTE：TOOLS / TOOL_IMPL 保持仅财务，通用工具走 GENERAL_*（agent 默认读取只暴露
# 财务工具，守住「财务分析不用通用工具」的边界）。
# ---------------------------------------------------------------------------
_GENERAL_SCHEMAS = {t["function"]["name"]: t for t in GENERAL_TOOLS}
_TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    t["function"]["name"]: {
        "schema": t, "impl": TOOL_IMPL[t["function"]["name"]], "mode": "finance",
    }
    for t in TOOLS
}
_TOOL_REGISTRY.update({
    n: {"schema": _GENERAL_SCHEMAS[n], "impl": GENERAL_IMPL[n], "mode": "general"}
    for n in GENERAL_IMPL
})

FINANCE_TOOLS: list[dict[str, Any]] = [r["schema"] for r in _TOOL_REGISTRY.values() if r["mode"] == "finance"]
FINANCE_IMPL: dict[str, Any] = {n: r["impl"] for n, r in _TOOL_REGISTRY.items() if r["mode"] == "finance"}
GENERAL_TOOLS: list[dict[str, Any]] = [r["schema"] for r in _TOOL_REGISTRY.values() if r["mode"] == "general"]
GENERAL_IMPL: dict[str, Any] = {n: r["impl"] for n, r in _TOOL_REGISTRY.items() if r["mode"] == "general"}
TOOL_REGISTRY: dict[str, dict[str, Any]] = _TOOL_REGISTRY


def truncate_tool_result(text: str) -> str:
    if len(text) <= TOOL_RESULT_MAX_CHARS:
        return text
    return text[:TOOL_RESULT_MAX_CHARS] + "…（已截断，只保留关键数字）"


# ---------------------------------------------------------------------------
# 确定性动作执行：不配模型也能在对话里直接执行（卖出/晨报/备份）
# ---------------------------------------------------------------------------
_ACTION_STOP = {"卖出", "卖掉", "清仓", "减仓", "抛售", "全部", "帮我", "一下", "现在", "把"}


async def _create_pending(
    tool_name: str,
    args: dict[str, Any],
    summary: str,
    lang: str,
    emit: Emit | None,
) -> str:
    """登记写类动作为待确认（token 一次性、10 分钟过期）；失败降级为直接执行（不阻塞原路径）。"""
    _action_log.info("PENDING %s args=%s summary=%r", tool_name, json.dumps(args, ensure_ascii=False), summary)
    try:
        out = await db.create_pending_action(tool_name, args, summary, lang)
    except Exception:  # noqa: BLE001 — 待确认登记失败不阻断原动作
        _action_log.exception("PENDING creation failed for %s", tool_name)
        return ""
    if emit is not None:
        await emit({"type": "pending_action", "token": out["token"], "summary": summary})
    _action_log.info("PENDING token=%s tool=%s", out["token"], tool_name)
    return out["token"]


def _match_position_by_name(q: str, positions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """名称匹配持仓：全名命中或任意两字连续命中（跳过动作/虚词/通用公司后缀），用于「清仓茅台」这类说法。

    跳过股份/有限/公司/集团等通用后缀，避免"招商银行"被含"银行"/"公司"的任意问题误匹配。"""
    GENERIC_COMPANY_SUFFIXES = {"股份", "有限", "公司", "集团", "银行", "证券", "保险", "信托", "基金"}
    for p in positions:
        name = (p.get("name") or "").strip()
        if not name:
            continue
        if name in q:
            return p
        for i in range(len(name) - 1):
            bigram = name[i : i + 2]
            if bigram in _ACTION_STOP:
                continue
            if bigram in GENERIC_COMPANY_SUFFIXES:
                continue
            if bigram in q:
                return p
    return None


async def run_action(question: str, lang: str = "zh", *, emit: Emit | None = None) -> dict[str, Any]:
    """对话内确定性动作：卖出/清仓/减仓 → sell_position；晨报 → 生成；备份 → 加密备份。
    返回与记账回执同构的 dict（answer/level/route/…/actions），供 agent 成文与前端跳转。"""
    q = question
    en = lang != "zh"

    if any(w in q for w in ("默认首页", "涨跌颜色", "颜色主题", "换颜色", "切换语言")):
        key, value = None, None
        if "默认首页" in q:
            key = "default_tab"
            vmap = {"总览": "overview", "持仓": "holdings", "行情": "market",
                    "记账": "ledger", "问ai": "chat", "对话": "chat", "chat": "chat"}
            for k, v in vmap.items():
                if k in q:
                    value = v
                    break
        elif any(w in q for w in ("涨跌颜色", "颜色主题", "换颜色")):
            key = "color_scheme"
            value = "us" if ("绿涨" in q or "绿色" in q or "us" in q.lower()) else "cn"
        elif "切换语言" in q or "语言" in q:
            key = "lang"
            value = "en" if ("英文" in q or "english" in q.lower() or "en" in q.lower()) else "zh"
        if key and value:
            ans = await tool_set_setting({"key": key, "value": value}, lang)
            return {
                "answer": ans,
                "level": "已执行",
                "route": "action",
                "route_reason": "Settings instruction" if en else "设置指令",
                "metrics": {},
                "flags": [],
                "llm": "tool",
                "tools_used": ["set_setting"],
                "actions": [{"tab": "settings"}],
            }
        return {
            "answer": (
                "I can change these: default home (overview/holdings/market/ledger/chat), color scheme "
                "(red-up/green-down or green-up/red-down), and language (Chinese/English). "
                'E.g. "set default home to holdings" or "green-up".'
                if en
                else "我可以帮你改这些设置：默认首页（总览/持仓/行情/记账/问AI）、涨跌颜色（红涨绿跌/绿涨红跌）、语言（中文/英文）。例如「默认首页改成持仓」「涨跌颜色改成绿涨红跌」。"
            ),
            "level": "需要补充",
            "route": "action",
            "route_reason": "Settings instruction missing parameters" if en else "设置指令参数不足",
            "metrics": {},
            "flags": [],
            "llm": "tool",
            "actions": [{"tab": "settings"}],
        }

    if any(w in q for w in ("买入", "买进", "建仓", "加仓")):
        m = re.search(r"(\d{6})", q)
        symbol = m.group(1) if m else ""
        sm = re.search(r"(\d+)\s*[股份手]", q)
        shares = int(sm.group(1)) if sm else 100
        if not symbol:
            return {
                "answer": (
                    "Buying needs a stock code, e.g. \"buy 600519 100 shares\"."
                    if en
                    else "买入需要告诉我股票代码（例如「买入 600519 100 股」）。"
                ),
                "level": "需要补充",
                "route": "action",
                "route_reason": "Buy instruction missing symbol" if en else "买入指令缺代码",
                "metrics": {},
                "flags": [],
                "llm": "tool",
                "actions": [{"tab": "holdings"}],
            }
        q_ = await quote_now(symbol)
        cost = float((q_ or {}).get("price") or 0)
        if cost <= 0:
            return {
                "answer": (
                    "Couldn't fetch the current price as cost basis — provide a cost, e.g. \"buy 600519 100 shares cost 1250\"."
                    if en
                    else "无法获取当前行情作为成本价，请补充成本价（例如「买入 600519 100 股 成本 1250」）。"
                ),
                "level": "需要补充",
                "route": "action",
                "route_reason": "Buy missing cost price" if en else "买入缺成本",
                "metrics": {},
                "flags": [],
                "llm": "tool",
                "actions": [{"tab": "holdings"}],
            }
        buy_args = {"symbol": symbol, "shares": shares, "cost": cost}
        summary = (
            f"Buy {shares:g} shares of {symbol} (cost {cost:g})"
            if en
            else f"买入 {symbol} {shares:g} 股（成本 {cost:g}）"
        )
        token = await _create_pending("record_position", buy_args, summary, lang, emit)
        return {
            "answer": (
                f"Confirm buy: {summary}? Confirm to execute; valid for 10 minutes."
                if en
                else f"确认买入 {summary}？点确认后执行，10 分钟内有效。"
            ),
            "level": "待确认",
            "route": "action",
            "route_reason": "Buy instruction" if en else "买入指令",
            "metrics": {},
            "flags": [],
            "llm": "tool",
            "tools_used": ["add_position"],
            "actions": [{"tab": "holdings"}],
            "pending_token": token,
            "pending_summary": summary,
        }

    if any(w in q for w in ("卖出", "卖掉", "清仓", "减仓", "抛售")):
        m = re.search(r"(\d{6})", q)
        symbol = m.group(1) if m else ""
        if not symbol:
            matched = _match_position_by_name(q, await db.list_positions())
            if matched:
                symbol = matched["symbol"]
        if not symbol:
            return {
                "answer": (
                    "Sell needs a code (e.g. \"sell 600519\") or a holding name (e.g. \"clear 贵州茅台\")."
                    if en
                    else "卖出需要告诉我代码（例如「卖出 600519」）或持仓名称（例如「清仓贵州茅台」）。"
                ),
                "level": "需要补充",
                "route": "action",
                "route_reason": "Action instruction missing symbol" if en else "动作指令缺代码",
                "metrics": {},
                "flags": [],
                "llm": "tool",
                "actions": [{"tab": "holdings"}],
            }
        sell_args: dict[str, Any] = {"symbol": symbol}
        # 「卖出一半/半仓/减半」= 减仓到剩余一半，不能误清仓
        if re.search(r"一半|半仓|减半", q):
            cur = next((p for p in await db.list_positions() if p["symbol"] == symbol), None)
            if cur:
                sell_args["shares"] = round(cur["shares"] / 2, 4)
        if en:
            summary = f"Sell/clear {symbol}"
            summary += f" ({sell_args['shares']:g} shares)" if "shares" in sell_args else " (all)"
        else:
            summary = (
                f"卖出/清仓 {symbol}"
                + (f"（{sell_args['shares']:g} 份）" if "shares" in sell_args else "（全部）")
            )
        token = await _create_pending("sell_position", sell_args, summary, lang, emit)
        return {
            "answer": (
                f"Confirm sell: {summary}? Confirm to execute; valid for 10 minutes."
                if en
                else f"确认卖出 {summary}？点确认后执行，10 分钟内有效。"
            ),
            "level": "待确认",
            "route": "action",
            "route_reason": "Sell/clear instruction" if en else "卖出/清仓指令",
            "metrics": {},
            "flags": [],
            "llm": "tool",
            "tools_used": ["sell_position"],
            "actions": [{"tab": "holdings"}],
            "pending_token": token,
            "pending_summary": summary,
        }

    if "晨报" in q:
        ans = await tool_trigger_morning_report({}, lang)
        return {
            "answer": ans,
            "level": "已生成",
            "route": "action",
            "route_reason": "Morning report instruction" if en else "晨报指令",
            "metrics": {},
            "flags": [],
            "llm": "tool",
            "tools_used": ["trigger_morning_report"],
            "actions": [{"tab": "overview"}],
        }

    if "备份" in q:
        out = await tool_backup_now({}, lang)
        return {
            "answer": out["answer"],
            "level": "已执行",
            "route": "action",
            "route_reason": "Backup instruction" if en else "备份指令",
            "metrics": {},
            "flags": [],
            "llm": "tool",
            "tools_used": ["backup_now"],
            "actions": [{"tab": "settings"}],
            "passphrase": out["passphrase"],
        }

    return {
        "answer": (
            "I can't run that instruction directly right now. Try: sell a holding (e.g. \"sell 600519\"), "
            'generate today\'s morning report ("generate today\'s report"), or create a backup ("back up").'
            if en
            else "这条指令我暂时还不能直接执行。你可以试试：卖出持仓（如「卖出 600519」）、生成晨报（「生成今日晨报」）或备份（「备份一下」）。"
        ),
        "level": "未识别",
        "route": "action",
        "route_reason": "Action instruction not matched" if en else "动作指令未命中",
        "metrics": {},
        "flags": [],
        "llm": "tool",
        "actions": [],
    }

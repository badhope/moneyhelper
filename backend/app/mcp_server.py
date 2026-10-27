"""MCP Server：把 Moneyhelper 所有工具暴露为标准 MCP 协议。

通过 fastmcp 把 tools.py 里的工具包装成 MCP 工具，让任何支持 MCP Client 的 AI IDE
（Claude Code / Cursor / Windsurf / Cline 等）都能直接调用 Moneyhelper 的工具集：
- 持仓分析、账本查询、风控、预算、目标、K线 等财务工具
- search_symbol / get_quote / add_to_watchlist 等行情工具
- get_now / web_search 等通用工具

启动方式：
1. 嵌入 FastAPI（默认）：mount 到 /mcp 路径，与主应用同进程
2. 独立进程：python -m app.mcp_server（stdio transport，供 Claude Desktop 接入）

MCP 协议接入后，Claude Code / Cursor 等 IDE 可以直接对 Moneyhelper 数据库执行财务分析。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from starlette.routing import BaseRoute

from . import db
from . import tools as xtools
from .logging_utils import get_logger
from .provenance import record_provenance

log = get_logger(__name__)

# MCP Server：fastmcp 版本与 FastAPI 版本可能冲突，import 失败就降级 no-op
try:
    from fastmcp import Context, FastMCP
    mcp = FastMCP("moneyhelper-finance")
    MCP_AVAILABLE = True
except Exception as e:  # pragma: no cover
    log.warning("mcp.fastmcp_unavailable: %s — MCP server disabled", e)
    # 假装饰器：让 @mcp.tool() / @mcp.resource() 等不炸，函数原样返回
    class _FakeMCP:
        def tool(self, *a, **kw):
            def deco(fn): return fn
            return deco
        def resource(self, *a, **kw):
            def deco(fn): return fn
            return deco
        def prompt(self, *a, **kw):
            def deco(fn): return fn
            return deco
        def sse_app(self):
            raise RuntimeError("MCP unavailable")
    mcp = _FakeMCP()
    MCP_AVAILABLE = False


# ---------------------------------------------------------------------------
# 持仓 / 组合分析工具
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_market_view() -> str:
    """查询用户持仓组合：总市值、累计盈亏、前几大持仓、集中度告警。"""
    return await xtools.tool_get_market_view({})


@mcp.tool()
async def get_ledger_view() -> str:
    """查询用户账本：本月收入、支出、结余、储蓄率、支出分类、订阅、负债、应急金。"""
    return await xtools.tool_get_ledger_view({})


@mcp.tool()
async def get_risk_flags() -> str:
    """运行风控规则：集中度超限、应急金不足、高息负债、负债收入比偏高、储蓄率偏低等告警。"""
    return await xtools.tool_get_risk_flags({})


@mcp.tool()
async def get_budget(month: str = "") -> str:
    """查询预算设置与实时使用情况。month 格式 YYYY-MM，省略=本月。"""
    return await xtools.tool_get_budget({"month": month})


@mcp.tool()
async def get_trend(months: int = 6) -> str:
    """查询近几个月收支趋势。months 范围 1-24，默认 6。"""
    return await xtools.tool_get_trend({"months": months})


@mcp.tool()
async def get_goals() -> str:
    """查询用户的财务目标：目标金额、已存金额、进度百分比、距截止月、建议月存。"""
    return await xtools.tool_get_goals({})


@mcp.tool()
async def get_health_check() -> str:
    """跑一次结构化财务体检：资产配置 / 现金流 / 负债 / 应急金 / 目标进度 五个维度评分与建议。"""
    return await xtools.tool_get_health_check({})


# ---------------------------------------------------------------------------
# 投资策略工具（与 LLM function calling 同源，数字由确定性引擎算出）
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_portfolio_risk(benchmark: str = "sh000300") -> str:
    """组合风险指标：年化波动率、夏普、索提诺、最大回撤、Calmar、Beta/Alpha、VaR，并与基准对比。benchmark 可选 sh000300/sh000001/sz399001/sz399006。"""
    return await xtools.tool_get_portfolio_risk({"benchmark": benchmark})


@mcp.tool()
async def get_rebalance_plan(band_pct: float = 5.0) -> str:
    """再平衡建议：对照目标配置给出偏离度与应买/应卖金额、约多少股。band_pct 为容忍带百分比。"""
    return await xtools.tool_get_rebalance_plan({"band_pct": band_pct})


@mcp.tool()
async def get_valuation(symbols: str = "") -> str:
    """估值位置分位：当前价在近 750 个交易日区间中的位置（0=最低，100=最高）。symbols 为逗号分隔代码，省略=全部持仓。"""
    return await xtools.tool_get_valuation({"symbols": symbols})


@mcp.tool()
async def get_dca_plans() -> str:
    """定投计划与回测：每期金额、累计投入、份额、成本线、当前盈亏、下一期扣款日。"""
    return await xtools.tool_get_dca_plans({})


@mcp.tool()
async def get_fire_plan() -> str:
    """FIRE 进度：目标本金、当前完成度、储蓄率、按复利估算的达成年限。"""
    return await xtools.tool_get_fire_plan({})


# ---------------------------------------------------------------------------
# 行情 / 自选工具
# ---------------------------------------------------------------------------


@mcp.tool()
async def search_symbol(query: str) -> str:
    """搜索 A股/基金/指数（按代码或名称，如「茅台」「600519」）。"""
    return await xtools.tool_search_symbol({"query": query})


@mcp.tool()
async def get_quote(symbol: str) -> str:
    """查询单只标的实时行情：现价、涨跌幅、来源（东财/新浪）。symbol 为 6 位代码如 600519。"""
    return await xtools.tool_get_quote({"symbol": symbol})


@mcp.tool()
async def get_kline(symbol: str, period: str = "daily", limit: int = 60) -> str:
    """查询某标的的 K 线走势。symbol=6 位代码，period=daily/weekly/monthly，limit=返回点数（10-500）。"""
    return await xtools.tool_get_kline({"symbol": symbol, "period": period, "limit": limit})


@mcp.tool()
async def add_to_watchlist(symbol: str, name: str = "", kind: str = "股票") -> str:
    """把标的加入自选。name 省略时自动从实时行情获取名称。"""
    return await xtools.tool_add_watchlist({"symbol": symbol, "name": name, "kind": kind})


@mcp.tool()
async def remove_from_watchlist(symbol: str) -> str:
    """自选列表移除标的。"""
    return await xtools.tool_remove_watchlist({"symbol": symbol})


@mcp.tool()
async def get_watchlist() -> str:
    """查询自选列表及其实时行情。"""
    return await xtools.tool_get_watchlist({})



# ---------------------------------------------------------------------------
# 写操作审批（M2.3）：MCP 侧的 elicitation 门禁
# ---------------------------------------------------------------------------
#
# 改造前 MCP 的写工具完全没有审批：任何接入的 MCP 客户端都能直接改账本，
# 与大额阈值（Web 对话里 >5000 元要确认）完全脱节。MCP 规范提供
# elicitation（服务端向客户端请求用户输入），正好承载这个语义：
#
#   Web 对话：超阈值 → route=nl_pending，问「确认/取消」
#   MCP     ：超阈值 → ctx.elicit(...)，客户端弹表单，用户点接受/拒绝
#
# 两条路径共用 approval.threshold 与 approval.format_approval_prompt，
# 保证"什么算大额"和"怎么问"一致。
#
# 客户端不支持 elicitation 时（老客户端 / 无 UI 的自动化场景）必须 **拒绝执行**，
# 而不是静默放行——审批是安全网，宁可失败也不能悄悄写入。


async def _confirm_write(ctx: Any, summary: str, amount: float) -> bool:
    """向客户端请求大额写操作确认；返回 True 表示用户同意。

    非大额直接返回 True（不打扰用户）；客户端不支持 elicitation 时返回 False
    （fail-closed）。
    """
    from . import approval

    if not await approval.needs_approval(amount):
        return True
    if ctx is None:
        log.warning("mcp.approval_no_context: 大额写操作缺少 Context，拒绝执行")
        return False

    from fastmcp.server.elicitation import (
        AcceptedElicitation,
        CancelledElicitation,
        DeclinedElicitation,
    )

    try:
        result = await ctx.elicit(approval.format_approval_prompt(summary, amount))
    except Exception as exc:  # noqa: BLE001 — 客户端不支持 elicitation 等
        log.warning("mcp.approval_failed: %s — 拒绝执行写操作", exc)
        return False

    if isinstance(result, AcceptedElicitation):
        return True
    if isinstance(result, (DeclinedElicitation, CancelledElicitation)):
        return False
    return False


# ---------------------------------------------------------------------------
# 记账 / 记忆工具
# ---------------------------------------------------------------------------


@mcp.tool()
async def record_transaction(text: str, ctx: Context | None = None) -> str:
    """一句话记账：把用户的记账指令（如「昨天打车 32」「工资 8000 已到账」）解析并写入账本。
    金额超过审批阈值时会先请用户确认。"""
    from . import nlparse

    parsed = nlparse.parse(text) or await nlparse.parse_with_ai(text)
    if parsed is None:
        # 交给底层实现给出统一的解析失败提示
        return await xtools.tool_record_transaction({"text": text})
    from . import approval

    summary = approval.describe_transaction(parsed)
    if not await _confirm_write(ctx, summary, float(parsed.get("amount", 0))):
        return "已取消：用户未确认这笔大额记账，账本未改动。"
    return await xtools.tool_record_transaction({"text": text})


@mcp.tool()
async def record_position(symbol: str, shares: float, cost: float, last: float = 0,
                          name: str = "", kind: str = "股票", industry: str = "其他",
                          buy_date: str = "", ctx: Context | None = None) -> str:
    """记录一笔买入持仓。symbol=代码(6位), shares=份额, cost=成本价, last=现价(自动获取可省略)。
    买入金额超过审批阈值时会先请用户确认。"""
    amount = float(shares or 0) * float(cost or 0)
    summary = f"买入 {name or symbol} {shares:g} 份 × {cost:g} 元"
    if not await _confirm_write(ctx, summary, amount):
        return "已取消：用户未确认这笔大额买入，持仓未改动。"
    return await xtools.tool_record_position({
        "symbol": symbol, "shares": shares, "cost": cost, "last": last,
        "name": name, "kind": kind, "industry": industry, "buy_date": buy_date,
    })


@mcp.tool()
async def sell_position(symbol: str, shares: float = 0, ctx: Context | None = None) -> str:
    """卖出/减仓持仓。symbol=代码, shares=份额(省略=全部清仓)。
    卖出金额超过审批阈值时会先请用户确认。"""
    # 卖出金额 = 份额 × 现价；现价取不到时按 0 处理（不触发审批，但底层会拒绝无现价卖出）
    try:
        from .quotes import quote_now

        q = await quote_now(symbol)
        price = float((q or {}).get("price") or 0)
    except Exception:  # noqa: BLE001 — 行情不可用不影响审批判定的降级
        price = 0.0

    # 清仓（shares=0）此前直接算成 0 元，永远不会触发审批——而清仓恰恰是
    # 金额最大、最不可逆的操作。这里用持仓市值兜底：现价缺失时退回成本价。
    effective_shares = float(shares or 0)
    if not effective_shares:
        try:
            rows = await db.list_positions()
        except Exception:  # noqa: BLE001
            rows = []
        pos = next((p for p in rows if p.get("symbol") == symbol), None)
        if pos:
            effective_shares = float(pos.get("shares") or 0)
            if price <= 0:
                price = float(pos.get("last") or pos.get("cost") or 0)
    amount = effective_shares * price
    summary = f"卖出 {symbol} {shares:g} 份" if shares else f"清仓 {symbol}"
    if not await _confirm_write(ctx, summary, amount):
        return "已取消：用户未确认这笔大额卖出，持仓未改动。"
    return await xtools.tool_sell_position({"symbol": symbol, "shares": shares})


@mcp.tool()
async def save_user_memory(content: str) -> str:
    """记住一条用户的长期信息（如「明年计划买房」「每月收入 2 万」）。"""
    return await xtools.tool_save_user_memory({"content": content})


@mcp.tool()
async def get_user_memory(query: str = "", kind: str = "") -> str:
    """查询用户长期记忆。query 关键词检索，kind 类型过滤(fact/preference/goal_related)。"""
    return await xtools.tool_get_user_memory({"query": query, "kind": kind})


@mcp.tool()
async def get_lessons() -> str:
    """查询经验库：之前工具调用的踩坑记录（避免重复犯同样的错误）。"""
    return await xtools.tool_get_lessons({})


@mcp.tool()
async def set_setting(key: str, value: str, lang: str = "zh") -> str:
    """修改应用偏好。key 如 color_scheme/default_tab/lang/compact_numbers 等；
    详细可用键与取值见工具描述。AI 接入配置（ai_base_url/ai_api_key/ai_model）
    一律拒绝，需到设置页修改。"""
    return await xtools.tool_set_setting({"key": key, "value": value}, lang=lang)


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_now() -> str:
    """返回当前日期与时间（服务器本地时区）。"""
    return await xtools.tool_get_now({})


@mcp.tool()
async def web_search(q: str) -> str:
    """联网搜索（免 key，Bing 接口，国内可达）。q 为搜索关键词。"""
    return await xtools.tool_web_search({"q": q})


# ---------------------------------------------------------------------------
# 投研 / 财报工具（v4.0：确定性技术面 + 回测 + 三表分析）
# ---------------------------------------------------------------------------


@mcp.tool()
async def research_analyze(symbol: str, period: str = "daily", limit: int = 180) -> str:
    """股票技术面研报：MA/MACD/RSI/BOLL/KDJ 指标快照 + 规则信号 + 多空倾向 + 文字结论。symbol 为 6 位代码，period 可选 daily/weekly/monthly。"""
    return await xtools.tool_research_analyze(
        {"symbol": symbol, "period": period, "limit": limit}
    )


@mcp.tool()
async def research_backtest(
    symbol: str,
    strategy: str = "ma_cross",
    fast: int = 5,
    slow: int = 20,
    invest_amount: float = 1000.0,
    freq_days: int = 5,
) -> str:
    """策略历史回测：ma_cross（双均线）或 dca（定投），输出收益/年化/最大回撤/夏普/胜率/盈亏比。symbol 为 6 位代码。"""
    return await xtools.tool_research_backtest(
        {
            "symbol": symbol,
            "strategy": strategy,
            "fast": fast,
            "slow": slow,
            "invest_amount": invest_amount,
            "freq_days": freq_days,
        }
    )


@mcp.tool()
async def statements_analyze(payload: dict) -> str:
    """财报分析：输入标准化三表 JSON（{company, currency, periods:[{period, balance_sheet, income_statement, cashflow_statement}]}），输出 20+ 指标、杜邦拆解、异常预警与文字报告。"""
    return await xtools.tool_statements_analyze({"payload": payload})


@mcp.tool()
async def research_forecast(symbol: str, period: str = "daily", days: int = 20) -> str:
    """价格统计预测：线性趋势 + 年化波动率 + 蒙特卡洛 GBM 分位区间（固定种子可复现）。symbol 为 6 位代码，days 为预测根数。"""
    return await xtools.tool_research_forecast({"symbol": symbol, "period": period, "days": days})


# ---------------------------------------------------------------------------
# 团队模拟盘工具（v4.2：事件溯源式虚拟账户）
# ---------------------------------------------------------------------------


@mcp.tool()
async def paper_open(name: str = "模拟账户", initial_cash: float = 100000.0) -> str:
    """团队模拟盘开户：为成员创建虚拟账户（独立初始资金，最小 1000）。"""
    return await xtools.tool_paper_open({"name": name, "initial_cash": initial_cash})


@mcp.tool()
async def paper_trade(account_id: str, symbol: str, side: str, price: float, shares: float) -> str:
    """团队模拟盘下单：买入/卖出虚拟持仓（A股整手、含佣金与印花税）。side 为 buy/sell。"""
    return await xtools.tool_paper_trade(
        {"account_id": account_id, "symbol": symbol, "side": side, "price": price, "shares": shares}
    )


@mcp.tool()
async def paper_overview() -> str:
    """团队模拟盘总览：账户收益率排行、团队汇总、持仓摘要。"""
    return await xtools.tool_paper_overview({})


# ---------------------------------------------------------------------------
# 写操作（需谨慎）：晨报 / 备份
# ---------------------------------------------------------------------------


@mcp.tool()
async def trigger_morning_report(lang: str = "zh") -> str:
    """立即生成今日晨报（组合+账本+财务目标体检）。lang=zh/en。"""
    return await xtools.tool_trigger_morning_report({}, lang=lang)


@mcp.tool()
async def backup_now(lang: str = "zh") -> str:
    """生成本地加密备份包（口令只显示一次，不落盘）。"""
    return await xtools.tool_backup_now({}, lang=lang)


# ---------------------------------------------------------------------------
# 资源暴露（MCP resource）：系统说明
# ---------------------------------------------------------------------------


@mcp.resource("moneyhelper://scheduled-outputs")
async def scheduled_outputs_resource() -> str:
    """最近的定时产出（晨报 + 技能触发），供 MCP 客户端主动拉取。

    为什么用 resource 而不是 Tasks：MCP 的 Tasks（长任务推送）在 mcp 1.30 仍属
    experimental，fastmcp 2.x 未透传，落地要绕开框架直接用 lowlevel server。
    而"客户端能拿到定时产出"这个真实需求，用 resource 拉取即可满足——
    客户端按自己的节奏刷新，服务端由既有 APScheduler 负责生成。
    """
    rows = await db.list_scheduled_runs(10)

    items = [
        {
            "thread_id": r.get("thread_id"),
            "question": r.get("question"),
            "answer": r.get("answer"),
            "level": r.get("level"),
            "created_at": r.get("created_at"),
        }
        for r in rows
    ]
    return json.dumps(
        {"count": len(items), "items": items},
        ensure_ascii=False,
        indent=1,
    )


@mcp.resource("moneyhelper://scheduler-status")
async def scheduler_status_resource() -> str:
    """定时任务状态（晨报开关、下次运行时间、上次错误）。"""
    from . import scheduler

    return json.dumps(scheduler.status(), ensure_ascii=False, indent=1)


@mcp.resource("moneyhelper://system-prompt")
def system_prompt_resource() -> str:
    """Moneyhelper 系统提示词：描述工具集和 Agent 行为规则。"""
    return (
        "你是 Moneyhelper(moneyhelper)财务 Agent，通过 MCP 工具访问用户的本地财务数据。\n"
        "规则：\n"
        "1. 需要数字时必须调用工具获取，绝不编造\n"
        "2. 先给一句话结论，再列关键数字，最后风险项\n"
        "3. 不给具体买卖指令\n"
        "4. 工具失败时如实说明\n"
        "5. 涉及用户背景先查 get_user_memory"
    )


# ---------------------------------------------------------------------------
# 财务数据查询工具（增强）
# ---------------------------------------------------------------------------


async def _compute_net_worth() -> str:
    """计算用户当前净值（确定性的，不依赖 LLM）。"""
    from .calculations.net_worth import calculate_net_worth

    positions = await db.list_positions()
    debts = await db.list_debts()
    snap = calculate_net_worth(positions=positions, debts=debts)
    return json.dumps({
        "date": str(snap.date),
        "total_assets": snap.total_assets,
        "total_liabilities": snap.total_liabilities,
        "net_worth": snap.net_worth,
        "asset_breakdown": snap.asset_breakdown,
        "liability_breakdown": snap.liability_breakdown,
    }, ensure_ascii=False)


async def _compute_financial_health() -> str:
    """计算财务健康评分（五维度 0-100）。"""
    from .calculations.health import HealthInputs, calculate_health_score

    # 从 DB 拿数据
    positions = await db.list_positions()
    txs = await db.list_transactions()
    debts = await db.list_debts()
    settings = await db.get_settings()

    # 计算月度收入 / 支出
    monthly_income = 0.0
    monthly_expense = 0.0
    now = datetime.now()
    month_prefix = now.strftime("%Y-%m")
    for t in txs:
        if t.get("date", "").startswith(month_prefix):
            amt = float(t.get("amount", 0))
            if amt > 0:
                monthly_income += amt
            else:
                monthly_expense += abs(amt)

    # 月度负债还款
    monthly_debt = sum(float(d.get("monthly", 0) or 0) for d in debts)

    # 现金
    cash = sum(
        float(p.get("last", 0)) * float(p.get("shares", 0))
        for p in positions if p.get("kind") == "现金"
    )

    inputs = HealthInputs(
        monthly_income=monthly_income,
        monthly_expense=monthly_expense,
        monthly_debt_payment=monthly_debt,
        cash_balance=cash,
        essential_monthly_expense=monthly_expense or 1.0,
        emergency_target_months=float(settings.get("emergency_target_months", 6) or 6),
        positions=[{"name": p.get("name", ""), "kind": p.get("kind", ""),
                     "market_value": float(p.get("last", 0)) * float(p.get("shares", 0))}
                    for p in positions],
    )
    score = calculate_health_score(inputs)
    return json.dumps({
        "score": score.score,
        "grade": score.grade,
        "breakdown": score.breakdown,
    }, ensure_ascii=False)


async def _compute_returns(months: int = 6) -> str:
    """计算收益率（简单收益率从持仓现值 vs 成本）。"""
    from .calculations.returns import calculate_simple_return

    positions = await db.list_positions()

    # 非现金持仓总成本 / 总市值
    total_cost = 0.0
    total_value = 0.0
    for p in positions:
        if p.get("kind") == "现金":
            continue
        shares = float(p.get("shares", 0))
        cost = float(p.get("cost", 0))
        last = float(p.get("last", 0))
        total_cost += shares * cost
        total_value += shares * last

    pnl = total_value - total_cost
    pnl_pct = (pnl / total_cost * 100) if total_cost > 0 else 0.0

    # 简单收益率：用历史流水做粗略估算
    simple_return = 0.0
    if total_cost > 0:
        try:
            simple_return = calculate_simple_return(total_cost, total_value)
        except ValueError:
            simple_return = 0.0

    return json.dumps({
        "months": months,
        "total_cost": round(total_cost, 2),
        "total_market_value": round(total_value, 2),
        "unrealized_pnl": round(pnl, 2),
        "unrealized_pnl_pct": round(pnl_pct, 2),
        "simple_return": round(simple_return, 6),
    }, ensure_ascii=False)


async def _compute_goal_progress() -> str:
    """查询所有财务目标的进度（on_track/逾期/完成）。"""
    from .calculations.goals import calculate_goal_progress

    goals = await db.list_goals()
    positions = await db.list_positions()
    txs = await db.list_transactions()
    progress = calculate_goal_progress(goals, positions, txs)
    return json.dumps([{
        "name": g.name,
        "target": g.target_amount,
        "current": g.current_amount,
        "progress_pct": g.progress_pct,
        "on_track": g.on_track,
        "months_remaining": g.months_remaining,
        "required_monthly": g.required_monthly,
    } for g in progress], ensure_ascii=False)


async def _import_transactions(source: str, csv_text: str) -> str:
    """批量导入交易：解析 CSV + 去重 + 写入 + 审计。"""
    from .csvimport import classify as _auto_classify
    from .import_parsers import get_parser

    parser = get_parser(source)
    result = parser.parse(csv_text)

    # 自动分类
    for t in result.transactions:
        if t.category in ("", "其他", "未分类"):
            t.category = _auto_classify(t.item) or "其他"

    # 去重
    existing = await db.list_transactions()
    existing_keys = {(r["date"], round(r["amount"], 2), r["item"]) for r in existing}
    unique_txs = []
    for t in result.transactions:
        key = (t.date, round(t.amount, 2), t.item)
        if key in existing_keys:
            continue
        existing_keys.add(key)
        unique_txs.append(t)

    # 写入
    imported = 0
    for t in unique_txs:
        await db.add_transaction(t.date, t.item, t.category, t.amount)
        imported += 1

    # 审计
    await record_provenance(
        action="import_transactions",
        entity_type="transaction",
        entity_id=f"batch:mcp:{imported}",
        before=None,
        after={"imported": imported, "source": source, "total_in_csv": len(result.transactions)},
        source="mcp",
    )

    return json.dumps({
        "imported": imported,
        "skipped": len(result.transactions) - imported,
        "errors": result.errors,
    }, ensure_ascii=False)


@mcp.tool()
async def get_net_worth() -> str:
    """查询用户当前净值（总资产 - 总负债）。返回资产/负债明细。"""
    return await _compute_net_worth()


@mcp.tool()
async def get_financial_health() -> str:
    """查询财务健康评分（0-100）及五维度拆解（储蓄率/DTI/应急金/集中度/投资多样性）。"""
    return await _compute_financial_health()


@mcp.tool()
async def get_returns(months: int = 6) -> str:
    """查询收益率数据：总成本、总市值、未实现盈亏、简单收益率。months 参数预留用于未来 XIRR 区间计算。"""
    return await _compute_returns(months)


@mcp.tool()
async def get_goal_progress() -> str:
    """查询所有财务目标进度：目标金额、已存金额、进度百分比、是否达标、所需月存。"""
    return await _compute_goal_progress()


@mcp.tool()
async def import_transactions(source: str, csv_text: str) -> str:
    """批量导入交易记录（source: generic/wechat/alipay，csv_text: CSV 文本内容）。自动去重、分类并记录审计日志。"""
    return await _import_transactions(source, csv_text)


@mcp.tool()
async def get_family_summary() -> str:
    """查询家庭整体汇总（总收入/总支出/各成员占比/未结清借贷）"""
    try:
        summary = await db.family_summary()
        return json.dumps(summary, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


@mcp.tool()
async def get_provenance(entity_type: str = "", entity_id: str = "", limit: int = 20) -> str:
    """查询操作审计日志（按实体类型/ID 过滤）。返回最近的操作记录（时间/动作/来源/前后快照）。"""
    from .provenance import get_provenances as _get_prov
    rows = await _get_prov(
        entity_type=entity_type or None,
        entity_id=entity_id or None,
        limit=min(limit, 200),
    )
    return json.dumps({"count": len(rows), "provenances": rows}, ensure_ascii=False)




# ---------------------------------------------------------------------------
# 参数 schema 对齐（M2.1）：MCP 工具的实际入参定义来自 tool_schemas.py
# ---------------------------------------------------------------------------
#
# 改造前每个 MCP 工具用手写函数签名声明参数，与 tools.py 的 JSON Schema 各自
# 维护同一份额外真相，已经漂移（MCP 的 record_position 多 industry、
# trigger_morning_report/backup_now 多 lang、get_lessons 与 set_setting 缺失）。
# 现在统一在注册后把参数 schema 覆盖为共享真源的产物：
# - 两侧参数名/类型/必填/说明完全一致，改一处即两侧同步
# - 函数签名保持原样（fastmcp 需要它做参数绑定），仅对外暴露的 schema 换源


def _apply_shared_schemas() -> list[str]:
    """把已注册 MCP 工具的参数 schema 覆盖为共享真源；返回未能对齐的工具名。

    只覆盖"共享真源里有定义"的工具；返回缺失清单让调用方可观测——
    新增 MCP 工具时若忘记在 tool_schemas.py 里登记，这里会明确报出来。
    """
    from . import tool_schemas as ts

    manager = getattr(mcp, "_tool_manager", None)
    if manager is None:  # pragma: no cover — 假 MCP（fastmcp 不可用）
        return []
    registered: dict[str, Any] = getattr(manager, "_tools", {}) or {}
    missing: list[str] = []
    for name, tool in registered.items():
        try:
            tool.parameters = ts.input_schema(name)
        except KeyError:
            missing.append(name)
    if missing:
        log.warning(
            "mcp.schema_missing: 以下工具未在 tool_schemas.py 登记入参模型: %s",
            ", ".join(sorted(missing)),
        )
    return missing


# ---------------------------------------------------------------------------
# 集成入口：挂载到 FastAPI 应用
# ---------------------------------------------------------------------------


def build_asgi() -> tuple[Any, Any] | None:
    """构建 MCP 的 ASGI 子应用，返回 (streamable_app, sse_app)。

    必须由调用方在创建父 app **之前**调用，并把 streamable_app.lifespan
    接进父 app —— Streamable HTTP 的 session manager 在 lifespan 里启动
    task group，不接会报 "Task group is not initialized"（实测）。
    sse_app 可能为 None（旧版 fastmcp 无 create_sse_app）。
    """
    if not MCP_AVAILABLE:
        return None

    _apply_shared_schemas()

    # 传输层：**Streamable HTTP 为默认**，SSE 保留一个版本期（M2.2）。
    #
    # 为什么换默认：MCP 规范 2025-03 起用 Streamable HTTP 取代 HTTP+SSE。
    # SSE 需要两条长连接（/sse 收 + /messages/ 发），在反向代理与移动网络下
    # 容易断流；Streamable HTTP 单端点、按需升流，是当前官方推荐形态。
    #
    # 兼容策略：已接入的客户端仍指向 /mcp/sse + /mcp/messages/，因此两条路径
    # 并存挂载。SSE 的移除安排在下一个大版本，届时在 CHANGELOG 明示。
    from fastmcp.server.http import create_streamable_http_app

    # 内部路由保留 /mcp：下面用「精确路径挂载」把 /mcp 与 /mcp/ 都直接交给它，
    # 不经过 Starlette 的斜杠重定向（307 会让不跟随重定向的 MCP 客户端失败）。
    streamable = create_streamable_http_app(server=mcp, streamable_http_path="/mcp")
    sse = None
    try:
        from fastmcp.server.http import create_sse_app

        sse = create_sse_app(server=mcp, message_path="/messages/", sse_path="/sse")
    except ImportError:  # pragma: no cover — 仅旧版 fastmcp 走到
        log.warning("mcp.sse_unavailable: 当前 fastmcp 版本不提供 create_sse_app")
    return streamable, sse


class _DynamicMcp:
    """动态转发到"当前" MCP 子应用。

    为什么需要它：session manager 每个实例只能 run 一次（run() 不可重入），
    而父 app 的 lifespan 可能被多次进入（测试用 TestClient、热重载、嵌入式
    多实例）。若挂载时把子应用写死，lifespan 里就得复用同一实例 → 第二次
    启动直接抛 "can only be called once per instance"；若 lifespan 里重建，
    挂载的路由又指向旧实例 → session manager 从未启动，端点 500。

    解法：挂一个转发器，请求到达时读取 holder 里的当前实例。lifespan 负责
    写入新实例，两者永远指同一个对象。
    """

    def __init__(self, holder: dict[str, Any]) -> None:
        self._holder = holder

    async def __call__(self, scope, receive, send) -> None:
        built = self._holder.get("built")
        target = built[0] if built else None
        if target is None:  # pragma: no cover — lifespan 未跑或构建失败
            from starlette.responses import JSONResponse

            await JSONResponse({"error": "MCP 未就绪"}, status_code=503)(scope, receive, send)
            return
        await target(scope, receive, send)


class _DynamicSse(_DynamicMcp):
    """同上，转发到 SSE 子应用（holder 里的第 2 项）。"""

    async def __call__(self, scope, receive, send) -> None:
        built = self._holder.get("built")
        target = built[1] if built else None
        if target is None:  # pragma: no cover — 旧版 fastmcp 无 SSE
            from starlette.responses import JSONResponse

            await JSONResponse({"error": "MCP SSE 不可用"}, status_code=503)(scope, receive, send)
            return
        await target(scope, receive, send)


class _ExactPathRoute(BaseRoute):
    """只匹配精确路径（含可选尾斜杠）并把原始 scope 交给子应用。

    为什么不用 Mount：Starlette 对 `Mount("/mcp")` 的精确路径 `/mcp` 会先做
    307 重定向到 `/mcp/`，而 MCP 客户端（含官方 SDK）默认不跟随重定向，
    表现为"连不上"。这里直接匹配、不改写路径，`/mcp` 与 `/mcp/` 都直达子应用。
    不匹配的路径返回 Match.NONE，后续静态托管等路由照常生效。
    """

    def __init__(self, path: str, app: Any) -> None:
        self.path = path
        self.app = app

    def matches(self, scope) -> tuple[Any, dict[str, Any]]:
        from starlette.routing import Match

        if scope["type"] != "http":
            return Match.NONE, {}
        raw = scope.get("path", "")
        if raw in (self.path, self.path + "/"):
            return Match.FULL, scope
        return Match.NONE, {}

    async def handle(self, scope, receive, send) -> None:
        await self.app(scope, receive, send)

    async def __call__(self, scope, receive, send) -> None:
        await self.handle(scope, receive, send)


def mount_to_app(app: Any, holder: dict[str, Any] | None = None) -> None:
    """把 MCP 子应用挂到 FastAPI app（/mcp 为 Streamable HTTP，/mcp-sse 为 SSE）。

    holder 是可变容器 {"built": (streamable, sse) | None}，由父 app 的 lifespan
    负责写入。不传则内部构建一次并写死（无 lifespan 接入，Streamable HTTP
    不可用，仅测试/特殊场景使用）。
    """
    if not MCP_AVAILABLE:
        log.info("mcp.skipped: fastmcp unavailable, not mounting")
        return

    if holder is None:
        built = build_asgi()
        if built is None:
            return
        holder = {"built": built}
    streamable = _DynamicMcp(holder)

    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    # /mcp 走 app.mount 会绕过主 app 的 @app.middleware("http") 中间件链，
    # 所以这里复用主 app 的同一套闸（口令 + 多用户 JWT fail-closed + Host/Origin
    # 白名单），否则就会出现"主站有防护、MCP 侧裸奔"的第二条信任边界。
    from .middleware import auth_gate, host_guard_check

    class _McpAuthGuard(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            gate = await auth_gate(request)
            if isinstance(gate, JSONResponse):
                return gate
            denied = host_guard_check(request)
            if denied is not None:
                return JSONResponse({"error": denied}, status_code=403)
            return await call_next(request)

    # 路径布局：
    #   /mcp                 Streamable HTTP（默认，MCP 规范推荐；无斜杠即用）
    #   /mcp-sse/sse         SSE 端点（旧客户端兼容，保留一个版本期）
    #   /mcp-sse/messages/   SSE 上行端点（仅 POST）
    #
    # 绝不挂 Mount("/")：根挂载会拦截所有未匹配请求（含前端静态资源），
    # 导致单端口部署时首页 404。streamable 子应用的内部路由就是 "/mcp"，
    # 因此用精确路径路由直接转发原始 scope（/mcp 与 /mcp/ 都命中，无 307）。
    sse_dynamic = _DynamicSse(holder)
    app.mount("/mcp-sse", _McpAuthGuard(sse_dynamic))
    app.router.routes.append(_ExactPathRoute("/mcp", _McpAuthGuard(streamable)))
    log.info("mcp.transport: streamable-http at /mcp, sse at /mcp-sse/sse")


async def startup() -> None:
    """MCP Server 启动时检查 DB 可用性。"""
    try:
        await db.fetch_all("SELECT 1")
    except Exception:
        pass  # DB 未就绪时 MCP 工具会在调用时返回错误


if __name__ == "__main__":
    """独立运行 MCP Server（stdio transport，供 Claude Desktop 等接入）。"""
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "stdio":
        asyncio.run(mcp.run_async(transport="stdio"))
    else:
        asyncio.run(mcp.run_async(transport="streamable-http", host="0.0.0.0", port=8765))

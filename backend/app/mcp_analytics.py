"""MCP 净值/健康度/收益/目标/导入/家庭/溯源 的净额计算与包装器。

从 mcp_server.py 拆出，import 即用 @_tool() 注册；mcp_server 末尾再导入本模块，
既触发注册也保留原有同名属性。
"""

from __future__ import annotations

import json

from . import db
from .logging_utils import get_logger
from .mcp_server import _tool
from .provenance import record_provenance

log = get_logger(__name__)

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
    """财务健康评分：**复用 analysis.health_check 的同一实现**。

    历史问题：这里曾用 calculations.calculate_health_score（连续打分），
    而 REST /api/calculations/health、/api/health-check 与体检页用
    analysis.health_check（定性折算）。同一份数据 MCP 报 54/D、界面报 83/B，
    AI 又会把 MCP 的数字当事实复述给用户——同一个产品给出两套结论。

    现在只有一条口径：进 analysis，出什么就报什么。
    """
    from . import analysis, quotes

    positions = await db.list_positions()
    txns = await db.list_transactions()
    debts = await db.list_debts()
    subs = await db.list_subscriptions()
    settings = await db.get_settings()

    try:
        live = await quotes.live_quotes(positions)
    except Exception:  # noqa: BLE001 — 行情失败退回快照价，评分仍可给
        live = {p["symbol"]: float(p.get("last", 0)) for p in positions}

    market = analysis.market_view(positions, live)
    ledger = analysis.ledger_view(txns, subs, debts, settings, positions, live)
    flags = analysis.risk_checks(market, ledger, "zh")
    report = analysis.health_check(market, ledger, flags, await db.list_goals(), "zh")

    return json.dumps(
        {
            "score": report.get("score", 0),
            "grade": report.get("grade", "-"),
            "summary": report.get("summary", ""),
            "dimensions": report.get("dimensions", []),
            "source": "analysis.health_check",
            "note": "与 /api/calculations/health、体检页同一口径",
        },
        ensure_ascii=False,
    )


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


@_tool()
async def get_net_worth() -> str:
    """查询用户当前净值（总资产 - 总负债）。返回资产/负债明细。"""
    return await _compute_net_worth()


@_tool()
async def get_financial_health() -> str:
    """查询财务健康评分（0-100）及五维度拆解（储蓄率/DTI/应急金/集中度/投资多样性）。"""
    return await _compute_financial_health()


@_tool()
async def get_returns(months: int = 6) -> str:
    """查询收益率数据：总成本、总市值、未实现盈亏、简单收益率。months 参数预留用于未来 XIRR 区间计算。"""
    return await _compute_returns(months)


@_tool()
async def get_goal_progress() -> str:
    """查询所有财务目标进度：目标金额、已存金额、进度百分比、是否达标、所需月存。"""
    return await _compute_goal_progress()


@_tool()
async def import_transactions(source: str, csv_text: str) -> str:
    """批量导入交易记录（source: generic/wechat/alipay，csv_text: CSV 文本内容）。自动去重、分类并记录审计日志。"""
    return await _import_transactions(source, csv_text)


@_tool()
async def get_family_summary() -> str:
    """查询家庭整体汇总（总收入/总支出/各成员占比/未结清借贷）"""
    try:
        summary = await db.family_summary()
        return json.dumps(summary, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


@_tool()
async def get_provenance(entity_type: str = "", entity_id: str = "", limit: int = 20) -> str:
    """查询操作审计日志（按实体类型/ID 过滤）。返回最近的操作记录（时间/动作/来源/前后快照）。"""
    from .provenance import get_provenances as _get_prov
    rows = await _get_prov(
        entity_type=entity_type or None,
        entity_id=entity_id or None,
        limit=min(limit, 200),
    )
    return json.dumps({"count": len(rows), "provenances": rows}, ensure_ascii=False)

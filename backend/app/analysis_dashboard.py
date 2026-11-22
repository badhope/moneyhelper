"""仪表盘快照：行情 + 账本取数、风控、动作建议，带 10 秒短 TTL 缓存。

缓存与前端 4 个组件 + 对话 + MCP 共享同一份快照对象，故 TTL 与 cache 实例
必须与本模块同生，不能留在门面。
"""

from __future__ import annotations

import asyncio
from typing import Any

from cachetools import TTLCache

from . import db, quotes
from .analysis_health import goal_progress
from .analysis_rules import risk_checks
from .analysis_views import _month_prefix, ledger_view, market_view
from .calculations import decisions as _decisions

_DASHBOARD_TTL_SECONDS = 10.0
_dashboard_cache: TTLCache[str, dict[str, Any]] = TTLCache(
    maxsize=64, ttl=_DASHBOARD_TTL_SECONDS
)


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
            "demo": settings.get("data_note", "") == "demo",
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

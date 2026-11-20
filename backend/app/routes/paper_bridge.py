"""团队模拟盘 · 桥接域：股票账户桥接计划/跟踪与跨账户概览。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..auth import get_current_user
from ..calculations.paper import estimate

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post("/api/paper/bridge/plan")
async def bridge_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """由回测结果生成「转模拟盘」计划（不执行，只描述）。

    请求：{symbol, capital, strategy?, fast?, slow?, invest_amount?, freq_days?}
    回测用真实日线（quotes.kline），结果直接交给 bridge.plan_from_backtest。
    """
    from .. import quotes
    from ..calculations.backtest import run_backtest, series_from_points
    from ..calculations.bridge import plan_from_backtest

    symbol = str(payload.get("symbol") or "").strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol 必填")
    try:
        capital = max(1000.0, float(payload.get("capital") or 100000.0))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="capital 非法") from exc
    strategy = str(payload.get("strategy") or "ma_cross")

    data = await quotes.kline(symbol, "daily", 750)
    if not data or not data.get("points"):
        return {"ok": False, "error": f"无法获取 {symbol} 的行情（可能非 A 股/ETF 或行情源不可用）"}
    points = data["points"]
    closes, dates = series_from_points(points)
    if len(closes) < 60:
        return {"ok": False, "error": f"{symbol} 历史数据不足 60 根，无法回测"}

    try:
        fast = max(2, min(int(payload.get("fast") or 5), 60))
        slow = max(5, min(int(payload.get("slow") or 20), 120))
    except (TypeError, ValueError):
        fast, slow = 5, 20
    if strategy == "ma_cross" and fast >= slow:
        # 快线周期不小于慢线时，"多头排列"判据反向，结果会是一份看起来正常
        # 但语义相反的报告；宁可明确拒绝。
        return {"ok": False, "error": "fast 必须小于 slow"}
    result = (
        run_backtest(closes, dates, "ma_cross", fast=fast, slow=slow)
        if strategy == "ma_cross"
        else run_backtest(closes, dates, "dca")
    )
    if result is None:
        return {"ok": False, "error": f"{symbol} 回测无结果"}

    plan = plan_from_backtest(result, symbol, capital, str(payload.get("lang") or "zh"))
    plan["price_points"] = len(closes)
    return plan


@router.post("/api/paper/bridge/track")
async def bridge_track(payload: dict[str, Any]) -> dict[str, Any]:
    """样本外跟踪：对比某模拟盘账户的实际净值与同策略回测预期曲线。

    请求：{account_id, symbol, strategy?, ...}
    模拟盘曲线取该账户快照（equity）；回测曲线取同 symbol 同策略重跑。
    两条曲线按较短长度对齐（重叠区间），偏差口径见 calculations/bridge。
    """
    from .. import quotes
    from ..calculations.backtest import run_backtest, series_from_points
    from ..calculations.bridge import tracking_report

    aid = str(payload.get("account_id") or "").strip()
    symbol = str(payload.get("symbol") or "").strip()
    if not aid or not symbol:
        raise HTTPException(status_code=400, detail="account_id 与 symbol 必填")
    acc = await db.get_account(aid)
    if not acc:
        raise HTTPException(status_code=404, detail="账户不存在")

    snapshots = await db.list_snapshots(aid)
    paper_curve = [float(s["equity"]) for s in snapshots if s.get("equity") is not None]
    if len(paper_curve) < 2:
        return {"ok": False, "error": "模拟盘快照不足 2 个，无法跟踪（先交易并生成快照）"}

    data = await quotes.kline(symbol, "daily", 750)
    if not data or not data.get("points"):
        return {"ok": False, "error": f"无法获取 {symbol} 行情"}
    points = data["points"]
    closes, dates = series_from_points(points)
    if len(closes) < 60:
        return {"ok": False, "error": f"{symbol} 历史数据不足"}

    strategy = str(payload.get("strategy") or "ma_cross")
    result = (
        run_backtest(closes, dates, "ma_cross")
        if strategy == "ma_cross"
        else run_backtest(closes, dates, "dca")
    )
    if result is None:
        return {"ok": False, "error": "回测无结果"}

    bt_curve = list((result.get("curve") or {}).get("strategy") or [])
    report = tracking_report(bt_curve, paper_curve, float(acc["initial_cash"]),
                             str(payload.get("lang") or "zh"))
    report["account_id"] = aid
    report["symbol"] = symbol
    report["backtest_return_pct"] = result.get("total_return_pct")
    return report


@router.get("/api/paper/bridge/accounts-overview")
async def accounts_overview(lang: str = "zh") -> dict[str, Any]:
    """多账户合并视图：本地账本 + 模拟盘 + 实盘。

    本地口径复用 calculate_net_worth（与 /api/calculations/net-worth 同源），
    不自己拼「市值+现金-负债」——否则同一屏又会出现两个净资产。
    实盘依赖 broker_live（可能未配置），失败时该来源为空，其余口径仍可用。
    """
    from .. import quotes
    from ..calculations.accounts import merge_accounts
    from ..calculations.net_worth import calculate_net_worth

    positions = await db.list_positions()
    debts = await db.list_debts()
    subs = await db.list_subscriptions()
    try:
        live = await quotes.live_quotes(positions)
    except Exception:  # noqa: BLE001 — 行情失败退回快照价
        live = {}
    priced = [{**p, "last": float(live.get(p["symbol"], p.get(p.get("symbol"), p.get("last", 0))))}
              if p.get("symbol") else p for p in positions]
    snapshot = calculate_net_worth(priced, debts=debts, subscriptions=subs)

    paper_items: list[dict[str, Any]] = []
    for acc in await db.list_accounts():
        trades = await db.get_trades(acc["account_id"])
        est = estimate(acc["initial_cash"], trades)
        paper_items.append({
            "account_id": acc["account_id"],
            "name": acc["name"],
            "equity": est["equity"],
            "initial_cash": acc["initial_cash"],
        })

    broker_items: list[dict[str, Any]] = []
    try:
        from .. import broker_live

        for acc in await broker_live.list_accounts():
            broker_items.append({
                "account_id": str(acc.get("account_id") or ""),
                "label": str(acc.get("label") or ""),
                "net_liquidation": float(acc.get("net_liquidation") or 0),
                "currency": str(acc.get("currency") or "CNY"),
            })
    except Exception:  # noqa: BLE001 — 实盘未配置/依赖缺失视为无实盘账户
        broker_items = []

    # 本地口径拆成「市值 + 现金 − 负债」以供明细展示；
    # 合计仍以 snapshot 为准（避免重复计算订阅等已在口径内的项）。
    local_market = float(snapshot.total_assets)
    local_net = float(snapshot.net_worth)
    liabilities = float(snapshot.total_liabilities)
    return merge_accounts(
        local_market_value=local_market,
        local_cash=0.0,
        local_debt=liabilities,
        paper_accounts=paper_items,
        broker_accounts=broker_items,
        lang=lang,
        local_net_override=local_net,
    )

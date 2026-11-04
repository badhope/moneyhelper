"""团队模拟盘路由（v4.2）：开户 / 下单 / 估值 / 排行 / 净值曲线。

设计要点：
- 事件溯源：持仓与现金由交易记录重放（calculations/paper.py），落库只有三表。
- 估值默认用「最近成交价」（本地确定性、可测试）；下单时前端填现价实现近似实时。
- 每笔交易后自动按日存档净值快照，GET 详情时补今日点。
- 所有校验（整手/现金/持仓）在引擎层完成，路由只做参数清洗。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..auth import get_current_user
from ..calculations.paper import (
    build_equity_curve,
    estimate,
    fee_for,
    ranking,
    team_summary,
    validate_trade,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/api/paper/accounts")
async def paper_accounts() -> dict[str, Any]:
    """团队账户列表：开户信息 + 估值 + 排行 + 团队摘要。"""
    accounts = await db.list_accounts()
    enriched: list[dict[str, Any]] = []
    for acc in accounts:
        trades = await db.get_trades(acc["account_id"])
        est = estimate(acc["initial_cash"], trades)
        enriched.append(
            {
                "account_id": acc["account_id"],
                "name": acc["name"],
                "initial_cash": acc["initial_cash"],
                "created_at": acc["created_at"],
                "trade_count": len(trades),
                **est,
            }
        )
    ranked = ranking(enriched)
    return {
        "items": ranked,
        "summary": team_summary(ranked),
        "valuation_source": "last_trade",
    }


@router.post("/api/paper/accounts")
async def paper_open(payload: dict[str, Any]) -> dict[str, Any]:
    """开户：name + initial_cash。"""
    try:
        acc = await db.open_account(
            str(payload.get("name") or "模拟账户"),
            float(payload.get("initial_cash") or 100000),
        )
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"account": acc}


@router.delete("/api/paper/accounts/{aid}")
async def paper_delete(aid: str) -> dict[str, Any]:
    """删除账户（含交易与快照）。"""
    ok = await db.delete_account(aid)
    if not ok:
        raise HTTPException(status_code=404, detail="账户不存在")
    return {"deleted": aid}


@router.get("/api/paper/accounts/{aid}")
async def paper_detail(aid: str) -> dict[str, Any]:
    """账户详情：估值 + 净值曲线 + 交易记录。"""
    acc = await db.get_account(aid)
    if not acc:
        raise HTTPException(status_code=404, detail="账户不存在")
    trades = await db.get_trades(aid)
    est = estimate(acc["initial_cash"], trades)
    # 补今日快照（估值变化后）
    await db.save_snapshot(aid, est["equity"], est["cash"], est["market_value"])
    snaps = await db.list_snapshots(aid)
    curve = build_equity_curve(snaps, acc["initial_cash"])
    return {
        "account": {
            "account_id": acc["account_id"],
            "name": acc["name"],
            "initial_cash": acc["initial_cash"],
            "created_at": acc["created_at"],
            "trade_count": len(trades),
            **est,
        },
        "curve": curve,
        "trades": list(reversed(trades))[:60],  # 最新在前，最多 60 条
    }


@router.post("/api/paper/accounts/{aid}/trades")
async def paper_trade(aid: str, payload: dict[str, Any]) -> dict[str, Any]:
    """下单：symbol + side(buy/sell) + price + shares（+name 可选）。"""
    acc = await db.get_account(aid)
    if not acc:
        raise HTTPException(status_code=404, detail="账户不存在")

    symbol = str(payload.get("symbol") or "").strip().upper()
    if not symbol.isdigit() or len(symbol) != 6:
        raise HTTPException(status_code=400, detail="symbol must be a 6-digit A-share code")
    side = str(payload.get("side") or "").strip()
    try:
        price = float(payload.get("price") or 0)
        shares = float(payload.get("shares") or 0)
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail="price/shares 非法") from e

    amount = price * shares
    fee = fee_for(side, amount)

    # 读-校验-写必须在同一把写锁内完成：否则两个并发买入都能通过现金校验，
    # 落库后现金为负、交易流水与估值不一致（排行榜/净值曲线全部失真）。
    # 事件溯源模型的正确用法是「持锁重放→校验→插入」，而不是先读后判。
    from ..db._core import get_write_lock

    async with get_write_lock():
        trades = await db.get_trades(aid)
        err = validate_trade(acc["initial_cash"], trades, side, symbol, price, shares)
        if err:
            raise HTTPException(status_code=400, detail=err)
        trade = await db.add_trade(
            aid,
            {
                "symbol": symbol,
                "name": str(payload.get("name") or ""),
                "side": side,
                "price": price,
                "shares": shares,
                "fee": fee,
            },
        )
        est = estimate(acc["initial_cash"], await db.get_trades(aid))
        await db.save_snapshot(aid, est["equity"], est["cash"], est["market_value"])
    return {"trade": trade, "estimate": est}


@router.post("/api/paper/accounts/{aid}/snapshot")
async def paper_snapshot(aid: str) -> dict[str, Any]:
    """手动存档净值快照（幂等：同日覆盖）。"""
    acc = await db.get_account(aid)
    if not acc:
        raise HTTPException(status_code=404, detail="账户不存在")
    trades = await db.get_trades(aid)
    est = estimate(acc["initial_cash"], trades)
    await db.save_snapshot(aid, est["equity"], est["cash"], est["market_value"])
    return {"snapshotted": True, "equity": est["equity"]}


# ---------------------------------------------------------------------------
# 回测 → 模拟盘桥接（样本外验证闭环）
# ---------------------------------------------------------------------------


@router.post("/api/paper/bridge/plan")
async def bridge_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """由回测结果生成「转模拟盘」计划（不执行，只描述）。

    请求：{symbol, capital, strategy?, fast?, slow?, invest_amount?, freq_days?}
    回测用真实日线（quotes.kline），结果直接交给 bridge.plan_from_backtest。
    """
    from .. import quotes
    from ..calculations.backtest import run_backtest
    from ..calculations.bridge import plan_from_backtest

    symbol = str(payload.get("symbol") or "").strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol 必填")
    try:
        capital = max(1000.0, float(payload.get("capital") or 100000.0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="capital 非法")
    strategy = str(payload.get("strategy") or "ma_cross")

    data = await quotes.kline(symbol, "daily", 750)
    if not data or not data.get("points"):
        return {"ok": False, "error": f"无法获取 {symbol} 的行情（可能非 A 股/ETF 或行情源不可用）"}
    points = data["points"]
    closes = [float(p["close"]) for p in points if p.get("close") is not None]
    dates = [p.get("date", "") for p in points]
    if len(closes) < 60:
        return {"ok": False, "error": f"{symbol} 历史数据不足 60 根，无法回测"}

    try:
        fast = max(2, min(int(payload.get("fast") or 5), 60))
        slow = max(5, min(int(payload.get("slow") or 20), 120))
    except (TypeError, ValueError):
        fast, slow = 5, 20
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
    from ..calculations.backtest import run_backtest
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
    closes = [float(p["close"]) for p in points if p.get("close") is not None]
    dates = [p.get("date", "") for p in points]
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

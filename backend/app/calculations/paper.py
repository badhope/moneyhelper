"""团队模拟盘引擎（v4.2）：事件溯源式纯函数计算，团队炒股核心。

设计：
- **事件溯源**：账户只有开户参数（initial_cash）+ 交易记录（trades）。
  持仓、现金、成本、估值全部从交易记录重放得到 —— 无状态漂移、可审计、
  可单测；删除/回滚一笔交易即回到对应时点。
- 全部为纯函数（无 I/O），确定性可复现。

口径（A 股）：
- 买入按 100 股整手成交；卖出可零股。
- 佣金双边 0.025%（最低 5 元）；卖出加印花税 0.05%（2023-08 后减半口径）。
- 加权平均成本（买入合并摊薄，卖出不变）。
- 收益率 = (equity - initial_cash) / initial_cash；年化按持仓自然日数简单折算。

本模块输出为模拟盘统计，**不构成投资建议**。
"""

from __future__ import annotations

import math
from typing import Any

MIN_LOT = 100
COMMISSION_RATE = 0.00025
COMMISSION_MIN = 5.0
STAMP_TAX_RATE = 0.0005  # 卖出印花税（2023-08 减半后 0.05%）

# 允许交易的边
SIDES = ("buy", "sell")


def round_lots(shares: float) -> float:
    """买入整手：向下取整到 100 股。shares<=0 返回 0。"""
    if shares <= 0:
        return 0.0
    return math.floor(shares / MIN_LOT) * MIN_LOT


def fee_for(side: str, amount: float) -> float:
    """单边手续费：佣金 max(5, 金额×0.025%)；卖出另加印花税 0.05%。"""
    if side not in SIDES or amount <= 0:
        return 0.0
    commission = max(COMMISSION_MIN, amount * COMMISSION_RATE)
    if side == "sell":
        commission += amount * STAMP_TAX_RATE
    return round(commission, 2)


def _rebuild(
    initial_cash: float, trades: list[dict[str, Any]]
) -> tuple[float, dict[str, dict[str, float]]]:
    """重放交易：返回 (现金, 持仓 {symbol: {shares, cost}})。

    cost 为加权平均成本；买入合并、卖出按比例不变。资金不足/卖出超仓由调用方校验。
    """
    cash = float(initial_cash)
    holdings: dict[str, dict[str, float]] = {}
    for t in trades:
        sym = str(t["symbol"]).upper()
        side = t["side"]
        price = float(t["price"])
        shares = float(t["shares"])
        amount = price * shares
        fee = float(t.get("fee") or 0.0)
        h = holdings.setdefault(sym, {"shares": 0.0, "cost": 0.0})
        if side == "buy":
            total_cost = h["cost"] * h["shares"] + amount + fee
            h["shares"] += shares
            h["cost"] = total_cost / h["shares"] if h["shares"] > 0 else 0.0
            cash -= amount + fee
        else:
            cash += amount - fee
            h["shares"] -= shares
            if h["shares"] <= 0:
                del holdings[sym]
    return round(cash, 2), holdings


def estimate(
    initial_cash: float,
    trades: list[dict[str, Any]],
    prices: dict[str, float] | None = None,
) -> dict[str, Any]:
    """账户估值：现金、持仓、市值、净值、收益率。

    prices：{symbol: 最新价}；缺 symbol 的持仓按最后一次成交价计（标注 stale=true）。
    """
    cash, holdings = _rebuild(initial_cash, trades)
    prices = prices or {}
    last_prices: dict[str, float] = {}
    for t in reversed(trades):
        sym = str(t["symbol"]).upper()
        last_prices.setdefault(sym, float(t["price"]))

    market_value = 0.0
    positions: list[dict[str, Any]] = []
    stale = False
    for sym, h in holdings.items():
        px = prices.get(sym)
        if px is None:
            px = last_prices.get(sym, 0.0)
            stale = True
        mv = px * h["shares"]
        market_value += mv
        cost_total = h["cost"] * h["shares"]
        positions.append(
            {
                "symbol": sym,
                "shares": round(h["shares"], 4),
                "cost": round(h["cost"], 4),
                "last": round(px, 4),
                "market_value": round(mv, 2),
                "pnl": round(mv - cost_total, 2),
                "pnl_pct": round((mv / cost_total - 1.0) * 100.0, 2) if cost_total > 0 else None,
            }
        )
    positions.sort(key=lambda p: p["market_value"], reverse=True)
    equity = cash + market_value
    return {
        "cash": cash,
        "holdings": positions,
        "market_value": round(market_value, 2),
        "equity": round(equity, 2),
        "return_pct": round((equity / initial_cash - 1.0) * 100.0, 2) if initial_cash > 0 else 0.0,
        "total_pnl": round(equity - initial_cash, 2),
        "position_count": len(positions),
        "stale": stale,
    }


def validate_trade(
    initial_cash: float,
    trades: list[dict[str, Any]],
    side: str,
    symbol: str,
    price: float,
    shares: float,
) -> str | None:
    """下单前校验：返回错误信息或 None（合法）。

    - side ∈ buy/sell；price>0；shares>0
    - 买入：整手（round_lots == shares）且资金（含费）充足
    - 卖出：持仓充足
    """
    if side not in SIDES:
        return f"side 仅支持 {SIDES}"
    if price <= 0:
        return "price 必须 > 0"
    if shares <= 0:
        return "shares 必须 > 0"
    cash, holdings = _rebuild(initial_cash, trades)
    if side == "buy":
        lots = round_lots(shares)
        if lots != shares:
            return f"买入必须整手（100 股整数倍），当前 {shares}"
        amount = price * shares
        if amount + fee_for("buy", amount) > cash + 1e-6:
            return "现金不足"
    else:
        sym = symbol.upper()
        if sym not in holdings or holdings[sym]["shares"] + 1e-9 < shares:
            return "持仓不足"
    return None


def ranking(accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """团队排行：按收益率降序；收益率相同按净值降序。原地不改输入。"""
    return sorted(accounts, key=lambda a: (a["return_pct"], a["equity"]), reverse=True)


def team_summary(accounts: list[dict[str, Any]]) -> dict[str, Any]:
    """团队汇总：总资产、总收益、收益率（资金加权）、账户数。"""
    total_initial = sum(a["initial_cash"] for a in accounts)
    total_equity = sum(a["equity"] for a in accounts)
    total_pnl = total_equity - total_initial
    return {
        "account_count": len(accounts),
        "total_initial_cash": round(total_initial, 2),
        "total_equity": round(total_equity, 2),
        "total_pnl": round(total_pnl, 2),
        "return_pct": round((total_equity / total_initial - 1.0) * 100.0, 2) if total_initial > 0 else 0.0,
        "active_positions": sum(a["position_count"] for a in accounts),
    }


def build_equity_curve(snapshots: list[dict[str, Any]], initial_cash: float) -> dict[str, Any]:
    """净值曲线：按日期升序。返回 {dates, equity, bench}（bench 为 1.0 基准线）。

    snapshots: [{date, equity}]，需按 date 升序传入（由调用方排序）。
    """
    dates = [s["date"] for s in snapshots]
    equity = [round(s["equity"] / initial_cash, 4) for s in snapshots]
    return {"dates": dates, "equity": equity, "bench": [1.0] * len(dates)}

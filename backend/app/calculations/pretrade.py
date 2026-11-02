"""预交易风控：把「能不能下单」变成一组确定性检查，而不是让模型自己判断。

检查项（每项独立返回 ok/detail，全部通过才放行）：

1. **参数合法性**：代码 6 位、方向 buy/sell、价格 > 0、股数 > 0。
2. **整手规则**：A 股买入必须 100 股整数倍；卖出允许零股（清仓场景）。
3. **涨跌停约束**：主板 ±10%、创业板/科创板 ±20%、北交所 ±30%、ST ±5%；
   价格超出当日涨跌停区间直接拒绝（用昨收价计算，缺昨收则跳过并标注）。
4. **价格偏离**：委托价与最新价比，偏离超过阈值默认 3% 时告警（不阻断，防打错价）。
5. **资金/持仓**：买入校验现金（含费用），卖出校验可用股数。
6. **T+1**：当日买入的股份当日不可卖（用成交记录判断）。
7. **集中度**：买入后单一标的市值占比超过阈值（默认 30%）告警。
8. **单日限额**：当日累计委托金额超过用户设定的日限额时拒绝。
9. **重复单**：同标的、同方向、同价格、同数量在 60 秒内重复提交时拒绝。

结果结构：
    {"ok": bool, "blocking": [...], "warnings": [...], "checks": [{id, ok, level, detail}]}

level 语义：block=拒绝下单；warn=提示但可继续；info=通过记录。
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any

A_SHARE_LOT = 100
DEFAULT_DAILY_LIMIT = 200_000.0
DEFAULT_DEVIATION_PCT = 3.0
DEFAULT_CONCENTRATION_PCT = 30.0
DUPLICATE_WINDOW_SECONDS = 60

# 涨跌停幅度：按代码前缀判定板块
_LIMIT_RULES: tuple[tuple[str, float], ...] = (
    ("688", 0.20),  # 科创板
    ("689", 0.20),
    ("300", 0.20),  # 创业板
    ("301", 0.20),
    ("8", 0.30),    # 北交所
    ("4", 0.30),
    ("9", 0.30),
)


def price_limit(symbol: str, prev_close: float, is_st: bool = False) -> float:
    """返回该标的的涨跌停幅度（0.05/0.10/0.20/0.30）。"""
    if prev_close <= 0:
        return 0.10
    if is_st:
        return 0.05
    for prefix, pct in _LIMIT_RULES:
        if symbol.startswith(prefix):
            return pct
    return 0.10


def limit_prices(symbol: str, prev_close: float, is_st: bool = False) -> dict[str, float]:
    """计算涨停价/跌停价（A 股四舍五入到分）。"""
    pct = price_limit(symbol, prev_close, is_st)
    up = round(prev_close * (1 + pct) + 1e-9, 2)
    down = round(prev_close * (1 - pct) + 1e-9, 2)
    return {"up": up, "down": down, "pct": pct}


def _check(cid: str, ok: bool, level: str, detail: str) -> dict[str, Any]:
    return {"id": cid, "ok": ok, "level": level if not ok else "info", "detail": detail}


def pre_trade_check(
    *,
    symbol: str,
    side: str,
    price: float,
    shares: float,
    cash: float,
    holdings: dict[str, float],
    last_price: float | None = None,
    prev_close: float | None = None,
    is_st: bool = False,
    today_bought: float = 0.0,
    portfolio_value: float = 0.0,
    position_value: float = 0.0,
    daily_used_amount: float = 0.0,
    daily_limit: float = DEFAULT_DAILY_LIMIT,
    recent_orders: list[dict[str, Any]] | None = None,
    fee: float = 0.0,
    deviation_pct: float = DEFAULT_DEVIATION_PCT,
    concentration_pct: float = DEFAULT_CONCENTRATION_PCT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """执行全部预交易检查。

    holdings: {symbol: 可用股数}；today_bought: 当日已买入股数（T+1 判定用）；
    position_value: 该标的当前持仓市值；portfolio_value: 组合总市值（集中度分母）；
    recent_orders: [{symbol, side, price, shares, ts}]，用于重复单检测。
    """
    checks: list[dict[str, Any]] = []
    symbol = str(symbol or "").strip().upper()
    side = str(side or "").strip().lower()

    # 1. 参数
    param_ok = bool(re.fullmatch(r"\d{6}", symbol)) and side in ("buy", "sell") and price > 0 and shares > 0
    checks.append(
        _check(
            "params",
            param_ok,
            "block",
            f"代码 {symbol} / 方向 {side} / 价格 {price} / 数量 {shares}"
            if param_ok
            else "代码需为 6 位数字，方向为 buy/sell，价格与数量需大于 0",
        )
    )
    if not param_ok:
        return _pack(checks)

    # 2. 整手
    if side == "buy":
        lot_ok = abs(shares % A_SHARE_LOT) < 1e-9
        checks.append(
            _check("lot", lot_ok, "block", f"{shares:g} 股为整手" if lot_ok else f"买入必须是 {A_SHARE_LOT} 股整数倍，当前 {shares:g}")
        )
    else:
        checks.append(_check("lot", True, "info", "卖出允许零股"))

    # 3. 涨跌停
    if prev_close and prev_close > 0:
        lp = limit_prices(symbol, prev_close, is_st)
        in_range = lp["down"] - 1e-9 <= price <= lp["up"] + 1e-9
        checks.append(
            _check(
                "price_limit",
                in_range,
                "block",
                f"价格 {price} 在 [{lp['down']}, {lp['up']}] 区间内（涨跌幅限制 ±{lp['pct']:.0%}）"
                if in_range
                else f"价格 {price} 超出今日涨跌停区间 [{lp['down']}, {lp['up']}]（±{lp['pct']:.0%}）",
            )
        )
    else:
        checks.append(_check("price_limit", True, "info", "缺昨收价，跳过涨跌停校验"))

    # 4. 价格偏离
    if last_price and last_price > 0:
        dev = abs(price - last_price) / last_price * 100
        ok = dev <= deviation_pct
        checks.append(
            _check(
                "deviation",
                ok,
                "warn",
                f"委托价较最新价偏离 {dev:.2f}%（阈值 {deviation_pct:.1f}%）",
            )
        )
    else:
        checks.append(_check("deviation", True, "info", "缺最新价，跳过偏离校验"))

    # 5. 资金 / 持仓
    amount = round(price * shares, 2)
    if side == "buy":
        need = round(amount + fee, 2)
        enough = cash + 1e-9 >= need
        checks.append(
            _check("cash", enough, "block", f"需 {need:,.2f}（含费 {fee:,.2f}），可用 {cash:,.2f}" if not enough else f"资金充足（需 {need:,.2f}）")
        )
    else:
        held = float(holdings.get(symbol, 0.0))
        sellable = max(0.0, held - max(0.0, today_bought))
        enough = sellable + 1e-9 >= shares
        checks.append(
            _check(
                "holdings",
                enough,
                "block",
                f"可卖 {sellable:g} 股（持仓 {held:g}，当日买入 {today_bought:g} T+1 冻结），委托 {shares:g} 股"
                if not enough
                else f"可卖 {sellable:g} 股，足够",
            )
        )

    # 6. T+1（单列一条，便于前端解释）
    if side == "sell":
        t1_ok = today_bought <= 0
        checks.append(
            _check(
                "t_plus_1",
                t1_ok,
                "block" if today_bought >= shares else "warn",
                "当日无买入，可正常卖出" if t1_ok else f"当日买入 {today_bought:g} 股不可当日卖出（T+1）",
            )
        )
    else:
        checks.append(_check("t_plus_1", True, "info", "买入不受 T+1 限制，次日可卖"))

    # 7. 集中度
    if side == "buy" and portfolio_value > 0:
        after = (position_value + amount) / (portfolio_value + amount) * 100
        ok = after <= concentration_pct
        checks.append(
            _check(
                "concentration",
                ok,
                "warn",
                f"买入后该标的占比 {after:.1f}%（阈值 {concentration_pct:.0f}%）",
            )
        )
    else:
        checks.append(_check("concentration", True, "info", "卖出或组合为空，跳过集中度"))

    # 8. 单日限额
    if daily_limit > 0:
        after_used = daily_used_amount + amount
        ok = after_used <= daily_limit
        checks.append(
            _check(
                "daily_limit",
                ok,
                "block",
                f"今日累计委托 {after_used:,.2f} / 限额 {daily_limit:,.2f}",
            )
        )

    # 9. 重复单
    now = now or datetime.now()
    dup = False
    for order in recent_orders or []:
        try:
            ts = order.get("ts")
            when = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
            if (now - when).total_seconds() > DUPLICATE_WINDOW_SECONDS:
                continue
            if (
                str(order.get("symbol", "")).upper() == symbol
                and str(order.get("side", "")).lower() == side
                and abs(float(order.get("price", 0)) - price) < 1e-6
                and abs(float(order.get("shares", 0)) - shares) < 1e-6
            ):
                dup = True
                break
        except (TypeError, ValueError):
            continue
    checks.append(
        _check("duplicate", not dup, "block", "60 秒内存在相同委托，已拦截" if dup else "无重复委托")
    )

    return _pack(checks, amount=amount)


def _pack(checks: list[dict[str, Any]], amount: float = 0.0) -> dict[str, Any]:
    blocking = [c for c in checks if not c["ok"] and c["level"] == "block"]
    warnings = [c for c in checks if not c["ok"] and c["level"] == "warn"]
    return {
        "ok": not blocking,
        "amount": round(amount, 2),
        "blocking": blocking,
        "warnings": warnings,
        "checks": checks,
        "summary": "全部检查通过" if not blocking and not warnings else (
            f"{len(blocking)} 项拦截，{len(warnings)} 项告警" if blocking else f"{len(warnings)} 项告警"
        ),
    }


def daily_order_amount(orders: list[dict[str, Any]], today: date | None = None) -> float:
    """统计当日已委托金额（用于限额）。orders 需含 ts 与 price/shares。"""
    target = today or datetime.now().astimezone().date()
    total = 0.0
    for o in orders:
        try:
            ts = o.get("ts")
            when = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
        except (TypeError, ValueError):
            continue
        if when.date() != target:
            continue
        total += float(o.get("price") or 0) * float(o.get("shares") or 0)
    return round(total, 2)


def rebalance_orders(
    *,
    plan_items: list[dict[str, Any]],
    available_cash: float,
    min_order_amount: float = 1_000.0,
    lot: int = A_SHARE_LOT,
) -> dict[str, Any]:
    """把再平衡清单转成可执行委托：整手取整、按金额排序、资金不足时给出缺口。

    plan_items: [{symbol, name, action(buy/sell/hold), amount, price}]（来自 compute_rebalance）
    先卖后买：卖出腾出的资金可用于买入（A 股 T+1 下当日卖出资金可用，这里按"可用"处理）。
    """
    sells: list[dict[str, Any]] = []
    buys: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in plan_items:
        action = str(item.get("action") or "").lower()
        price = float(item.get("price") or 0)
        amount = abs(float(item.get("amount") or 0))
        symbol = str(item.get("symbol") or "")
        name = str(item.get("name") or "")
        if action not in ("buy", "sell") or price <= 0 or amount < min_order_amount:
            continue
        if action == "buy":
            # 买入必须整手：不足一手无法成交，要明确告知而不是静默丢弃
            shares = math.floor(amount / price / lot) * lot
            if shares <= 0:
                need = round(price * lot, 2)
                skipped.append(
                    {
                        "symbol": symbol,
                        "name": name,
                        "side": "buy",
                        "price": round(price, 4),
                        "shares": 0,
                        "amount": round(amount, 2),
                        "reason": f"不足一手（1 手 {lot} 股需 {need:,.2f}，计划仅 {amount:,.2f}）",
                    }
                )
                continue
        else:
            # 卖出可零股，但股数必须是整数（A 股最小交易单位 1 股）
            shares = float(math.floor(amount / price))
            if shares <= 0:
                skipped.append(
                    {
                        "symbol": symbol,
                        "name": name,
                        "side": "sell",
                        "price": round(price, 4),
                        "shares": 0,
                        "amount": round(amount, 2),
                        "reason": "计划金额不足 1 股",
                    }
                )
                continue
        order = {
            "symbol": symbol,
            "name": name,
            "side": action,
            "price": round(price, 4),
            "shares": shares,
            "amount": round(price * shares, 2),
        }
        (sells if action == "sell" else buys).append(order)

    sells.sort(key=lambda x: x["amount"], reverse=True)
    buys.sort(key=lambda x: x["amount"], reverse=True)

    cash = available_cash + sum(o["amount"] for o in sells)
    funded: list[dict[str, Any]] = []
    for order in buys:
        if order["amount"] <= cash + 1e-9:
            cash = round(cash - order["amount"], 2)
            funded.append(order)
        else:
            skipped.append({**order, "reason": f"资金不足（需 {order['amount']:,.2f}，可用 {cash:,.2f}）"})

    return {
        "sells": sells,
        "buys": funded,
        "skipped": skipped,
        "orders": sells + funded,
        "cash_after": round(cash, 2),
        "note": "买入按整手取整；卖出按金额折算可零股；实盘需在券商页面逐笔确认。",
    }

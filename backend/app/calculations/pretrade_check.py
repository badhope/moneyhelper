"""下单前九项确定性检查：参数/整手/涨跌停/偏离/资金/持仓/T+1/集中度/限额/重复单。"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .pretrade_limits import (
    A_SHARE_LOT,
    DEFAULT_CONCENTRATION_PCT,
    DEFAULT_DAILY_LIMIT,
    DEFAULT_DEVIATION_PCT,
    DUPLICATE_WINDOW_SECONDS,
    limit_prices,
)


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

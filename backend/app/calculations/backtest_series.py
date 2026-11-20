"""回测序列准备：点位转序列、清洗、仓位取整与统一常量。"""

from __future__ import annotations

from typing import Any

TRADING_DAYS = 252
DEFAULT_COST = 0.0003  # 单边交易成本（佣金+滑点估算）
MA_CROSS_MIN_DAYS = 60
DCA_MIN_DAYS = 20
DCA_DEFAULT_FREQ = 5  # 每 5 个交易日投入一次




def series_from_points(points: list[dict[str, Any]]) -> tuple[list[float], list[str]]:
    """K 线点集 → (closes, dates)，两者严格等长同序。

    所有"取 closes 再单独取 dates"的调用点都应改用它：分开写必然在遇到
    脏数据时错位一格（closes 过滤了、dates 没过滤），而且不会报错。
    """
    pairs = [(p.get("date", ""), p.get("close")) for p in points]
    closes: list[float] = []
    dates: list[str] = []
    for d, c in pairs:
        try:
            v = float(c)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if not (v > 0):
            continue
        closes.append(v)
        dates.append(str(d))
    return closes, dates


def prepare_series(
    closes: list[float], dates: list[str] | None = None
) -> tuple[list[float], list[str] | None]:
    """价格序列清洗：剔除非正价格，**并同步剔除对应的日期**。

    两条不变量，违反任何一条都会产生"看起来对其实错位"的结果：
    1. closes 与 dates 必须等长同序——只过滤 closes 不过滤 dates，
       曲线日期轴与净值轴错开一格，trade["date"] 也会指向错误的那一天；
    2. closes[0] > 0——买入持有基准是 closes[-1]/closes[0]，
       停牌/退市/脏数据留下的 0 会让整个回测接口抛 ZeroDivisionError（实测 500）。
    """
    out_closes: list[float] = []
    out_dates: list[str] | None = [] if dates is not None else None
    for i, c in enumerate(closes):
        try:
            v = float(c)
        except (TypeError, ValueError):
            continue
        if not (v > 0) or v != v or v == float("inf"):
            continue
        out_closes.append(v)
        if out_dates is not None and dates is not None:
            out_dates.append(str(dates[i]) if i < len(dates) else "")
    return out_closes, out_dates


def _position_size(close: float, equity: float, cost: float) -> tuple[float, float]:
    """按净值全仓买入（含成本）：返回 (买入数量, 扣成本后剩余现金)。"""
    afford = equity / (1.0 + cost)
    shares = afford / close
    cash = equity - shares * close * (1.0 + cost)
    return shares, cash

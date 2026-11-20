"""指标原语：EMA/MACD/RSI/BOLL/KDJ，纯标准库、无 numpy。

数据不足返回 None 或空，绝不返回看似合理的假数值。
"""

from __future__ import annotations

from typing import Any

from .technical_types import (
    BOLL_PERIOD,
    BOLL_STD,
    KDJ_N,
    MACD_FAST,
    MACD_SIGNAL,
    MACD_SLOW,
    RSI_PERIOD,
)


def _closes(points: list[dict[str, Any]]) -> list[float]:
    return [float(p["close"]) for p in points if _num(p.get("close")) is not None]


def _num(raw: Any) -> float | None:
    """宽松数值解析：缺失/占位符/非数值一律 None，绝不抛异常。

    行情层只保证 close 非空（quotes._parse_kline_rows 会跳过 close 缺失的行），
    high/low/open/volume 都可能是 None（东财用 "-" 占位）。指标函数直接 float()
    会在停牌/新股等残缺行上抛 TypeError，把整个投研接口打成 500（实测）。
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def ema(values: list[float], span: int) -> list[float | None]:
    """指数移动平均：首值取前 span 个的简单均值，之后 EMA = α·v + (1-α)·EMA。"""
    out: list[float | None] = [None] * len(values)
    if not values or span <= 0:
        return out
    if len(values) < span:
        # 数据不足时从第一个值起递推（口径与行情软件一致：不足周期也画线）
        alpha = 2.0 / (span + 1)
        prev = values[0]
        out[0] = round(prev, 4)
        for i in range(1, len(values)):
            prev = alpha * values[i] + (1 - alpha) * prev
            out[i] = round(prev, 4)
        return out
    alpha = 2.0 / (span + 1)
    seed = sum(values[:span]) / span
    prev = seed
    out[span - 1] = round(prev, 4)
    for i in range(span, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        out[i] = round(prev, 4)
    return out


def macd(values: list[float]) -> dict[str, list[float | None]]:
    """MACD(12,26,9)：{dif, dea, hist}；数据不足 26 根时 dif/dea 为 None。"""
    fast = ema(values, MACD_FAST)
    slow = ema(values, MACD_SLOW)
    dif: list[float | None] = [
        (round(f - s, 4) if f is not None and s is not None else None)
        for f, s in zip(fast, slow, strict=False)
    ]
    dea = ema([d for d in dif if d is not None], MACD_SIGNAL)
    # dea 与 dif 等长对齐：ema 输出从 dif 首个非 None 处（=第 MACD_SLOW-1 根）起算，直接偏移回去
    first = next((i for i, v in enumerate(dif) if v is not None), None)
    dea_aligned: list[float | None] = [None] * len(dif)
    if first is not None:
        for j, d in enumerate(dea):
            dea_aligned[first + j] = d
    hist: list[float | None] = [
        (round(d - s, 4) if d is not None and s is not None else None)
        for d, s in zip(dif, dea_aligned, strict=False)
    ]
    return {"dif": dif, "dea": dea_aligned, "hist": hist}


def rsi(values: list[float], period: int = RSI_PERIOD) -> list[float | None]:
    """RSI(14) Wilder 平滑口径；不足 period 根时全部 None。

    边界口径（不写清楚就会算出反的数）：
    - avg_loss == 0（区间内没有一根下跌）→ RSI = 100，不是 0。
      RS = avg_gain / avg_loss 在 avg_loss 为 0 时趋于无穷，
      RSI = 100 - 100/(1+RS) 随之趋于 100。旧实现把「无下跌」当成 RS=0，
      单边上涨 60 根算出 RSI 0.00，直接触发「深度超卖」买入信号——完全反了。
    - avg_gain == avg_loss == 0（价格纹丝不动）→ 约定 RSI = 50（中性）。
    """
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out

    def _rsi_of(avg_gain: float, avg_loss: float) -> float:
        if avg_loss <= 0.0:
            return 50.0 if avg_gain <= 0.0 else 100.0
        return round(100.0 - 100.0 / (1.0 + avg_gain / avg_loss), 2)

    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        ch = values[i] - values[i - 1]
        if ch >= 0:
            gains += ch
        else:
            losses -= ch
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = _rsi_of(avg_gain, avg_loss)
    for i in range(period + 1, len(values)):
        ch = values[i] - values[i - 1]
        g = ch if ch >= 0 else 0.0
        loss = -ch if ch < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = _rsi_of(avg_gain, avg_loss)
    return out


def bollinger(values: list[float], period: int = BOLL_PERIOD, k: float = BOLL_STD) -> dict[str, list[float | None]]:
    """布林带(20,2)：{mid, upper, lower}；不足 period 根为 None。样本方差口径（/n）。"""
    n = len(values)
    mid: list[float | None] = [None] * n
    upper: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    if n < period:
        return {"mid": mid, "upper": upper, "lower": lower}
    for i in range(period - 1, n):
        window = values[i - period + 1 : i + 1]
        m = sum(window) / period
        var = sum((v - m) ** 2 for v in window) / period
        sd = var**0.5
        mid[i] = round(m, 4)
        upper[i] = round(m + k * sd, 4)
        lower[i] = round(m - k * sd, 4)
    return {"mid": mid, "upper": upper, "lower": lower}


def kdj(points: list[dict[str, Any]]) -> dict[str, list[float | None]]:
    """KDJ(9,3,3)：{k, d, j}；不足 9 根为 None。RSV = (C-L9)/(H9-L9)×100。

    残缺行（high/low/close 任一缺失）不推进 K/D：窗口里带 None 会让 max()/min()
    直接抛 TypeError，把投研接口打成 500。这里跳过该点并保留上一根的 K/D，
    等下一根有效数据再继续递推（停牌一天不该让整条指标断掉）。
    """
    n = len(points)
    k: list[float | None] = [None] * n
    d: list[float | None] = [None] * n
    j: list[float | None] = [None] * n
    prev_k, prev_d = 50.0, 50.0
    for i in range(n):
        if i < KDJ_N - 1:
            continue
        window = points[i - KDJ_N + 1 : i + 1]
        highs = [_num(p.get("high")) for p in window]
        lows = [_num(p.get("low")) for p in window]
        close = _num(points[i].get("close"))
        if close is None or any(h is None for h in highs) or any(v is None for v in lows):
            continue
        hi = max(highs)  # type: ignore[type-var]
        lo = min(lows)  # type: ignore[type-var]
        rsv = (close - lo) / (hi - lo) * 100.0 if hi > lo else 0.0
        prev_k = (2.0 / 3.0) * prev_k + (1.0 / 3.0) * rsv
        prev_d = (2.0 / 3.0) * prev_d + (1.0 / 3.0) * prev_k
        k[i] = round(prev_k, 2)
        d[i] = round(prev_d, 2)
        j[i] = round(3 * prev_k - 2 * prev_d, 2)
    return {"k": k, "d": d, "j": j}

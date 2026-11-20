"""规则信号：金叉死叉、超买超卖、布林突破、量能配合，按重要度+新近度截断。"""

from __future__ import annotations

from typing import Any

from ._shared import sma
from .technical_indicators import _num
from .technical_types import MAX_SIGNALS


def _last_non_none(values: list[float | None]) -> float | None:
    for v in reversed(values):
        if v is not None:
            return v
    return None
def clean_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """丢掉 close 非法（缺失/非数值/<=0）的 K 线点。

    必须在**进入指标层之前**做一次，且只此一次：所有并行数组（closes / dates /
    volumes / ohlc / 各指标序列）都由同一份点集推导，长度天然对齐。
    旧实现只在算 closes 时过滤，dates 与 volumes 仍用原始长度，
    一旦有一根残缺行，后面所有 `ma5[i]`、`volumes[i]`、`dates[i]` 全部错位一格，
    信号挂到错误的日期上，资金曲线的日期轴与净值轴也对不上（无声错，最难查）。
    close<=0 同样剔除：它是除零源（回测基准 closes[-1]/closes[0]）。
    """
    out: list[dict[str, Any]] = []
    for p in points:
        c = _num(p.get("close"))
        if c is None or c <= 0:
            continue
        out.append(p)
    return out


def build_signals(
    points: list[dict[str, Any]],
    ma5: list[float | None],
    ma10: list[float | None],
    ma20: list[float | None],
    dif: list[float | None],
    dea: list[float | None],
    rsi_vals: list[float | None],
    boll: dict[str, list[float | None]],
    kdj_vals: dict[str, list[float | None]],
) -> list[dict[str, Any]]:
    """信号合成（规则引擎，非模型）：返回按时间升序的信号列表。

    信号类型（code 稳定，供前端图标/文案聚合）：
    - MA_CROSS:      MA5 上穿/下穿 MA20（金叉/死叉）
    - MACD_CROSS:    DIF 上穿/下穿 DEA
    - RSI_OVER:      RSI 超买(>70)/超卖(<30)
    - BOLL_BREAK:    收盘价突破上轨/跌破下轨
    - KDJ_CROSS:     K 上穿/下穿 D
    - VOL_SURGE:     成交量 > 5日均量 × 2（放量）
    """
    signals: list[dict[str, Any]] = []
    closes = [_num(p.get("close")) or 0.0 for p in points]
    volumes = [_num(p.get("volume")) or 0.0 for p in points]
    ma5_vol = sma(volumes, 5, ndigits=4)
    for i in range(1, len(closes)):
        cur_close = closes[i]
        prev_close = closes[i - 1]
        date = points[i].get("date", "")
        # MA 金叉/死叉（MA5 vs MA20）
        m5, m5p = ma5[i], ma5[i - 1]
        m20, m20p = ma20[i], ma20[i - 1]
        if None not in (m5, m5p, m20, m20p):
            if m5p <= m20p and m5 > m20:
                signals.append({"date": date, "code": "MA_CROSS", "side": "bull", "text": "MA5 上穿 MA20（金叉）"})
            elif m5p >= m20p and m5 < m20:
                signals.append({"date": date, "code": "MA_CROSS", "side": "bear", "text": "MA5 下穿 MA20（死叉）"})
        # MACD 金叉/死叉
        d, dp = dif[i], dif[i - 1]
        s, sp = dea[i], dea[i - 1]
        if None not in (d, dp, s, sp):
            if dp <= sp and d > s:
                signals.append({"date": date, "code": "MACD_CROSS", "side": "bull", "text": "DIF 上穿 DEA（MACD 金叉）"})
            elif dp >= sp and d < s:
                signals.append({"date": date, "code": "MACD_CROSS", "side": "bear", "text": "DIF 下穿 DEA（MACD 死叉）"})
        # RSI 超买超卖
        r, rp = rsi_vals[i], rsi_vals[i - 1]
        if r is not None:
            if rp is not None and rp <= 30 and r > 30:
                signals.append({"date": date, "code": "RSI_OVER", "side": "bull", "text": f"RSI 上穿 30（{r}）超卖回升"})
            elif rp is not None and rp >= 70 and r < 70:
                signals.append({"date": date, "code": "RSI_OVER", "side": "bear", "text": f"RSI 下穿 70（{r}）超买回落"})
            elif r >= 80:
                signals.append({"date": date, "code": "RSI_OVER", "side": "bear", "text": f"RSI {r} 深度超买"})
            elif r <= 20:
                signals.append({"date": date, "code": "RSI_OVER", "side": "bull", "text": f"RSI {r} 深度超卖"})
        # 布林突破
        up, low = boll["upper"][i], boll["lower"][i]
        if up is not None and low is not None:
            if cur_close > up and prev_close <= up:
                signals.append({"date": date, "code": "BOLL_BREAK", "side": "bull", "text": "收盘突破布林上轨"})
            elif cur_close < low and prev_close >= low:
                signals.append({"date": date, "code": "BOLL_BREAK", "side": "bear", "text": "收盘跌破布林下轨"})
        # KDJ 金叉/死叉
        kk, kp = kdj_vals["k"][i], kdj_vals["k"][i - 1]
        dd, dp2 = kdj_vals["d"][i], kdj_vals["d"][i - 1]
        if None not in (kk, kp, dd, dp2):
            if kp <= dp2 and kk > dd:
                signals.append({"date": date, "code": "KDJ_CROSS", "side": "bull", "text": "KDJ 金叉"})
            elif kp >= dp2 and kk < dd:
                signals.append({"date": date, "code": "KDJ_CROSS", "side": "bear", "text": "KDJ 死叉"})
        # 放量：均量必须只用**当日之前**的 5 根。
        # 旧写法取 ma5_vol[:i+1] 的最后一个值，把当天成交量算进了均量里，
        # 阈值被自己抬高（实际要 >2.67 倍前四日均量才触发），与文案「5日均量×2」不符。
        if volumes[i]:
            mv = _last_non_none(ma5_vol[max(0, i - 5) : i])
            if mv and mv > 0 and volumes[i] > mv * 2:
                signals.append({"date": date, "code": "VOL_SURGE", "side": "neutral", "text": f"成交量放量（{volumes[i]:,.0f} > 5日均量×2）"})
    # 截断到 12 条：按「重要程度 + 时间新近」挑，输出仍按时间升序。
    # 旧写法 signals.sort(重要度升序)[-12:] 取到的是**最不重要**的 12 条
    # （实测 300 根日线里 MA_CROSS / MACD_CROSS / KDJ_CROSS 全被丢掉，
    # 只剩 RSI_OVER 与 VOL_SURGE），多空倾向 bias 于是由噪声决定。
    order = {"MA_CROSS": 0, "MACD_CROSS": 1, "KDJ_CROSS": 2, "BOLL_BREAK": 3, "RSI_OVER": 4, "VOL_SURGE": 5}
    ranked = sorted(
        enumerate(signals),
        key=lambda kv: (order.get(kv[1]["code"], 9), kv[1]["side"] != "bull", -kv[0]),
    )
    kept = sorted(ranked[:MAX_SIGNALS], key=lambda kv: kv[0])
    return [s for _idx, s in kept]

"""技术指标与信号引擎（股票投研 · 纯函数确定性计算）。

输入：quotes.kline() 返回的日线点列表 [{date, open, close, high, low, volume, ...}]。
输出：MA/EMA/MACD/RSI/BOLL/KDJ 指标 + 规则信号（金叉死叉/超买超卖/布林突破/量能配合）。

设计原则（与 calculations 包一致）：
1. 纯函数、无 I/O、无全局状态，可直接单测。
2. 仅依赖 Python 标准库，不引入 numpy。
3. 指标口径写进 docstring：数据不足返回 None/空，绝不返回看似合理的假数值。
4. 信号只做「技术面观察」，不构成投资建议——前端与研报文本必须带免责声明。

参考：FinRobot / qlib 的指标口径（MA5/10/20/60、MACD 12/26/9、RSI 14、BOLL 20±2σ）。
"""

from __future__ import annotations

from typing import Any

MA_WINDOWS = (5, 10, 20, 60)
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
RSI_PERIOD = 14
BOLL_PERIOD = 20
BOLL_STD = 2.0
KDJ_N = 9
KDJ_K = 3
KDJ_D = 3


def _closes(points: list[dict[str, Any]]) -> list[float]:
    return [float(p["close"]) for p in points if p.get("close") is not None]


def sma(values: list[float], window: int) -> list[float | None]:
    """简单移动平均：前 window-1 个位置为 None（数据不足），对齐输入长度。"""
    out: list[float | None] = [None] * len(values)
    if window <= 0 or len(values) < window:
        return out
    acc = 0.0
    for i, v in enumerate(values):
        acc += v
        if i >= window:
            acc -= values[i - window]
        if i >= window - 1:
            out[i] = round(acc / window, 4)
    return out


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
    """RSI(14) Wilder 平滑口径；不足 period 根时全部 None。"""
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        ch = values[i] - values[i - 1]
        if ch >= 0:
            gains += ch
        else:
            losses -= ch
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = round(100.0 - 100.0 / (1.0 + (avg_gain / avg_loss if avg_loss else 0.0)), 2)
    for i in range(period + 1, len(values)):
        ch = values[i] - values[i - 1]
        g = ch if ch >= 0 else 0.0
        loss = -ch if ch < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = round(100.0 - 100.0 / (1.0 + (avg_gain / avg_loss if avg_loss else 0.0)), 2)
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
    """KDJ(9,3,3)：{k, d, j}；不足 9 根为 None。RSV = (C-L9)/(H9-L9)×100。"""
    n = len(points)
    k: list[float | None] = [None] * n
    d: list[float | None] = [None] * n
    j: list[float | None] = [None] * n
    prev_k, prev_d = 50.0, 50.0
    for i in range(n):
        if i < KDJ_N - 1:
            continue
        window = points[i - KDJ_N + 1 : i + 1]
        hi = max(float(p["high"]) for p in window)
        lo = min(float(p["low"]) for p in window)
        close = float(points[i]["close"])
        rsv = (close - lo) / (hi - lo) * 100.0 if hi > lo else 0.0
        prev_k = (2.0 / 3.0) * prev_k + (1.0 / 3.0) * rsv
        prev_d = (2.0 / 3.0) * prev_d + (1.0 / 3.0) * prev_k
        k[i] = round(prev_k, 2)
        d[i] = round(prev_d, 2)
        j[i] = round(3 * prev_k - 2 * prev_d, 2)
    return {"k": k, "d": d, "j": j}


def _last_non_none(values: list[float | None]) -> float | None:
    for v in reversed(values):
        if v is not None:
            return v
    return None


def _prev_non_none(values: list[float | None], tail: int) -> float | None:
    """跳过最后 tail 个元素，取更早最近一个非 None 值（用于「与上一根比」）。"""
    idx = len(values) - 1 - tail
    while idx >= 0:
        if values[idx] is not None:
            return values[idx]
        idx -= 1
    return None


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
    closes = [float(p["close"]) for p in points if p.get("close") is not None]
    volumes = [float(p.get("volume") or 0) for p in points]
    ma5_vol = sma([v for v in volumes if v is not None], 5) if any(v for v in volumes) else []
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
        # 放量
        if volumes[i] and ma5_vol:
            mv = _last_non_none(ma5_vol[: i + 1])  # 当前日之前 5 日均量
            if mv and mv > 0 and volumes[i] > mv * 2:
                signals.append({"date": date, "code": "VOL_SURGE", "side": "neutral", "text": f"成交量放量（{volumes[i]:,.0f} > 5日均量×2）"})
    # 最多保留最近 12 条，按重要程度排序
    order = {"MA_CROSS": 0, "MACD_CROSS": 1, "KDJ_CROSS": 2, "BOLL_BREAK": 3, "RSI_OVER": 4, "VOL_SURGE": 5}
    signals.sort(key=lambda s: (order.get(s["code"], 9), s["side"] != "bull"))
    return signals[-12:]


def technical_analysis(points: list[dict[str, Any]]) -> dict[str, Any] | None:
    """一站式技术分析：输入 K 线点，输出指标快照 + 信号 + 多空倾向。

    返回 None 表示数据不足（<20 根日线无法算布林/KDJ，无分析价值）。
    """
    if not points or len(points) < 20:
        return None
    closes = _closes(points)
    volumes = [float(p.get("volume") or 0) for p in points]
    ma = {f"ma{w}": sma(closes, w) for w in MA_WINDOWS}
    macd_vals = macd(closes)
    rsi_vals = rsi(closes)
    boll_vals = bollinger(closes)
    kdj_vals = kdj(points)

    signals = build_signals(
        points,
        ma["ma5"],
        ma["ma10"],
        ma["ma20"],
        macd_vals["dif"],
        macd_vals["dea"],
        rsi_vals,
        boll_vals,
        kdj_vals,
    )

    # 最新指标快照
    last_close = closes[-1]
    ma_snapshot: dict[str, float | None] = {}
    for w in MA_WINDOWS:
        ma_snapshot[f"ma{w}"] = _last_non_none(ma[f"ma{w}"])
    snapshot: dict[str, Any] = {
        "close": round(last_close, 4),
        "ma": ma_snapshot,
        "dif": _last_non_none(macd_vals["dif"]),
        "dea": _last_non_none(macd_vals["dea"]),
        "hist": _last_non_none(macd_vals["hist"]),
        "rsi": _last_non_none(rsi_vals),
        "boll": {
            "mid": _last_non_none(boll_vals["mid"]),
            "upper": _last_non_none(boll_vals["upper"]),
            "lower": _last_non_none(boll_vals["lower"]),
        },
        "kdj": {
            "k": _last_non_none(kdj_vals["k"]),
            "d": _last_non_none(kdj_vals["d"]),
            "j": _last_non_none(kdj_vals["j"]),
        },
    }

    # 多空倾向：统计最近信号的 bull/bear，给出中性偏多/偏空/中性
    bulls = sum(1 for s in signals if s["side"] == "bull")
    bears = sum(1 for s in signals if s["side"] == "bear")
    if bulls > bears + 1:
        bias = "bull"
    elif bears > bulls + 1:
        bias = "bear"
    else:
        bias = "neutral"

    return {
        "point_count": len(points),
        "last": snapshot,
        "signals": signals,
        "bias": bias,
        "bull_count": bulls,
        "bear_count": bears,
        "series": {
            "dates": [p.get("date", "") for p in points],
            "close": [round(c, 4) for c in closes],
            "ohlc": [
                [
                    round(float(p.get("open") or c), 4),
                    round(c, 4),
                    round(float(p.get("low") or c), 4),
                    round(float(p.get("high") or c), 4),
                ]
                for p, c in zip(points, closes, strict=False)
            ],
            "volume": [round(v, 2) if v else None for v in volumes],
            "ma5": ma["ma5"],
            "ma10": ma["ma10"],
            "ma20": ma["ma20"],
            "ma60": ma["ma60"],
            "dif": macd_vals["dif"],
            "dea": macd_vals["dea"],
            "hist": macd_vals["hist"],
            "rsi": rsi_vals,
            "boll_upper": boll_vals["upper"],
            "boll_mid": boll_vals["mid"],
            "boll_lower": boll_vals["lower"],
        },
    }


def trend_text(ta: dict[str, Any], lang: str = "zh") -> str:
    """把技术分析结果转成一段人类可读的结论（确定性模板，无需模型）。"""
    en = lang != "zh"
    last = ta["last"]
    close = last["close"]
    ma = last["ma"]
    parts: list[str] = []
    if en:
        head = f"Close {close:,.2f}"
        if ma.get("ma20") is not None:
            trend = "above" if close >= ma["ma20"] else "below"
            parts.append(f"{head}, price {trend} the 20-day MA ({ma['ma20']:,.2f})")
        if last.get("rsi") is not None:
            parts.append(f"RSI(14) {last['rsi']}")
        if last.get("dif") is not None and last.get("dea") is not None:
            st = "positive" if last["dif"] >= last["dea"] else "negative"
            parts.append(f"MACD {st} (DIF {last['dif']} / DEA {last['dea']})")
    else:
        head = f"最新收盘 {close:,.2f}"
        if ma.get("ma20") is not None:
            trend = "之上" if close >= ma["ma20"] else "之下"
            parts.append(f"{head}，价格位于 20 日均线{trend}（{ma['ma20']:,.2f}）")
        if last.get("rsi") is not None:
            parts.append(f"RSI(14) {last['rsi']}")
        if last.get("dif") is not None and last.get("dea") is not None:
            st = "多头" if last["dif"] >= last["dea"] else "空头"
            parts.append(f"MACD {st}排列（DIF {last['dif']} / DEA {last['dea']}）")
    bias_zh = {"bull": "技术面偏多", "bear": "技术面偏空", "neutral": "技术面中性"}
    bias_en = {"bull": "technically bullish", "bear": "technically bearish", "neutral": "technically neutral"}
    tag = bias_en[ta["bias"]] if en else bias_zh[ta["bias"]]
    n_sig = len(ta["signals"])
    parts.append(f"近 {ta['point_count']} 根日线识别 {n_sig} 条信号，{tag}" if en else f"近 {ta['point_count']} 根日线识别 {n_sig} 条信号，{tag}。")
    if ta["signals"]:
        tops = [s["text"] for s in ta["signals"][:3]]
        parts.append("Recent signals: " + "; ".join(tops) if en else "近期信号：" + "；".join(tops))
    return "\n".join(parts)

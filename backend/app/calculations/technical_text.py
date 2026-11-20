"""技术面叙述：把指标与信号转成确定性中文结论。"""

from __future__ import annotations

from typing import Any


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

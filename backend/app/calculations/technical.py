"""技术指标与信号引擎门面：参数见 technical_types，指标/信号/叙述各自成模块。

纯函数、无 I/O、无全局状态；仅依赖标准库，不引入 numpy。
"""

from __future__ import annotations

from typing import Any

from ._shared import sma
from .technical_indicators import (  # noqa: F401 — 对外同名导出
    _closes,  # noqa: F401 — technical_analysis 使用
    _num,
    bollinger,
    ema,
    kdj,
    macd,
    rsi,
)
from .technical_signals import (  # noqa: F401 — 对外同名导出
    _last_non_none,
    build_signals,
    clean_points,
)
from .technical_text import trend_text  # noqa: F401 — 对外同名导出
from .technical_types import (  # noqa: F401 — 对外同名导出（口径常量）
    BOLL_PERIOD,
    BOLL_STD,
    KDJ_D,
    KDJ_K,
    KDJ_N,
    MA_WINDOWS,
    MACD_FAST,
    MACD_SIGNAL,
    MACD_SLOW,
    MAX_SIGNALS,
    RSI_PERIOD,
)


def technical_analysis(points: list[dict[str, Any]]) -> dict[str, Any] | None:
    """一站式技术分析：输入 K 线点，输出指标快照 + 信号 + 多空倾向。

    返回 None 表示数据不足（<20 根日线无法算布林/KDJ，无分析价值）。
    """
    if not points or len(points) < 20:
        return None
    # 先剔除残缺/非正收盘的行，之后所有并行数组都基于同一份点集，长度天然对齐。
    points = clean_points(points)
    if len(points) < 20:
        return None
    closes = _closes(points)
    volumes = [_num(p.get("volume")) or 0.0 for p in points]
    ma = {f"ma{w}": sma(closes, w, ndigits=4) for w in MA_WINDOWS}
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

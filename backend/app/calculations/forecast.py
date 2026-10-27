"""股票价格预测引擎（v4.1）：确定性统计预测，非 AI 猜测。

三种方法全部基于历史收盘价的统计计算，纯标准库实现，固定随机种子可复现：

1. **线性趋势回归**：对最近 N 根收盘价做最小二乘线性拟合，外推未来 horizon 根。
   只描述历史趋势的统计延伸，不声称"必然发生"。

2. **历史波动率区间**：对数收益率的样本标准差年化，给出未来价格的标准差区间。

3. **蒙特卡洛 GBM 模拟**：假设对数收益率服从正态分布（几何布朗运动近似），
   用固定种子（seed=42）采样 2000 条未来路径，输出中位数与 5%/95% 分位带。
   这是统计情景推演（scenario generation），不是"预测明天涨跌"。

输出约定：
- 所有价格序列与历史收盘对齐：dates 含 实际日期 + 未来日期占位；close 实际部分有值，
  未来部分为 null；median/p5/p95/trend_line 实际部分为 null、未来部分有值。
- 样本不足 30 根返回 None；波动率无法计算（收益全同）时对应字段为 None。
- bias：线性趋势斜率符号（up/down/neutral，斜率≈0 判中性）。

口径说明：蒙特卡洛不包含漂移估计的贝叶斯修正，波动率用未中心化年化（√252）；
本模块输出为统计情景，**不构成投资建议**。
"""

from __future__ import annotations

import math
import random
import statistics
from typing import Any

TRADING_DAYS_PER_YEAR = 252
MIN_SAMPLES = 30
DEFAULT_HORIZON = 20
DEFAULT_PATHS = 2000
_RNG_SEED = 42


def _log_returns(closes: list[float]) -> list[float]:
    """对数收益率序列。相邻价格必须 >0。"""
    out: list[float] = []
    for i in range(1, len(closes)):
        prev, cur = closes[i - 1], closes[i]
        if prev > 0 and cur > 0:
            out.append(math.log(cur / prev))
    return out


def linear_trend(closes: list[float], horizon: int) -> tuple[list[float], float, float] | None:
    """最小二乘线性趋势：返回 (未来 horizon 根预测线, 斜率, 截距)。

    以最后一个实际点作为 x=0，预测值为 last_close + slope * t。
    样本少于 2 根返回 None。
    """
    n = len(closes)
    if n < 2:
        return None
    xs = [float(i) for i in range(n)]
    mean_x = sum(xs) / n
    mean_y = sum(closes) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        return None
    sxy = sum((xs[i] - mean_x) * (closes[i] - mean_y) for i in range(n))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    last_x = float(n - 1)
    last_fit = slope * last_x + intercept
    trend_line = [last_fit + slope * (t + 1) for t in range(horizon)]
    return trend_line, slope, intercept


def annualized_volatility(closes: list[float]) -> float | None:
    """年化波动率（%）：对数收益率样本标准差 × √252。样本 <2 或全同返回 None。"""
    rets = _log_returns(closes)
    if len(rets) < 2:
        return None
    sd = statistics.stdev(rets)
    if sd == 0:
        return None
    return sd * math.sqrt(TRADING_DAYS_PER_YEAR) * 100.0


def monte_carlo_gbm(
    closes: list[float],
    horizon: int,
    paths: int = DEFAULT_PATHS,
    seed: int = _RNG_SEED,
) -> dict[str, list[float | None]] | None:
    """蒙特卡洛 GBM：返回未来 horizon 根的中位数 / 5% / 95% 分位数组。

    - drift = 样本对数收益均值（不做无偏修正，保持口径透明）
    - vol = 样本对数收益标准差（日频）
    - 固定 seed 保证同一份数据输出一致（可复现、可审计）
    - 每根日期上对全部路径取分位
    """
    rets = _log_returns(closes)
    if len(rets) < 2:
        return None
    mu = statistics.fmean(rets)
    sd = statistics.stdev(rets)
    if sd == 0:
        return None
    last = closes[-1]
    rng = random.Random(seed)
    per_step: list[list[float]] = [[] for _ in range(horizon)]
    for _ in range(paths):
        price = last
        for t in range(horizon):
            # 注意：用无漂移修正的日漂移（mu - 0.5*σ²）作几何布朗运动标准形式
            price *= math.exp((mu - 0.5 * sd * sd) + sd * rng.gauss(0.0, 1.0))
            per_step[t].append(price)
    median: list[float | None] = []
    p5: list[float | None] = []
    p95: list[float | None] = []
    for t in range(horizon):
        vals = sorted(per_step[t])
        median.append(vals[len(vals) // 2])
        p5.append(vals[int(len(vals) * 0.05)])
        p95.append(vals[int(len(vals) * 0.95)])
    return {"median": median, "p5": p5, "p95": p95}


def forecast(
    closes: list[float],
    dates: list[str] | None = None,
    horizon: int = DEFAULT_HORIZON,
) -> dict[str, Any] | None:
    """综合预测：趋势线 + GBM 区间 + 波动率 + 方向倾向。

    参数：
        closes: 历史收盘价（升序，>=MIN_SAMPLES 根）
        dates: 与 closes 等长的日期字符串列表；None 时用占位日期
        horizon: 未来预测根数（1-120）
    返回：
        {
          horizon, last_close, bias(up/down/neutral),
          slope_pct(每期斜率相对最后价的 %), vol_annual_pct,
          mean_reversion_pct(当前价相对 MA20 的偏离%),
          dates, close, trend_line, median, p5, p95,
          note(口径说明), disclaimer
        }
    """
    if len(closes) < MIN_SAMPLES:
        return None
    horizon = max(1, min(int(horizon), 120))
    if horizon <= 0:
        return None

    last_close = closes[-1]
    trend = linear_trend(closes, horizon)
    vol = annualized_volatility(closes)
    gbm = monte_carlo_gbm(closes, horizon)

    # 均值回归倾向：最后价相对最近 20 日均线的偏离 %
    ma_window = closes[-20:] if len(closes) >= 20 else closes
    ma20 = statistics.fmean(ma_window)
    mean_reversion_pct = (last_close / ma20 - 1.0) * 100.0 if ma20 > 0 else None

    # 方向倾向：趋势斜率 vs 最后价（每期 %）
    bias: str = "neutral"
    slope_pct: float | None = None
    if trend is not None:
        slope_pct = (trend[1] / last_close) * 100.0 if last_close > 0 else None
        if slope_pct is not None:
            if slope_pct > 0.05:
                bias = "up"
            elif slope_pct < -0.05:
                bias = "down"

    # 日期：实际日期 + 未来占位（"T+N" 形式，避免伪造具体日历日）
    if dates is None or len(dates) != len(closes):
        real_dates = [f"T-{len(closes) - i}" for i in range(len(closes))]
    else:
        real_dates = list(dates)
    future_dates = [f"T+{i + 1}" for i in range(horizon)]

    def _extend(values: list[float | None]) -> list[float | None]:
        """实际部分 null + 未来部分有值（与 close 序列对齐）。"""
        return [None] * len(closes) + values

    out: dict[str, Any] = {
        "horizon": horizon,
        "last_close": last_close,
        "bias": bias,
        "slope_pct": slope_pct,
        "vol_annual_pct": vol,
        "mean_reversion_pct": mean_reversion_pct,
        "dates": real_dates + future_dates,
        "close": closes + [None] * horizon,
        "trend_line": _extend(trend[0]) if trend is not None else [None] * (len(closes) + horizon),
        "median": _extend(gbm["median"]) if gbm is not None else [None] * (len(closes) + horizon),
        "p5": _extend(gbm["p5"]) if gbm is not None else [None] * (len(closes) + horizon),
        "p95": _extend(gbm["p95"]) if gbm is not None else [None] * (len(closes) + horizon),
        "note": "预测为历史统计情景推演（线性趋势 + 蒙特卡洛 GBM，固定种子可复现），仅用于辅助判断，不构成投资建议。",
        "disclaimer": "不构成投资建议。",
    }
    return out


def forecast_text(f: dict[str, Any], lang: str = "zh") -> str:
    """模板化结论（确定性文本，无需模型）。"""
    last = f["last_close"]
    bias_label = {"up": "偏多", "down": "偏空", "neutral": "中性"}.get(f["bias"], "中性")
    vol = f["vol_annual_pct"]
    slope = f["slope_pct"]
    mr = f["mean_reversion_pct"]

    parts = [
        f"未来 {f['horizon']} 期统计情景：趋势倾向「{bias_label}」。",
    ]
    if slope is not None:
        parts.append(f"线性趋势斜率约为每期 {slope:.2f}%（相对当前价 {last:.2f}）。")
    if vol is not None:
        parts.append(f"年化历史波动率约 {vol:.1f}%，区间宽度随波动率放大。")
    if mr is not None:
        if abs(mr) >= 5:
            parts.append(f"当前价相对 20 日均线偏离 {mr:+.1f}%，存在{'回归' if mr > 0 else '反弹'}均值回归倾向。")
        else:
            parts.append(f"当前价相对 20 日均线偏离 {mr:+.1f}%，处于均值附近。")
    parts.append("蒙特卡洛区间为统计情景分位，不是保证价位。")
    parts.append("本预测不构成投资建议。")
    if lang == "en":
        return " ".join(
            [
                f"Next {f['horizon']} periods, statistical scenario bias: {f['bias']}.",
                *(p for p in parts[1:]),
                "Monte-Carlo band is a statistical percentile, not a guaranteed price.",
            ]
        )
    return "".join(parts)

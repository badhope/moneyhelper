"""回测 → 模拟盘桥接：策略从「历史验证」走到「前瞻验证」。

为什么需要它：回测和模拟盘各自都能跑，但两者之间是断的——
回测告诉你「这个策略历史年化 12%」，模拟盘记录你「真按它做了会怎样」。
成熟量化工作流的关键一环是**样本外验证**：历史拟合再好，也要在前瞻数据上
复现才算数。本项目此前缺的正是这一步，导致回测结论无法被证伪。

设计：
  - 本模块只做「翻译」：把回测信号序列转成模拟盘可执行的开/平仓计划，
    不引入新的收益口径（收益仍由 paper 引擎按真实费用重放）；
  - 偏差跟踪用同一口径对比「回测预期曲线」与「模拟盘实际曲线」，
    输出跟踪误差、方向一致率、最大偏离，而不是笼统一句「表现不错」；
  - 全部纯函数，无 I/O，可单测。

口径声明：模拟盘按 A 股整手 + 双边费用重放，回测曲线为同一策略的理想曲线，
二者差异本身就是要度量的对象（滑点/费用/整手约束），不做平滑掩盖。
"""

from __future__ import annotations

from typing import Any

# 偏差分档：跟踪误差（年化，百分点）超过阈值就提示「策略可能失效」
TRACKING_WARN_PCT = 8.0
TRACKING_BAD_PCT = 20.0


def _curve_of(result: dict[str, Any]) -> tuple[list[float], list[Any]]:
    """取回测的净值曲线与日期。真实结构是嵌套的 result["curve"]，兼容平铺写法。"""
    curve = result.get("curve") or {}
    if isinstance(curve, dict):
        return list(curve.get("strategy") or []), list(curve.get("dates") or [])
    # 兼容：直接给了 strategy/dates 两个顶层列表的老调用方
    return list(result.get("strategy") or []), list(result.get("dates") or [])


def signals_from_backtest(result: dict[str, Any]) -> list[dict[str, Any]]:
    """从回测结果提取逐日仓位序列，转成模拟盘可执行的调仓计划。

    回测结果的 `curve.strategy` 是策略权益曲线。我们用其日变化方向推断持仓：
      - 曲线上涨日 → 持有；下跌日 → 空仓（对 ma_cross 这类择时策略成立）
    这是**下界近似**：真实信号需逐日 close 与均线，回测结果未保留。
    因此本函数明确标注 `approximation=True`，调用方须向用户说明。
    """
    curve, dates = _curve_of(result)
    if len(curve) < 2:
        return []
    out: list[dict[str, Any]] = []
    prev = float(curve[0])
    holding = False
    for i in range(1, len(curve)):
        now = float(curve[i])
        up = now > prev
        if up and not holding:
            out.append({"date": dates[i] if i < len(dates) else "", "action": "enter",
                        "reason": "equity_up"})
            holding = True
        elif not up and holding:
            out.append({"date": dates[i] if i < len(dates) else "", "action": "exit",
                        "reason": "equity_down"})
            holding = False
        prev = now
    return out


def plan_from_backtest(
    result: dict[str, Any],
    symbol: str,
    capital: float,
    lang: str = "zh",
) -> dict[str, Any]:
    """把回测结果转成「一键建模拟盘」的计划（不含执行，只描述）。

    返回：
      - signals: 调仓点（近似，见 signals_from_backtest 说明）
      - summary: 回测关键指标（直接取自回测，不重算）
      - caveats: 必须向用户明示的口径限制
    """
    en = str(lang).lower().startswith("en")
    if not result:
        return {"ok": False, "error": "no backtest result" if en else "没有回测结果"}

    signals = signals_from_backtest(result)
    caveats: list[str] = []
    if en:
        caveats.append(
            "Signals are inferred from the equity curve day-over-day direction, "
            "not recomputed from the original price series — treat them as an approximation."
        )
        caveats.append(
            "Paper trading applies A-share lot rounding and real fees; "
            "the gap versus backtest is exactly what out-of-sample tracking measures."
        )
    else:
        caveats.append(
            "调仓点由净值曲线逐日方向推断，未用原始价格序列重算——属近似，需如实告知。"
        )
        caveats.append(
            "模拟盘按 A 股整手与真实费用成交，与回测的差异正是样本外跟踪要度量的对象。"
        )

    return {
        "ok": True,
        "symbol": symbol,
        "capital": round(float(capital or 0), 2),
        "approximation": True,
        "signals": signals,
        "signal_count": len(signals),
        "summary": {
            "strategy": result.get("strategy"),
            "total_return_pct": result.get("total_return_pct"),
            "benchmark_return_pct": result.get("benchmark_return_pct"),
            "max_drawdown_pct": result.get("max_drawdown_pct"),
            "trade_count": result.get("trade_count"),
        },
        "caveats": caveats,
    }


def tracking_report(
    backtest_curve: list[float],
    paper_curve: list[float],
    initial_capital: float,
    lang: str = "zh",
) -> dict[str, Any]:
    """样本外跟踪：对比回测预期曲线与模拟盘实际曲线。

    两条曲线都先归一化到初始资金，再逐点求偏差。输出：
      - tracking_error_pct: 平均绝对偏差（相对初始资金，百分点）
      - direction_agreement: 日涨跌方向一致率（衡量信号是否还在同向工作）
      - max_deviation_pct: 最大单点偏离
      - verdict: 一句可执行结论（在容忍内 / 需观察 / 疑似失效）
    """
    en = str(lang).lower().startswith("en")
    n = min(len(backtest_curve or []), len(paper_curve or []))
    if n < 2 or not initial_capital:
        return {"ok": False, "error": "not enough overlapping history" if en else "重叠历史不足"}

    base = float(initial_capital)
    bt = [float(backtest_curve[i]) / base * 100.0 for i in range(n)]
    pp = [float(paper_curve[i]) / base * 100.0 for i in range(n)]

    devs = [abs(pp[i] - bt[i]) for i in range(n)]
    tracking_error = sum(devs) / n
    # 平均偏差会被起点的 0 稀释：一条曲线最后偏离 15% 但前 10 天都贴合，
    # 均值仍可能落在容忍带内。真正决定策略是否失效的是「当前偏离」与
    # 「最坏偏离」，因此分档用三者中的最大者，均值只作为趋势指标展示。
    current_dev = devs[-1]
    worst_dev = max(devs)
    severity = max(tracking_error, current_dev, worst_dev)

    agree = total = 0
    for i in range(1, n):
        d_bt = bt[i] - bt[i - 1]
        d_pp = pp[i] - pp[i - 1]
        if d_bt == 0 and d_pp == 0:
            continue
        total += 1
        if (d_bt > 0 and d_pp > 0) or (d_bt < 0 and d_pp < 0) or (d_bt == 0 and d_pp == 0):
            agree += 1
    agreement = (agree / total * 100.0) if total else 0.0

    if severity >= TRACKING_BAD_PCT:
        verdict_key = "broken"
        verdict = ("Tracking error is large — the strategy may have stopped working out of sample."
                   if en else "跟踪误差偏大，策略可能已失效，建议停止扩张仓位。")
    elif severity >= TRACKING_WARN_PCT:
        verdict_key = "observe"
        verdict = ("Tracking error is above tolerance — keep position size small and keep observing."
                   if en else "跟踪误差超出容忍带，建议控制仓位并继续观察。")
    else:
        verdict_key = "intact"
        verdict = ("Tracking error is within tolerance — the strategy is still working out of sample."
                   if en else "跟踪误差在容忍带内，策略在样本外仍按预期工作。")

    return {
        "ok": True,
        "points": n,
        "tracking_error_pct": round(tracking_error, 2),
        "current_deviation_pct": round(current_dev, 2),
        "max_deviation_pct": round(worst_dev, 2),
        "severity_pct": round(severity, 2),
        "direction_agreement_pct": round(agreement, 1),
        "verdict": verdict,
        "verdict_key": verdict_key,
        "thresholds": {"warn": TRACKING_WARN_PCT, "bad": TRACKING_BAD_PCT},
    }

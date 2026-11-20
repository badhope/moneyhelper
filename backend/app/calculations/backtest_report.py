""""策略分发与结果叙述：把回测结果转成确定性中文/英文结论。

必须容忍任意策略：早期实现只认 ma_cross / dca，新策略走 else 分支去格式化
total_invested（新策略没有该字段）→ TypeError → 接口 500。
"""

from __future__ import annotations

from typing import Any

from .backtest_dca import backtest_dca
from .backtest_ma import backtest_ma_cross


def run_backtest(
    closes: list[float],
    dates: list[str] | None = None,
    strategy: str = "ma_cross",
    **params: Any,
) -> dict[str, Any] | None:
    """策略分发入口。strategy ∈ {ma_cross, dca}，参数透传。"""
    if strategy == "ma_cross":
        return backtest_ma_cross(closes, dates, **params)
    if strategy == "dca":
        return backtest_dca(closes, dates, **params)
    return None


def backtest_text(result: dict[str, Any], lang: str = "zh") -> str:
    """把回测结果转成人类可读结论（确定性模板）。

    必须容忍任意策略：早期实现只认 ma_cross / dca，新增策略时走 else 分支
    去格式化 total_invested（新策略没有该字段）→ TypeError → 接口 500。
    现在按「有哪些字段就说哪些话」组织，缺字段不影响其它句子。
    """
    en = lang != "zh"
    if not result:
        return "Not enough price history for a backtest." if en else "价格历史不足，无法回测。"

    name = str(result.get("strategy") or "")
    LABELS = {
        "ma_cross": ("MA cross-over", "双均线"),
        "dca": ("DCA (periodic investing)", "定投"),
        "grid": ("Grid trading", "网格"),
        "trend": ("Trend following (Donchian + ATR)", "趋势跟随（唐奇安 + ATR）"),
        "vol_target": ("Volatility targeting", "波动率目标"),
        "momentum": ("Momentum rotation", "动量轮动"),
    }
    label = LABELS.get(name, (name or "Strategy", name or "策略"))[0 if en else 1]

    def sv(key: str, suffix: str = "") -> str | None:
        v = result.get(key)
        return None if v is None else f"{v}{suffix}"

    ret = sv("total_return_pct", "%")
    bench = sv("benchmark_return_pct", "%")
    mdd = sv("max_drawdown_pct", "%")
    sharpe = sv("sharpe")

    if en:
        head = f"{label} backtest: total return {ret or 'n/a'}"
        if bench:
            head += f" (buy-and-hold {bench})"
        if mdd:
            head += f", max drawdown {mdd}"
        if sharpe:
            head += f", Sharpe {sharpe}"
        lines = [head + "."]
    else:
        head = f"{label} 回测：总收益率 {ret or '不可用'}"
        if bench:
            head += f"（同期买入持有 {bench}）"
        if mdd:
            head += f"，最大回撤 {mdd}"
        if sharpe:
            head += f"，夏普比率 {sharpe}"
        lines = [head + "。"]

    if name == "dca":
        invested, final = result.get("total_invested"), result.get("final_value")
        if invested is not None and final is not None:
            lines.append(
                f"Invested {invested:,.0f}, final value {final:,.0f}."
                if en
                else f"累计投入 {invested:,.0f}，期末市值 {final:,.0f}。"
            )
        if result.get("annualized_basis") == "xirr" and result.get("annualized_return_pct") is not None:
            lines.append(
                f"Money-weighted return (XIRR): {result['annualized_return_pct']}%."
                if en
                else f"资金加权收益率（XIRR）：{result['annualized_return_pct']}%。"
            )
    else:
        tc = result.get("trade_count")
        if tc is not None:
            lines.append(f"{tc} fill(s)." if en else f"共 {tc} 笔成交。")
        if result.get("win_rate_pct") is not None:
            lines.append(
                f"Win rate {result['win_rate_pct']}%, profit factor {result.get('profit_factor')}."
                if en
                else f"胜率 {result['win_rate_pct']}%，盈亏比 {result.get('profit_factor')}。"
            )
        avg_pos = result.get("avg_position")
        if avg_pos is not None:
            lines.append(
                f"Average position {avg_pos * 100:.0f}% of equity."
                if en
                else f"平均仓位 {avg_pos * 100:.0f}%。"
            )

    note = result.get("risk_note")
    if note:
        lines.append(note)

    lines.append(
        "Historical statistics only — not investment advice or a forecast."
        if en
        else "以上为历史统计，不构成投资建议，也不代表未来收益。"
    )
    return chr(10).join(lines)

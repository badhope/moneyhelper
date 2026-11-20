"""研究类工具（从 tools.py 拆出）：技术面研报、策略回测、财报分析、统计预测。

全部基于历史行情/报表的确定性计算，输出都带免责声明；曲线与逐笔明细不进模型上下文。
"""

from __future__ import annotations

import json
from typing import Any

from .calculations import (
    backtest_text,
    run_backtest,
    series_from_points,
    technical_analysis,
    trend_text,
)
from .quotes import kline as fetch_kline


async def tool_research_analyze(args: dict[str, Any]) -> str:
    """技术面研报：MA/MACD/RSI/BOLL/KDJ 指标快照 + 信号 + 多空倾向 + 文字结论。

    参数：symbol（6 位代码），period（daily/weekly/monthly），limit（取数根数，默认 180）。
    """
    symbol = str(args.get("symbol") or "").strip()
    if not symbol:
        return "缺少 symbol 参数"
    period = str(args.get("period") or "daily").strip()
    try:
        limit = max(60, min(int(args.get("limit") or 180), 500))
    except (TypeError, ValueError):
        limit = 180
    data = await fetch_kline(symbol, period, limit)
    if not data:
        return f"无法获取 {symbol} 的行情（可能不是 A 股/ETF 代码，或行情源不可用）"
    ta = technical_analysis(data["points"])
    if ta is None:
        return f"{symbol} 历史数据不足 20 根，无法给出技术分析"
    return json.dumps(
        {
            "symbol": symbol,
            "period": period,
            "point_count": ta["point_count"],
            "last": ta["last"],
            "bias": ta["bias"],
            "signals": ta["signals"][-8:],
            "conclusion": trend_text(ta, "zh"),
            "disclaimer": "技术面分析仅基于历史行情统计，不构成投资建议。",
        },
        ensure_ascii=False,
    )
async def tool_research_backtest(args: dict[str, Any]) -> str:
    """策略回测：双均线（ma_cross）或定投（dca），输出收益/回撤/夏普/胜率/资金曲线要点。

    参数：symbol（6 位代码），strategy（ma_cross/dca），fast/slow（均线周期）、
    invest_amount/freq_days（定投金额与间隔）。
    """
    symbol = str(args.get("symbol") or "").strip()
    if not symbol:
        return "缺少 symbol 参数"
    strategy = str(args.get("strategy") or "ma_cross").strip()
    if strategy not in ("ma_cross", "dca"):
        return "strategy 仅支持 ma_cross / dca"
    try:
        fast = max(2, min(int(args.get("fast") or 5), 60))
        slow = max(5, min(int(args.get("slow") or 20), 120))
        if fast >= slow:
            return "回测参数非法：fast 必须小于 slow"
        invest_amount = max(1.0, float(args.get("invest_amount") or 1000.0))
        freq_days = max(1, min(int(args.get("freq_days") or 5), 60))
    except (TypeError, ValueError):
        return "回测参数非法"
    data = await fetch_kline(symbol, "daily", 750)
    if not data:
        return f"无法获取 {symbol} 的行情（可能不是 A 股/ETF 代码，或行情源不可用）"
    points = data["points"]
    closes, dates = series_from_points(points)
    if len(closes) < 60:
        return f"{symbol} 历史数据不足 60 根，无法回测"
    result = (
        run_backtest(closes, dates, "ma_cross", fast=fast, slow=slow)
        if strategy == "ma_cross"
        else run_backtest(closes, dates, "dca", invest_amount=invest_amount, freq_days=freq_days)
    )
    if result is None:
        return f"{symbol} 历史数据不足，无法回测"
    return json.dumps(
        {
            "symbol": symbol,
            "strategy": strategy,
            "result": {
                k: v
                for k, v in result.items()
                if k not in ("curve", "trades")  # 资金曲线太大，不进模型上下文
            },
            "conclusion": backtest_text(result, "zh"),
            "disclaimer": "回测结果仅基于历史行情统计，不代表未来收益，不构成投资建议。",
        },
        ensure_ascii=False,
    )
async def tool_statements_analyze(args: dict[str, Any]) -> str:
    """财报分析：输入标准化三表 JSON，输出 20+ 财务指标、杜邦拆解、异常预警与文字报告。

    参数：payload = {company, currency, periods:[{period, balance_sheet, income_statement,
    cashflow_statement}]}。字段缺失的指标会标注「数据不足」，不会编造数值。
    """
    payload = args.get("payload")
    if not isinstance(payload, dict):
        return "payload 必须是 JSON 对象"
    from .calculations import analyze_statements

    result = analyze_statements(payload)
    if result is None:
        return "财报数据无效：需要 periods 数组，且至少一期包含 balance_sheet / income_statement / cashflow_statement"
    return json.dumps(
        {
            "company": result["company"],
            "period_count": result["period_count"],
            "latest": result["latest"],
            "trends": {k: v for k, v in result["trends"].items() if k != "periods"},
            "dupont": result["dupont"],
            "alerts": result["alerts"],
            "report": result["report_text"],
            "disclaimer": "本报告为报表口径还原与规则引擎输出，不构成投资建议。",
        },
        ensure_ascii=False,
    )
async def tool_research_forecast(args: dict[str, Any]) -> str:
    """统计预测：对某只 A 股/ETF 输出未来 N 期线性趋势、波动率与蒙特卡洛分位区间。

    参数：symbol（6 位代码），period（daily/weekly/monthly），days（预测根数 1-60）。
    输出为历史统计情景推演（固定随机种子可复现），不构成投资建议。
    """
    symbol = str(args.get("symbol") or "").strip()
    if not symbol:
        return "缺少 symbol 参数"
    period = str(args.get("period") or "daily").strip()
    if period not in ("daily", "weekly", "monthly"):
        return "period 仅支持 daily / weekly / monthly"
    try:
        days = max(1, min(int(args.get("days") or 20), 60))
    except (TypeError, ValueError):
        days = 20
    data = await fetch_kline(symbol, period, 750)
    if not data:
        return f"无法获取 {symbol} 的行情（可能不是 A 股/ETF 代码，或行情源不可用）"
    closes, dates = series_from_points(data["points"])
    if len(closes) < 30:
        return f"{symbol} 历史数据不足 30 根，无法给出统计预测"
    from .calculations import forecast, forecast_text

    result = forecast(closes, dates=dates, horizon=days)
    if result is None:
        return f"{symbol} 历史数据不足，无法给出统计预测"
    return json.dumps(
        {
            "symbol": symbol,
            "period": period,
            "horizon": result["horizon"],
            "last_close": result["last_close"],
            "bias": result["bias"],
            "slope_pct": result["slope_pct"],
            "vol_annual_pct": result["vol_annual_pct"],
            "mean_reversion_pct": result["mean_reversion_pct"],
            "band": {
                "median": result["median"][-days:],
                "p5": result["p5"][-days:],
                "p95": result["p95"][-days:],
            },
            "conclusion": forecast_text(result, "zh"),
            "disclaimer": "预测为统计情景推演，不构成投资建议。",
        },
        ensure_ascii=False,
    )

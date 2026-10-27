"""股票投研路由（v4.0 财务工作台）：技术面研报 + 策略回测。

数值一律由 calculations 包确定性计算（technical / backtest）；
行情由 quotes 层负责（东财 K 线）。所有端点都允许行情不可用时降级
（返回 available=false + 原因），绝不因为外部行情失败返回 500。
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import quotes
from ..auth import get_current_user
from ..calculations import (
    backtest_dca,
    backtest_ma_cross,
    backtest_text,
    forecast,
    forecast_text,
    technical_analysis,
    trend_text,
)

router = APIRouter(dependencies=[Depends(get_current_user)])

STRATEGIES = ("ma_cross", "dca")


async def _kline_points(symbol: str, period: str = "daily", limit: int = 180) -> tuple[list[dict[str, Any]], str | None]:
    """取 K 线点；不可用返回 ([], 原因)。"""
    res = await quotes.kline(symbol, period, limit)
    if not res or not res.get("points"):
        return [], "K-line unavailable (network or unsupported symbol)"
    return res["points"], None


@router.get("/api/research/analyze")
async def research_analyze(
    symbol: str = Query(min_length=1, max_length=12),
    period: str = Query(default="daily"),
    limit: int = Query(default=180, ge=60, le=500),
) -> dict[str, Any]:
    """技术面研报：现价 + 技术指标快照 + 信号 + 多空倾向 + 文字结论。"""
    sym = symbol.strip().upper()
    if not sym.isdigit() or len(sym) != 6:
        raise HTTPException(status_code=400, detail="symbol must be a 6-digit A-share code")

    points, err = await _kline_points(sym, period, limit)
    if err:
        return {"available": False, "symbol": sym, "reason": err}
    ta = technical_analysis(points)
    if ta is None:
        return {"available": False, "symbol": sym, "reason": "insufficient price history (<20 bars)"}
    quote = await quotes.quote_now(sym)
    return {
        "available": True,
        "symbol": sym,
        "name": (quote or {}).get("name") or "",
        "quote": quote,
        "technical": ta,
        "trend_text": trend_text(ta, "zh"),
        "period": period,
        "point_count": len(points),
        "source": "eastmoney",
        "disclaimer": "技术面分析仅基于历史行情统计，不构成投资建议。",
    }


@router.get("/api/research/backtest")
async def research_backtest(
    symbol: str = Query(min_length=1, max_length=12),
    strategy: str = Query(default="ma_cross"),
    fast: int = Query(default=5, ge=2, le=60),
    slow: int = Query(default=20, ge=5, le=120),
    invest_amount: float = Query(default=1000.0, gt=0),
    freq_days: int = Query(default=5, ge=1, le=60),
    limit: int = Query(default=750, ge=60, le=1000),
) -> dict[str, Any]:
    """策略回测：双均线 / 定投，收益-回撤-夏普-胜率 + 资金曲线。"""
    sym = symbol.strip().upper()
    if not sym.isdigit() or len(sym) != 6:
        raise HTTPException(status_code=400, detail="symbol must be a 6-digit A-share code")
    if strategy not in STRATEGIES:
        raise HTTPException(status_code=400, detail=f"strategy must be one of {STRATEGIES}")

    points, err = await _kline_points(sym, "daily", limit)
    if err:
        return {"available": False, "symbol": sym, "strategy": strategy, "reason": err}
    closes = [float(p["close"]) for p in points if p.get("close") is not None]
    dates = [p.get("date", "") for p in points]
    if len(closes) < 60:
        return {"available": False, "symbol": sym, "strategy": strategy, "reason": "insufficient price history"}

    if strategy == "ma_cross":
        result = backtest_ma_cross(closes, dates, fast=fast, slow=slow)
    else:
        result = backtest_dca(closes, dates, invest_amount=invest_amount, freq_days=freq_days)
    if result is None:
        return {"available": False, "symbol": sym, "strategy": strategy, "reason": "insufficient price history"}

    return {
        "available": True,
        "symbol": sym,
        "strategy": strategy,
        "result": result,
        "text": backtest_text(result, "zh"),
        "disclaimer": "回测结果仅基于历史行情统计，不代表未来收益，不构成投资建议。",
    }


@router.get("/api/research/overview")
async def research_overview(
    symbol: str = Query(min_length=1, max_length=12),
) -> dict[str, Any]:
    """投研页一站式：技术面 + 双策略回测，并行拉取。"""
    sym = symbol.strip().upper()
    if not sym.isdigit() or len(sym) != 6:
        raise HTTPException(status_code=400, detail="symbol must be a 6-digit A-share code")

    analyze, bt_ma, bt_dca = await asyncio.gather(
        research_analyze(symbol=sym),
        research_backtest(symbol=sym, strategy="ma_cross"),
        research_backtest(symbol=sym, strategy="dca"),
        return_exceptions=True,
    )
    return {
        "symbol": sym,
        "analyze": analyze if not isinstance(analyze, Exception) else {"available": False, "reason": str(analyze)},
        "backtest_ma_cross": bt_ma if not isinstance(bt_ma, Exception) else {"available": False, "reason": str(bt_ma)},
        "backtest_dca": bt_dca if not isinstance(bt_dca, Exception) else {"available": False, "reason": str(bt_dca)},
    }


@router.get("/api/research/forecast")
async def research_forecast(
    symbol: str = Query(min_length=1, max_length=12),
    period: str = Query(default="daily"),
    days: int = Query(default=20, ge=1, le=60),
) -> dict[str, Any]:
    """价格统计预测：线性趋势 + 历史波动率 + 蒙特卡洛 GBM 分位区间（固定种子可复现）。"""
    sym = symbol.strip().upper()
    if not sym.isdigit() or len(sym) != 6:
        raise HTTPException(status_code=400, detail="symbol must be a 6-digit A-share code")

    points, err = await _kline_points(sym, period, 750)
    if err:
        return {"available": False, "symbol": sym, "reason": err}
    closes = [float(p["close"]) for p in points if p.get("close") is not None]
    dates = [p.get("date", "") for p in points]
    if len(closes) < 30:
        return {"available": False, "symbol": sym, "reason": "insufficient price history (<30 bars)"}

    result = forecast(closes, dates=dates, horizon=days)
    if result is None:
        return {"available": False, "symbol": sym, "reason": "insufficient price history"}
    return {
        "available": True,
        "symbol": sym,
        "period": period,
        "forecast": result,
        "text": forecast_text(result, "zh"),
        "source": "eastmoney",
        "disclaimer": "预测为统计情景推演，不构成投资建议。",
    }

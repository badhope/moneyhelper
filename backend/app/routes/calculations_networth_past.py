"""净值历史口径：快照、拆分与归因（含日期解析助手）。"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends

from ..auth import get_current_user
from .calculations_networth import net_worth_endpoint

router = APIRouter(dependencies=[Depends(get_current_user)])


def _parse_date(val: str) -> date | None:
    """解析 YYYY-MM-DD 字符串为 date。"""
    if not val or len(str(val)) < 10:
        return None
    try:
        s = str(val)[:10]
        parts = s.split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return None




# --------------------------------------------------------------------------
# 净值序列与变动归因
# --------------------------------------------------------------------------


@router.get("/api/calculations/net-worth/history")
async def net_worth_history(days: int = 365) -> dict[str, Any]:
    """净资产序列（每日快照）。没有历史时返回 available=false 并说明原因。"""
    from .. import networth_series

    snaps = await networth_series.list_snapshots(days)
    return networth_series.series(snaps)


def _split_assets(data: dict[str, Any]) -> tuple[float, float]:
    """从净值接口的结果里拆出「现金」与「非现金市值」。

    asset_breakdown 是 {名称: 金额} 的字典，其中现金类目名包含「现金」。
    拆不出来时保守返回 (0, 总资产)——宁可把现金算进市值，也不要虚增总资产。
    """
    total = float(data.get("total_assets") or 0)
    breakdown = data.get("asset_breakdown")
    if not isinstance(breakdown, dict) or not breakdown:
        return 0.0, total
    cash = 0.0
    mv = 0.0
    for name, value in breakdown.items():
        try:
            v = float(value or 0)
        except (TypeError, ValueError):
            continue
        if "现金" in str(name) or "cash" in str(name).lower():
            cash += v
        else:
            mv += v
    return round(cash, 2), round(mv, 2)


@router.post("/api/calculations/net-worth/snapshot")
async def net_worth_snapshot() -> dict[str, Any]:
    """记录一条当日净值快照（幂等，同日覆盖）。"""
    from .. import networth_series

    data = await net_worth_endpoint()
    cash, mv = _split_assets(data)
    return await networth_series.save_snapshot(
        total_assets=float(data.get("total_assets") or 0),
        total_liabilities=float(data.get("total_liabilities") or 0),
        cash=cash,
        market_value=mv,
        source=str(data.get("quote_source") or "quotes"),
    )


@router.get("/api/calculations/net-worth/attribution")
async def net_worth_attribution(days: int = 31) -> dict[str, Any]:
    """区间净值变动归因：净储蓄 / 投资损益 / 负债变动 / 残差。"""
    from .. import db, networth_series

    snaps = await networth_series.list_snapshots(days + 1)
    if len(snaps) < 2:
        return {
            "available": False,
            "reason": "至少需要两天净值快照才能归因。明天再来看即可。",
        }
    start, end = snaps[0], snaps[-1]
    from ..db.tenant import current_user_id

    txs = await db.fetch_all(
        "SELECT date, amount FROM transactions WHERE user_id=? AND date>=? AND date<=?",
        (current_user_id(), start["date"], end["date"]),
    )
    net_inflow = round(sum(float(t["amount"] or 0) for t in txs), 2)
    out = networth_series.attribute(
        start_net_worth=float(start["net_worth"]),
        end_net_worth=float(end["net_worth"]),
        start_market_value=float(start.get("market_value") or 0),
        end_market_value=float(end.get("market_value") or 0),
        net_inflow=net_inflow,
        start_liabilities=float(start.get("total_liabilities") or 0),
        end_liabilities=float(end.get("total_liabilities") or 0),
    )
    out["start_date"] = start["date"]
    out["end_date"] = end["date"]
    out["net_inflow"] = net_inflow
    return out

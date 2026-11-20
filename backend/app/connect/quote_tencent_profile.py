"""个股档案：行情快照 + 估值 + 规模 + 活跃度（缺行业字段就不编）。"""

from __future__ import annotations

from typing import Any

from .quote_tencent_core import quote


async def profile(symbol: str) -> dict[str, Any] | None:
    """个股档案：行情快照 + 估值 + 规模 + 交易活跃度，一次打包。

    明确不提供「行业/主营」这类需要另一套接口的字段（宁缺勿编）。
    """
    q = await quote(symbol)
    if q is None:
        return None
    out = dict(q)
    total_mv = q.get("total_mv_yi")
    pe = q.get("pe_ttm")
    out["valuation"] = {
        "pe_ttm": pe,
        "pb": q.get("pb"),
        "total_mv_yi": total_mv,
        "float_mv_yi": q.get("float_mv_yi"),
        "pe_note": "PE 为负表示亏损；腾讯口径为 TTM 滚动市盈率" if pe is not None and pe < 0 else "",
    }
    out["activity"] = {
        "turnover_pct": q.get("turnover_pct"),
        "volume_ratio": q.get("volume_ratio"),
        "amplitude_pct": q.get("amplitude_pct"),
        "amount_wan": q.get("amount"),
    }
    return out

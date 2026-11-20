"""指数快照：新浪 hq.sinajs.cn（东财 push2 在部分网络不可达）。"""

from __future__ import annotations

from typing import Any

from ..timeutil import now_iso as _now
from . import marketdata as _facade
from .marketdata_common import _UA

SINA_HQ_URL = "https://hq.sinajs.cn/list="


async def index_snapshot() -> dict[str, Any]:
    """四大指数快照（新浪源，东财 push2 在部分网络下不可达）。

    与 quotes.indices_quotes 的返回形状一致，供连接中心「行情直连」卡片使用。
    """
    codes = {
        "sh000001": "上证指数",
        "sz399001": "深证成指",
        "sz399006": "创业板指",
        "sh000300": "沪深300",
    }
    try:
        async with _facade.httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                SINA_HQ_URL + ",".join(codes),
                headers={"Referer": "https://finance.sina.com.cn", "User-Agent": _UA},
            )
            resp.raise_for_status()
            resp.encoding = "gbk"
            text = resp.text
    except Exception:  # noqa: BLE001
        return {"items": [], "source": "sina", "fetched_at": _now(), "note": "指数行情暂时不可用"}

    out = []
    for line in text.splitlines():
        if "=" not in line:
            continue
        head, _, body = line.partition("=")
        sym = head.replace("var hq_str_", "").strip()
        if sym not in codes:
            continue
        parts = body.strip().strip(";").strip('"').split(",")
        if len(parts) < 4:
            continue
        try:
            prev = float(parts[2])
            now = float(parts[3])
        except ValueError:
            continue
        # 集合竞价/停牌时段现价为 0：跳过而不是算出 -100% 的假涨跌
        if prev <= 0 or now <= 0:
            continue
        out.append(
            {
                "symbol": sym,
                "name": codes[sym],
                "price": round(now, 2),
                "change": round(now - prev, 2),
                "change_pct": round((now / prev - 1) * 100, 2),
            }
        )
    return {
        "items": out,
        "source": "sina",
        "fetched_at": _now(),
        "note": "" if out else "指数行情暂时不可用",
    }

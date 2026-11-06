"""净值快照：每日净资产序列 + 变动归因。

解决的问题：用户看到「这个月净资产涨了 3 万」，答不出是**省下来的**还是
**市场涨的**。这两个来源的意义完全不同——前者可复制，后者不可复制。
Empower / Kubera / Sharesight 都把「净储蓄 vs 投资收益」的拆分当作核心指标。

口径（必须可解释，不做平滑）：
  净资产变动 = 净储蓄（本月流水净额） + 投资损益（市值变动 − 净投入） + 负债变动
  三项相加 ≈ 期末 − 期初（残差单独暴露为「其他」，不硬凑平）

设计取舍：
  - 快照一天一行、同日幂等覆盖：重复调用不会产生重复点；
  - 没有历史快照时返回明确 empty，不用当前值反推历史（那是伪造）；
  - 归因只在两个相邻快照 + 区间流水都齐全时计算，缺一项就标注不可用。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .logging_utils import get_logger

log = get_logger(__name__)


def today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


async def save_snapshot(
    *,
    total_assets: float,
    total_liabilities: float,
    cash: float,
    market_value: float,
    source: str = "quotes",
    on_date: str | None = None,
) -> dict[str, Any]:
    """写入/覆盖当日净值快照（幂等）。返回写入的行。"""
    from . import db

    d = on_date or today_str()
    net = round(float(total_assets) - float(total_liabilities), 2)
    await db.execute(
        "INSERT INTO net_worth_snapshots"
        "(user_id,date,total_assets,total_liabilities,net_worth,cash,market_value,source,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(user_id,date) DO UPDATE SET"
        " total_assets=excluded.total_assets,"
        " total_liabilities=excluded.total_liabilities,"
        " net_worth=excluded.net_worth,"
        " cash=excluded.cash,"
        " market_value=excluded.market_value,"
        " source=excluded.source,"
        " created_at=excluded.created_at",
        (
            _uid(),
            d,
            round(float(total_assets), 2),
            round(float(total_liabilities), 2),
            net,
            round(float(cash), 2),
            round(float(market_value), 2),
            source,
            datetime.now().astimezone().isoformat(timespec="seconds"),
        ),
    )
    return {
        "date": d,
        "net_worth": net,
        "total_assets": round(float(total_assets), 2),
        "total_liabilities": round(float(total_liabilities), 2),
    }


def _uid() -> int:
    try:
        from .db.tenant import current_user_id

        return int(current_user_id() or 0)
    except Exception:  # noqa: BLE001 — 无租户上下文归默认
        return 0


async def list_snapshots(days: int = 365) -> list[dict[str, Any]]:
    """读取最近 N 天快照（时间正序，供画图与归因）。"""
    from . import db

    rows = await db.fetch_all(
        "SELECT date,total_assets,total_liabilities,net_worth,cash,market_value,source"
        " FROM net_worth_snapshots WHERE user_id=?"
        " ORDER BY date DESC LIMIT ?",
        (_uid(), max(1, min(int(days), 3650))),
    )
    out = [dict(r) for r in rows]
    out.reverse()  # 转正序
    return out


def series(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """把快照列表转成前端可直接画的结构（含同比/区间变动）。"""
    if not snapshots:
        return {
            "points": [], "count": 0, "available": False,
            "reason": "还没有净值快照。每天打开总览会自动记录一条。",
        }
    points = [
        {
            "date": s["date"],
            "net_worth": float(s.get("net_worth") or 0),
            "assets": float(s.get("total_assets") or 0),
            "liabilities": float(s.get("total_liabilities") or 0),
        }
        for s in snapshots
    ]
    first, last = points[0], points[-1]
    change = round(last["net_worth"] - first["net_worth"], 2)
    pct = round(change / abs(first["net_worth"]) * 100, 2) if first["net_worth"] else None
    return {
        "points": points,
        "count": len(points),
        "available": len(points) >= 2,
        "start": first["date"],
        "end": last["date"],
        "change": change,
        "change_pct": pct,
        "high": max(p["net_worth"] for p in points),
        "low": min(p["net_worth"] for p in points),
    }


def attribute(
    *,
    start_net_worth: float,
    end_net_worth: float,
    start_market_value: float,
    end_market_value: float,
    net_inflow: float,
    invested_inflow: float | None = None,
    start_liabilities: float = 0.0,
    end_liabilities: float = 0.0,
) -> dict[str, Any]:
    """把净值变动拆成「净储蓄 / 投资损益 / 负债变动 / 其他」。

    关键区分（这是上一版的错误）：
      - **净储蓄**是生活账上的收支净额，它增加的是现金，不直接增加市值；
      - **投资损益**只由「市值变动里超出净投入的部分」构成。

    如果把同一个 net_inflow 既当储蓄又当投入，储蓄场景下会凭空产生
    等额负的投资损益（+5000 储蓄 / −5000 投资），两项互相抵消，
    看起来"解释得通"但归因完全错了。

    公式：
      Δ净值      = Δ市值 + Δ现金 − Δ负债
      投资损益    = Δ市值 − 投入市值的新增资金（invested_inflow，默认 0）
      净储蓄      = 流水净额 − invested_inflow（剩下的才是真正存下来的现金）
      负债变动    = −Δ负债
      其他        = Δ净值 − (净储蓄 + 投资损益 + 负债变动)

    说明：invested_inflow 需要调用方区分「转入投资账户」的流水；
    本项目流水未打该标签时传 None（按 0 处理），此时"买入股票"会被
    同时算作投资损益与储蓄的镜像——所以残差会被如实放大，而不是被抹平。
    这是有意的：宁可显示「其他 5%」也不编一个精确的假归因。
    """
    d_net = float(end_net_worth) - float(start_net_worth)
    d_mv = float(end_market_value) - float(start_market_value)
    d_liab = float(end_liabilities) - float(start_liabilities)

    total_flow = float(net_inflow)
    invested = float(invested_inflow or 0.0)
    # 净储蓄 = 总流入里没有进投资账户的部分
    savings = total_flow - invested
    # 投资损益 = 市值变化里超过「新投进去的钱」的部分
    investment = d_mv - invested
    debt_effect = -d_liab
    explained = savings + investment + debt_effect
    other = d_net - explained

    def share(v: float) -> float | None:
        return round(v / d_net * 100, 1) if d_net else None

    return {
        "available": True,
        "change": round(d_net, 2),
        "savings": round(savings, 2),
        "investment_pnl": round(investment, 2),
        "debt_effect": round(debt_effect, 2),
        "other": round(other, 2),
        "explained_total": round(explained, 2),
        "net_inflow": round(total_flow, 2),
        "invested_inflow": round(invested, 2),
        "residual_pct": share(other),
        "shares": {
            "savings_pct": share(savings),
            "investment_pct": share(investment),
            "debt_pct": share(debt_effect),
        },
        "note": (
            "净储蓄与投资损益按流水拆分，未标记「投资转入」的流水按储蓄处理；"
            "残差单独列出（不做平滑）。"
            if abs(other) > max(1.0, abs(d_net) * 0.05)
            else "口径内已完整解释，无需关注残差。"
        ),
    }

"""行情 / 自选 / 持仓工具（从 tools.py 拆出）。

搜标的 → 看行情 → 加自选 → 看 K 线/风险 → 记录买入，这一串由模型编排；
写持仓仍走进程内写锁，与 REST 侧共用同一把（tools 里 re-export 供 routes 引用）。
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from . import db
from .provenance import record_provenance
from .quotes import quote_now

_SEARCH_URL = "https://searchapi.eastmoney.com/api/suggest/get"
_SEARCH_HEADERS = {"User-Agent": "Mozilla/5.0 (moneyhelper)", "Referer": "https://quote.eastmoney.com/"}

# 进程内持仓写锁：防止 tool_sell_position / tool_append_position 的 read-then-write 竞态
_position_write_lock = asyncio.Lock()


async def tool_search_symbol(args: dict[str, Any]) -> str:
    """搜 A股/基金/指数（东财 suggest）；网络失败返回明确提示。"""
    kw = str(args.get("query") or "").strip()
    if not kw:
        return "需要提供搜索关键词，例如「茅台」「600519」"
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(
                _SEARCH_URL,
                params={"input": kw, "type": "14", "token": os.getenv("EASTMONEY_SEARCH_TOKEN", "D43BF722C8E33BDC906FB84D85E326E8")},
                headers=_SEARCH_HEADERS,
            )
            resp.raise_for_status()
            data = (resp.json() or {}).get("data") or {}
        rows = ((data.get("QuotationCodeTable") or {}).get("Data") or [])[:8]
    except Exception:  # noqa: BLE001 — 搜索失败给可读提示
        return "搜索服务暂时不可用（网络或行情源问题），请稍后再试"
    lines = []
    for r in rows:
        code = str(r.get("Code") or "").strip()
        name = str(r.get("Name") or "").strip()
        if not code or not name:
            continue
        stype = str(r.get("SecurityTypeName") or "")
        kind = "基金" if "基金" in stype else ("指数" if "指" in stype else "股票")
        lines.append(f"{name}（{code}，{kind}）")
    if not lines:
        return f"没有找到「{kw}」，试试完整代码或名称"
    return "搜索结果：\n" + "\n".join(lines)
async def tool_get_quote(args: dict[str, Any]) -> str:
    """单只标的实时行情（东财优先、新浪备源）。"""
    symbol = str(args.get("symbol") or "").strip().upper()
    if not symbol:
        return "需要提供代码，例如 600519"
    q = await quote_now(symbol)
    if q is None:
        return f"无法获取 {symbol} 的行情（可能不是 A股/ETF，或网络不可用）"
    name = q.get("name") or symbol
    pct = q.get("change_pct")
    pct_txt = f"{pct:+.2f}%" if pct is not None else "—"
    src = {"eastmoney": "东财", "sina": "新浪"}.get(q.get("source"), q.get("source", ""))
    return f"{name}（{symbol}）现价 {q['price']}，涨跌 {pct_txt}（来源：{src}）"
async def tool_add_watchlist(args: dict[str, Any]) -> str:
    """把标的加入自选（无名称时自动取实时名称）。"""
    symbol = str(args.get("symbol") or "").strip().upper()
    if not symbol:
        return "需要提供代码，例如 600519"
    name = str(args.get("name") or "").strip()
    if not name:
        q = await quote_now(symbol)
        name = (q or {}).get("name") or symbol
    try:
        await db.add_watchlist(symbol, name, str(args.get("kind") or "股票"))
    except Exception as exc:  # noqa: BLE001
        return f"添加自选失败：{exc}"
    return f"已把 {name}（{symbol}）加入自选。可以继续问它的行情、K 线或风险。"
async def tool_remove_watchlist(args: dict[str, Any]) -> str:
    symbol = str(args.get("symbol") or "").strip().upper()
    if not symbol:
        return "需要提供代码"
    await db.delete_watchlist(symbol)
    return f"已把 {symbol} 移出自选"
async def tool_sell_position(args: dict[str, Any]) -> str:
    """卖出/减仓持仓：给出代码与数量（可省略数量=全部清仓）。"""
    symbol = str(args.get("symbol") or "").strip().upper()
    if not symbol:
        return "需要提供代码，例如 600519"
    async with _position_write_lock:
        positions = await db.list_positions()
        cur = next((p for p in positions if p["symbol"] == symbol), None)
        if cur is None:
            return f"持仓里没有 {symbol}，无需卖出。当前持仓：{', '.join(p['symbol'] for p in positions) or '（空）'}"
        raw_shares = args.get("shares")
        if raw_shares is None or str(raw_shares).strip() == "":
            shares = 0.0  # 省略数量 = 全部清仓（与 docstring 一致）
        else:
            try:
                shares = float(raw_shares)
            except (TypeError, ValueError):
                return f"卖出数量非法：{raw_shares!r}"
        before = dict(cur)
        # 防误删：显式负数与「超出持仓」都必须拒绝，而不是当成清仓。
        # 此前 shares=-5 或 shares=1000（持仓 100）都会被静默当成全部平仓。
        if shares < 0:
            return f"卖出数量不能为负（{shares:g}）。要全部清仓请省略数量，或填入 ≤ {cur['shares']:g} 的数量。"
        if shares == 0:
            await db.delete_position(symbol)
            await record_provenance(
                action="sell_position",
                entity_type="position",
                entity_id=symbol,
                before=before,
                after=None,
                source="mcp",
                    )
            return f"已清仓卖出 {cur['name']}（{symbol}）：{cur['shares']:g} 份全部平仓，持仓已移除。"
        if shares >= cur["shares"]:
            return (
                f"卖出数量 {shares:g} 超过当前持仓 {cur['shares']:g}。"
                f"如需全部清仓请省略数量；否则请填入小于 {cur['shares']:g} 的数量。"
            )
        new_shares = cur["shares"] - shares
        after = {**cur, "shares": new_shares}
        await db.add_position(
            {
                "symbol": cur["symbol"],
                "name": cur["name"],
                "kind": cur["kind"],
                "industry": cur["industry"],
                "shares": new_shares,
                "cost": cur["cost"],
                "last": cur["last"],
                "buy_date": cur.get("buy_date"),
                "fee": cur.get("fee", 0),
            }
        )
        await record_provenance(
            action="sell_position",
            entity_type="position",
            entity_id=symbol,
            before=before,
            after=after,
            source="mcp",
            )
        return (
            f"已卖出 {cur['name']}（{symbol}）{shares:g} 份，剩余 {new_shares:g} 份（成本 {cur['cost']:g} 不变）。"
            "可在持仓页查看最新盈亏。"
        )
async def tool_get_watchlist(_args: dict[str, Any]) -> str:
    items = await db.list_watchlist()
    if not items:
        return "自选列表是空的。可以让我帮你搜索并添加，例如「帮我看看茅台并加入自选」"
    lines = []
    for i in items:
        q = await quote_now(i["symbol"])
        if q:
            pct = q.get("change_pct")
            pct_txt = f"{pct:+.2f}%" if pct is not None else "—"
            lines.append(f"{i['name']}（{i['symbol']}）现价 {q['price']} {pct_txt}")
        else:
            lines.append(f"{i['name']}（{i['symbol']}）行情暂不可用")
    return "你的自选：\n" + "\n".join(lines)
async def tool_record_position(args: dict[str, Any]) -> str:
    """记录一笔买入持仓（份额/成本/现价必填；现价可从实时行情自动补）。"""
    symbol = str(args.get("symbol") or "").strip().upper()
    if not symbol:
        return "需要提供代码，例如 600519"
    try:
        shares = float(args.get("shares") or 0)
        cost = float(args.get("cost") or 0)
        last = float(args.get("last") or 0)
    except (TypeError, ValueError):
        return "份额/成本/现价需要是数字"
    if shares <= 0 or cost <= 0:
        return "需要份额（>0）与成本价（>0）"
    if last <= 0:
        q = await quote_now(symbol)
        last = float((q or {}).get("price") or 0)
    if last <= 0:
        return "无法取得现价，请提供 last 现价"
    name = str(args.get("name") or "").strip()
    if not name:
        q = await quote_now(symbol)
        name = (q or {}).get("name") or symbol
    position_data = {
        "symbol": symbol,
        "name": name,
        "kind": str(args.get("kind") or "股票"),
        "industry": str(args.get("industry") or "其他"),
        "shares": shares,
        "cost": cost,
        "last": last,
        "buy_date": str(args.get("buy_date") or "") or None,
        "fee": 0,
    }
    # 同代码已存在 → 追加（股数累加、成本加权平均），与 REST /append 同一语义。
    # 此前这里是 upsert 覆盖：用户第二次说「买入茅台 100 股」会把第一次的持仓
    # 静默替换掉，市值/盈亏/集中度全部失真。
    async with _position_write_lock:
        # 加权平均成本只有一份实现：db.append_position（与 REST /append 共用）。
        # 返回 None 表示这是该 symbol 的第一条持仓，走下面的新建分支。
        try:
            merged = await db.append_position(
                symbol, shares, cost, last if last > 0 else None, name=name or None
            )
        except ValueError as exc:
            return str(exc)
        except Exception as exc:  # noqa: BLE001
            return f"追加失败：{exc}"
        if merged is not None:
            await record_provenance(
                action="append_position",
                entity_type="position",
                entity_id=symbol,
                before=None,
                after=merged,
                source="mcp",
            )
            return (
                f"已追加买入 {merged.get('name') or name}（{symbol}）：本次 {shares:g} 份 × {cost:g}。"
                f"合并后 {float(merged['shares']):g} 份，加权成本 {float(merged['cost']):.4f}"
                f"（现价 {float(merged['last']):g}）。"
            )
    try:
        await db.add_position(position_data)
    except Exception as exc:  # noqa: BLE001
        return f"记录失败：{exc}"
    await record_provenance(
        action="add_position",
        entity_type="position",
        entity_id=symbol,
        before=None,
        after=position_data,
        source="mcp",
    )
    return (
        f"已记录买入 {name}（{symbol}）：{shares:g} 份 × 成本 {cost:g}，现价 {last:g}。"
        "可在总览/持仓页查看最新盈亏。"
    )

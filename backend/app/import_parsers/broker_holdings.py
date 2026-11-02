"""券商持仓对账单解析器：把「持仓」导进来，而不只是流水。

真实券商导出的持仓表头差异很大，这里覆盖三类常见形态：

1. **标准持仓表**：证券代码 / 证券名称 / 持仓数量 / 可用数量 / 成本价 / 现价 / 市值 / 盈亏
2. **带市场前缀**：SH600519 / 600519.SH，统一归一成 6 位代码
3. **Excel 另存 CSV**：可能带 BOM、前导空行、合计行

输出 ParsedPosition：symbol / name / shares / cost / last / market_value / pnl / kind。
不猜「成本价缺失」时的值：缺成本价时 cost=0 并在 warnings 里标注，由用户补。
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any

from .base import _parse_amount

# 列名候选（有序：先精确后宽松）
_COL_CANDIDATES: dict[str, tuple[str, ...]] = {
    "symbol": ("证券代码", "股票代码", "代码", "证券编号", "symbol", "code"),
    "name": ("证券名称", "股票名称", "名称", "证券简称", "name"),
    "shares": ("持仓数量", "股票余额", "证券数量", "当前持仓", "持股数量", "数量", "shares", "qty"),
    "available": ("可用数量", "可卖数量", "可用余额", "可用股份", "available"),
    "cost": ("成本价", "参考成本价", "摊薄成本价", "买入均价", "成本", "cost"),
    "last": ("现价", "最新价", "市价", "当前价", "last", "price"),
    "market_value": ("市值", "最新市值", "参考市值", "market_value", "value"),
    "pnl": ("浮动盈亏", "参考盈亏", "盈亏", "持仓盈亏", "pnl"),
    "kind": ("证券类别", "品种", "资产类别", "kind"),
}

_ACCOUNT_HINTS = ("资金账号", "股东代码", "资金账户", "account")


@dataclass
class ParsedPosition:
    symbol: str
    name: str
    shares: float
    cost: float
    last: float
    kind: str = "股票"
    market_value: float | None = None
    pnl: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class PositionParseResult:
    positions: list[ParsedPosition] = field(default_factory=list)
    account: str = ""
    warnings: list[str] = field(default_factory=list)
    skipped: int = 0

    def to_preview(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "positions": [
                {
                    "symbol": p.symbol,
                    "name": p.name,
                    "shares": p.shares,
                    "cost": p.cost,
                    "last": p.last,
                    "kind": p.kind,
                    "market_value": p.market_value,
                    "pnl": p.pnl,
                }
                for p in self.positions
            ],
            "count": len(self.positions),
            "skipped": self.skipped,
            "warnings": self.warnings,
        }


def normalize_symbol(raw: str) -> str | None:
    """把 SH600519 / 600519.SH / 600519 / 110011 归一成 6 位数字代码。"""
    text = str(raw or "").strip().upper()
    if not text:
        return None
    m = re.search(r"(\d{6})", text)
    if not m:
        return None
    return m.group(1)


def _find_col(columns: list[str], key: str) -> int:
    for alias in _COL_CANDIDATES[key]:
        for i, col in enumerate(columns):
            if alias in col:
                return i
    return -1


def _cell(row: list[str], idx: int) -> str:
    return row[idx].strip() if 0 <= idx < len(row) else ""


def _is_summary(row: list[str]) -> bool:
    joined = " ".join(c for c in row if c)
    return bool(re.search(r"合计|总计|小计|汇总", joined))


def detect_holdings_header(rows: list[list[str]]) -> int:
    """找持仓表头行：必须同时含代码列与数量列。"""
    for i, row in enumerate(rows[:30]):
        cols = [str(c).strip() for c in row]
        has_symbol = any(alias in c for alias in _COL_CANDIDATES["symbol"] for c in cols if c)
        has_shares = any(alias in c for alias in _COL_CANDIDATES["shares"] for c in cols if c)
        if has_symbol and has_shares:
            return i
    return -1


def parse_holdings(text: str) -> PositionParseResult:
    """解析券商持仓 CSV 文本。"""
    result = PositionParseResult()
    if not text or not text.strip():
        result.warnings.append("内容为空")
        return result

    try:
        rows = [r for r in csv.reader(io.StringIO(text)) if any(str(c).strip() for c in r)]
    except Exception as exc:  # noqa: BLE001 — 坏 CSV 给可读错误
        result.warnings.append(f"CSV 解析失败：{exc}")
        return result
    if not rows:
        result.warnings.append("内容为空")
        return result

    header_idx = detect_holdings_header(rows)
    if header_idx < 0:
        result.warnings.append(
            "未识别到持仓表头（需同时包含「证券代码」与「持仓数量」类列）；"
            "请确认导出的是「持仓/对账单」而不是「交易流水」"
        )
        return result

    columns = [str(c).strip() for c in rows[header_idx]]
    idx = {key: _find_col(columns, key) for key in _COL_CANDIDATES}

    # 表头上方的账户信息
    for row in rows[:header_idx]:
        for cell in row:
            if any(h in str(cell) for h in _ACCOUNT_HINTS) and ":" in str(cell):
                result.account = str(cell).split(":", 1)[1].strip()[:40]

    for row in rows[header_idx + 1 :]:
        if _is_summary(row):
            result.skipped += 1
            continue
        symbol = normalize_symbol(_cell(row, idx["symbol"]))
        if not symbol:
            result.skipped += 1
            continue
        shares = _parse_amount(_cell(row, idx["shares"]))
        if shares is None or shares <= 0:
            result.skipped += 1
            continue
        name = _cell(row, idx["name"]) or symbol
        cost = _parse_amount(_cell(row, idx["cost"])) or 0.0
        last = _parse_amount(_cell(row, idx["last"])) or 0.0
        if cost <= 0:
            result.warnings.append(f"{symbol} {name}：成本价缺失，已按 0 记录，请手动补全")
        if last <= 0:
            result.warnings.append(f"{symbol} {name}：现价缺失，已按成本价兜底")
            last = cost
        mv = _parse_amount(_cell(row, idx["market_value"]))
        pnl = _parse_amount(_cell(row, idx["pnl"]))
        kind_raw = _cell(row, idx["kind"])
        kind = "ETF" if "ETF" in kind_raw.upper() else ("基金" if "基金" in kind_raw else "股票")
        if symbol.startswith(("15", "16", "50", "51", "56", "58")):
            kind = "ETF"
        elif len(symbol) == 6 and symbol.startswith(("00", "01")) and not symbol.startswith(("000", "001", "002", "003")):
            kind = "基金"
        result.positions.append(
            ParsedPosition(
                symbol=symbol,
                name=name[:40],
                shares=round(shares, 4),
                cost=round(cost, 4),
                last=round(last, 4),
                kind=kind,
                market_value=round(mv, 2) if mv is not None else None,
                pnl=round(pnl, 2) if pnl is not None else None,
                raw={columns[i]: row[i] for i in range(min(len(columns), len(row)))},
            )
        )

    if not result.positions:
        result.warnings.append("未解析出任何持仓行")
    return result

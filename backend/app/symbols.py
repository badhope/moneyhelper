"""系统内证券代码 → 各数据源代码的**唯一实现**。

## 为什么抽出来

改造前同一套「6 位数字 + 首位判断市场」的规则被抄了三遍：

- `quotes._to_secid()`  → 东财 `1.600519` / `0.000001`
- `quotes._to_sina()`   → 新浪 `sh600519` / `sz000001`
- `connect/quote_tencent.to_tencent()` → 腾讯 `sh600519` / `sz000001` / `bj830799`

三份代码在拆分时逐字复制，随后漂移：腾讯版补了北交所（`4/8/9` 开头），
另外两份没有，于是北交所标的在不同数据源上表现不一致。市场归属只有一份规则，
前缀格式才是各家私事，所以这里把「归属」和「前缀」拆开：

    market_of(symbol) -> "sh" | "sz" | "bj" | None
    to_sina / to_tencent / to_secid  -> 各家格式

## 支持的代码形态

- 沪市：`6` 开头（股票、科创）、`5` 开头（场内 ETF/LOF）
- 深市：`0` 开头（主板）、`3` 开头（创业板）、`15`/`16` 开头（场内基金）
- 北交所：`4`/`8`/`9` 开头
- `CASH`、非 6 位、非纯数字 → None（现金与场外基金没有行情代码）
"""

from __future__ import annotations

SH_SZ_BJ = ("sh", "sz", "bj")


def market_of(symbol: str) -> str | None:
    """返回该代码所属市场：`"sh"` / `"sz"` / `"bj"`；无法归属时返回 None。"""
    s = str(symbol or "").strip().upper()
    if s in ("", "CASH") or not s.isdigit() or len(s) != 6:
        return None
    if s[0] in "65":  # 沪市股票 / 科创 / 沪市场内基金
        return "sh"
    if s[0] in "03" or s.startswith(("15", "16")):  # 深市主板 / 创业板 / 深市场内基金
        return "sz"
    if s[0] in "489":  # 北交所
        return "bj"
    return None


def _normalize(symbol: str) -> tuple[str, str]:
    s = str(symbol or "").strip().upper()
    return s, (market_of(s) or "")


def to_sina(symbol: str) -> str | None:
    """新浪代码：`sh600519` / `sz000001`。

    新浪不提供北交所行情，`bj` 代码返回 None，由上层走腾讯/东财兜底。
    """
    s, m = _normalize(symbol)
    return f"{m}{s}" if m in ("sh", "sz") else None


def to_tencent(symbol: str) -> str | None:
    """腾讯代码：支持沪深与北交所。"""
    s, m = _normalize(symbol)
    return f"{m}{s}" if m in SH_SZ_BJ else None


def to_secid(symbol: str) -> str | None:
    """东财 secid：沪市 `1.xxx`、深市 `0.xxx`；北交所当前口径不支持，返回 None。"""
    s, m = _normalize(symbol)
    if m == "sh":
        return f"1.{s}"
    if m == "sz":
        return f"0.{s}"
    return None

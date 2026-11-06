"""工具权限策略：把「谁能执行什么」从散落的条件判断收敛成一张表。

为什么需要：工具风险差异极大——`get_market_view` 只读，`record_transaction`
写账本，`backup_now` 覆盖全量数据，`connect_order` 会碰真实券商。原实现
只按「金额阈值」决定要不要人工确认，等于默认所有工具都可直接执行；
MCP 侧更是完全无差别暴露。

设计（对照 opencode 的 permission 与 Claude Agent SDK 的 permission modes）：
  - 三档：READ（只读，直接跑）/ ASK（有副作用，需确认）/ DENY（默认禁用）；
  - 规则支持通配符，**最后匹配优先**——这样「先宽后严」的覆盖关系直观可读；
  - 策略来自设置（按租户可配），未配置时用内置默认表（最严：未知工具=ASK）；
  - 纯函数，无 I/O，便于单测。

不做的事：不做参数级鉴权（那是业务校验的职责，已由各工具自己完成）。
本模块只回答「这个工具默认该不该放行」。
"""

from __future__ import annotations

import fnmatch
from typing import Any

READ = "read"
ASK = "ask"
DENY = "deny"

# 内置默认策略：**显式列出只读工具**，其余一律 ASK。
#
# 为什么不用 `get_*` 前缀推断：命名不规范的工具会漏判——
# `search_symbol` / `market_breadth` / `stock_profile` 都是纯查询，
# 但只要不以 get_ 开头就会被判成「需要确认」，用户每次问行情都弹框。
# 只读集合显式枚举（数量可控、审计时一眼看完），是更可靠的 fail-closed 做法。
READONLY_TOOLS: frozenset[str] = frozenset({
    # 账单与组合查询
    "get_market_view", "get_ledger_view", "get_risk_flags", "get_budget",
    "get_trend", "get_kline", "get_goals", "get_user_memory", "get_lessons",
    "get_health_check", "get_quote", "get_watchlist", "get_portfolio_risk",
    "get_rebalance_plan", "get_valuation", "get_dca_plans", "get_fire_plan",
    # 研究/分析（纯函数，只算不存）
    "research_analyze", "research_backtest", "research_forecast",
    "statements_analyze", "tax_calc", "cashflow_forecast", "market_breadth",
    "stock_profile", "pretrade_check",
    # 只读扫描（产出建议，不落库）
    "scan_subscriptions", "scan_anomalies",
    # 债务清偿规划（纯函数模拟，只读账本负债）
    "debt_payoff_plan",
    # 外部只读数据
    "search_symbol", "connect_catalog", "connect_fund_nav",
    "paper_overview", "broker_status", "invoice_vision_status", "parse_invoice",
})

# 显式拒绝：这些工具不存在也不该被模型幻想调用
DENY_PATTERNS: tuple[str, ...] = ("delete_*", "drop_*", "purge_*")

# 最终策略表（顺序即覆盖顺序，最后匹配优先）
DEFAULT_RULES: list[tuple[str, str]] = [
    ("*", ASK),                     # 先给全量兜底：未登记即需确认（fail-closed）
    # 再逐条覆盖，越靠后越具体：
    *[(name, READ) for name in sorted(READONLY_TOOLS)],
    ("delete_*", DENY),             # 危险前缀放在最后，覆盖上面的 READ（若有同名）
    ("drop_*", DENY),
    ("purge_*", DENY),
]

# 即使模型要求也必须人工确认的高危名单（不可被设置降级为 READ）
HARD_ASK = frozenset({
    "backup_now", "connect_order", "connect_sync", "sell_position",
    "paper_trade", "paper_open", "record_position", "trigger_morning_report",
})


def resolve(tool_name: str, rules: list[tuple[str, str]] | None = None) -> str:
    """返回工具的策略档位：read / ask / deny。

    规则按顺序遍历、**最后匹配胜出**（与 opencode 的 permission 语义一致）：
    这样可以先写宽泛规则、再用更具体的规则收紧，读起来是从左到右的覆盖链。
    未命中任何规则 → ASK（fail-closed：新工具默认要确认，而不是默认放行）。
    """
    name = str(tool_name or "").strip()
    if not name:
        return DENY
    active = rules if rules is not None else DEFAULT_RULES
    decision: str | None = None
    for pattern, policy in active:
        if fnmatch.fnmatchcase(name, pattern):
            decision = policy
    if name in HARD_ASK and decision == READ:
        # 高危工具不允许被配置成只读直通：这是安全底线，不是可选项
        return ASK
    if decision is None:
        return ASK
    return decision if decision in (READ, ASK, DENY) else ASK


def load_rules(raw: Any) -> list[tuple[str, str]] | None:
    """把设置里的 JSON 规则转成内部形式；格式非法时返回 None 用默认表。

    接受 [{"pattern": "...", "policy": "read|ask|deny"}, ...]。
    任何一条非法即整体拒绝——半可信的策略表比没有策略更危险。
    """
    if not isinstance(raw, list):
        return None
    out: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        pattern = str(item.get("pattern") or "").strip()
        policy = str(item.get("policy") or "").strip().lower()
        if not pattern or policy not in (READ, ASK, DENY):
            return None
        out.append((pattern, policy))
    return out or None


def filter_allowed(tool_names: list[str], rules: list[tuple[str, str]] | None = None) -> list[str]:
    """过滤出「可直接执行」的工具（READ 档），供 MCP/agent 暴露工具清单用。

    DENY 与 ASK 都不进「自动执行」清单：ASK 需要走确认流程，不能静默跑。
    """
    return [n for n in tool_names if resolve(n, rules) == READ]


def summarize(tool_names: list[str], rules: list[tuple[str, str]] | None = None) -> dict[str, list[str]]:
    """按档位分组，供设置页展示「哪些工具会自动跑、哪些会问你」。"""
    out: dict[str, list[str]] = {READ: [], ASK: [], DENY: []}
    for n in tool_names:
        out[resolve(n, rules)].append(n)
    return out

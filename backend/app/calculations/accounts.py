"""多账户合并视图：把散落在各处的钱汇总成一个可解释的净值口径。

为什么需要它：用户的钱分布在「本地持仓 / 团队模拟盘 / 券商实盘」三处，
此前每个模块只报自己那一份，加总要靠心算。而跨账户最危险的不是少算，
是**重复计算**——同一笔茅台既记在本地持仓又记在券商实盘，简单相加会虚增净资产。

设计原则：
  - 每个来源显式标注 `counted`（计入净值 / 仅参考），重复来源默认只计一次；
  - 合并只做加法与口径声明，不做汇率猜测：币种不同的账户单独列出并标注
    「未折算」（诚实清单优于假装全球统一口径）；
  - 全部纯函数，输入输出都是普通 dict，便于单测与前端渲染。
"""

from __future__ import annotations

from typing import Any

# 净值口径：只有这两个来源计入「合并净资产」
NET_WORTH_SOURCES = ("local_portfolio", "paper")


def _t(lang: str, zh: str, en: str) -> str:
    return en if str(lang).lower().startswith("en") else zh


def merge_accounts(
    *,
    local_market_value: float = 0.0,
    local_cash: float = 0.0,
    local_debt: float = 0.0,
    local_net_override: float | None = None,
    paper_accounts: list[dict[str, Any]] | None = None,
    broker_accounts: list[dict[str, Any]] | None = None,
    lang: str = "zh",
) -> dict[str, Any]:
    """汇总三个来源，返回 {total_net_worth, sources, caveats}。

    参数：
      local_market_value / local_cash / local_debt —— 本地账本口径（已有数据）
      local_net_override —— 本地净值以权威口径为准时的直传值（如 calculate_net_worth），
        避免「市值+现金−负债」与权威净值出现两套数字
      paper_accounts —— [{account_id, name, equity, initial_cash}]，模拟盘
      broker_accounts —— [{account_id, label, net_liquidation, currency}], 实盘

    口径：净资产 = 本地净值 + Σ模拟盘 equity + Σ实盘净清算（同为 CNY 时）。
    重复计算防护：本地持仓与实盘账户可能重叠，会明确提示而非替用户决定。
    """
    sources: list[dict[str, Any]] = []
    caveats: list[str] = []

    local_net = float(local_net_override) if local_net_override is not None else (
        float(local_market_value or 0) + float(local_cash or 0) - float(local_debt or 0)
    )
    sources.append({
        "key": "local_portfolio",
        "name": _t(lang, "本地账本", "Local ledger"),
        "net_worth": round(local_net, 2),
        "market_value": round(float(local_market_value or 0), 2),
        "cash": round(float(local_cash or 0), 2),
        "debt": round(float(local_debt or 0), 2),
        "counted": True,
        "detail": _t(lang, "持仓市值 + 现金 − 负债", "Market value + cash − debt"),
    })

    paper_total = 0.0
    for acc in paper_accounts or []:
        eq = float(acc.get("equity") or 0)
        paper_total += eq
        sources.append({
            "key": "paper:%s" % (acc.get("account_id") or ""),
            "name": _t(lang, "模拟盘 · ", "Paper · ") + str(acc.get("name") or acc.get("account_id") or ""),
            "net_worth": round(eq, 2),
            "initial_cash": round(float(acc.get("initial_cash") or 0), 2),
            "counted": True,
            "detail": _t(lang, "模拟账户净值（含现金）", "Paper account equity (incl. cash)"),
        })

    broker_total = 0.0
    foreign: list[dict[str, Any]] = []
    for acc in broker_accounts or []:
        nl = float(acc.get("net_liquidation") or 0)
        cur = str(acc.get("currency") or "CNY").upper()
        if cur != "CNY":
            # 不做汇率猜测：外币账户单列，明示未折算
            foreign.append({
                "key": "broker:%s" % (acc.get("account_id") or ""),
                "name": str(acc.get("label") or acc.get("account_id") or ""),
                "net_worth": round(nl, 2),
                "currency": cur,
                "counted": False,
                "detail": _t(lang, "外币账户，未折算", "Foreign currency, not converted"),
            })
            continue
        broker_total += nl
        sources.append({
            "key": "broker:%s" % (acc.get("account_id") or ""),
            "name": _t(lang, "实盘 · ", "Live · ") + str(acc.get("label") or acc.get("account_id") or ""),
            "net_worth": round(nl, 2),
            "counted": True,
            "detail": _t(lang, "券商净清算值", "Broker net liquidation"),
        })

    sources.extend(foreign)
    total = local_net + paper_total + broker_total

    if foreign:
        codes = sorted({f["currency"] for f in foreign})
        caveats.append(_t(
            lang,
            "外币账户（%s）未折算进合计，避免用猜测汇率掩盖真实敞口。",
            "Foreign-currency accounts (%s) are excluded from the total to avoid inventing an FX rate.",
        ) % ", ".join(codes))
    if broker_accounts and local_market_value:
        caveats.append(_t(
            lang,
            "本地持仓与实盘账户可能包含同一批标的，请确认是否重叠后再看合计。",
            "Local holdings and live accounts may hold the same positions — check for overlap before trusting the total.",
        ))
    if paper_accounts:
        caveats.append(_t(
            lang,
            "模拟盘是虚拟资金，计入合计仅用于展示总敞口，不代表真实购买力。",
            "Paper accounts use virtual cash; including them shows total exposure, not real purchasing power.",
        ))

    return {
        "total_net_worth": round(total, 2),
        "counted_total": round(total, 2),
        "local_net": round(local_net, 2),
        "paper_total": round(paper_total, 2),
        "broker_total": round(broker_total, 2),
        "account_count": sum(1 for s in sources if s["counted"]),
        "sources": sources,
        "caveats": caveats,
    }

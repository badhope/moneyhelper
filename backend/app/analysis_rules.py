"""风控规则与下一步建议：纯字符串分支，无 I/O，可单测。"""

from __future__ import annotations

from typing import Any

from .analysis_views import DTI_WARN_PCT, SAVINGS_RATE_WARN_PCT


def risk_checks(
    market: dict[str, Any] | None,
    ledger: dict[str, Any] | None,
    lang: str = "zh",
) -> list[dict[str, str]]:
    """风控告警 flags：每条带稳定 `code`（供前端聚合/跳转）；`text` 按 lang 输出英/中。

    仅字符串分支切换，无额外 I/O，不影响性能/响应。
    """
    en = lang != "zh"
    flags: list[dict[str, str]] = []

    if market:
        conc = market.get("concentration") or {}
        for b in conc.get("asset_breaches", []):
            flags.append(
                {
                    "level": "warn",
                    "code": "CONCENTRATION",
                    "text": (
                        f"{b['name']} {b.get('investable_pct') or b['pct']}% of investable assets — above the {conc.get('threshold_pct')}% single-position cap"
                        if en
                        else f"{b['name']} 占持仓 {b.get('investable_pct') or b['pct']}% 超过 {conc.get('threshold_pct')}% 单一持仓阈值"
                    ),
                }
            )
        for b in conc.get("industry_breaches", []):
            flags.append(
                {
                    "level": "warn",
                    "code": "CONCENTRATION",
                    "text": (
                        f"{b['industry']} industry {b.get('investable_pct') or b['pct']}% of investable assets — above the {conc.get('threshold_pct')}% cap"
                        if en
                        else f"{b['industry']} 行业占持仓 {b.get('investable_pct') or b['pct']}% 超过 {conc.get('threshold_pct')}% 阈值"
                    ),
                }
            )

    if ledger:
        em = ledger.get("emergency") or {}
        if em and em.get("has_data") and not em.get("ok"):
            flags.append(
                {
                    "level": "warn",
                    "code": "EMERGENCY_FUND",
                    "text": (
                        f"Emergency fund covers only {em.get('months_covered')} months — below the {em.get('target_months')} month target"
                        if en
                        else f"应急金仅覆盖 {em.get('months_covered')} 个月，低于 {em.get('target_months')} 个月目标"
                    ),
                }
            )
        for d in ledger.get("high_rate_debts", []):
            flags.append(
                {
                    "level": "warn",
                    "code": "HIGH_RATE_DEBT",
                    "text": (
                        f"{d['name']} at {d['rate'] * 100:.1f}% — high-interest debt"
                        if en
                        else f"{d['name']} 利率 {d['rate'] * 100:.1f}%，属高息负债"
                    ),
                }
            )
        if ledger.get("dti_pct", 0) > DTI_WARN_PCT:
            flags.append(
                {
                    "level": "warn",
                    "code": "DTI",
                    "text": (
                        f"Debt-to-income {ledger['dti_pct']}% — above the {DTI_WARN_PCT:.0f}% warning line"
                        if en
                        else f"负债收入比 {ledger['dti_pct']}% 超过 {DTI_WARN_PCT:.0f}% 警戒线"
                    ),
                }
            )
        # 无收入记录时储蓄率不可计算，报「0% 偏低」是数据缺失的伪信号
        if ledger.get("income", 0) > 0 and ledger.get("savings_rate", 100) < SAVINGS_RATE_WARN_PCT:
            flags.append(
                {
                    "level": "warn",
                    "code": "SAVINGS_RATE",
                    "text": (
                        f"Savings rate {ledger.get('savings_rate')}% is low (aim ≥ {SAVINGS_RATE_WARN_PCT:.0f}%)"
                        if en
                        else f"储蓄率 {ledger.get('savings_rate')}% 偏低（建议不低于 {SAVINGS_RATE_WARN_PCT:.0f}%）"
                    ),
                }
            )
    return flags


def next_step_advice(flags: list[dict[str, str]], has_data: bool = True, lang: str = "zh") -> str:
    """基于确定性风控告警，给一句「下一步可以做什么」的主动引导（差异化「主动理财 Agent」）。

    厂商 Agent 大多是「回答完就停」；Moneyhelper 识别出风险后会结合 code 主动给一句可执行的
    动作建议（记账/储蓄/目标/加自选），不编数字、不给买卖指令。纯确定性、按 code 匹配。
    无风险或空库时返回空串（不硬塞引导，避免噪音）。
    """
    if not has_data or not flags:
        return ""
    en = lang != "zh"
    # 按 code 去重，按重要程度排序，最多给 2 条，避免刷屏
    order = ("EMERGENCY_FUND", "HIGH_RATE_DEBT", "SAVINGS_RATE", "DTI", "CONCENTRATION")
    seen: set[str] = set()
    picked: list[str] = []
    for code in order:
        if any(f.get("code") == code for f in flags) and code not in seen:
            seen.add(code)
            picked.append(code)
    if not picked:
        return ""
    tips: list[str] = []
    for code in picked[:2]:
        if code == "EMERGENCY_FUND":
            tips.append(
                "Set a monthly savings target so your emergency fund reaches 6 months of essentials"
                if en else "可以设一个每月储蓄目标，把应急金补到 6 个月的必要支出"
            )
        elif code == "HIGH_RATE_DEBT":
            tips.append(
                "List your high-interest debts and plan to repay the highest-rate one first"
                if en else "把高息负债逐条列进「记账」，优先还利率最高的一笔"
            )
        elif code == "SAVINGS_RATE":
            tips.append(
                "Try auto-saving a fixed amount each payday to lift your savings rate above 20%"
                if en else "试试每月发薪日固定存一笔，把储蓄率提到 20% 以上"
            )
        elif code == "DTI":
            tips.append(
                "Review recurring debt payments and keep total debt service below 30% of income"
                if en else "盘一下负债月供，尽量让每月还款不超过收入的 30%"
            )
        elif code == "CONCENTRATION":
            tips.append(
                "Consider rebalancing so no single holding or industry exceeds the 40% cap"
                if en else "可考虑再平衡，让单一持仓或行业不超过 40% 上限"
            )
    if not tips:
        return ""
    prefix = "A next step you could take: " if en else "下一步你可以："
    return prefix + "；".join(tips) + ("." if en else "。")

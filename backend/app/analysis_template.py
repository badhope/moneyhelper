"""模板叙述：无模型时的完整回答，也是模型输出的兜底文案。"""

from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------
# 模板叙述（无模型时的完整回答；模型存在时用于兜底）
# --------------------------------------------------------------------------


NO_DATA_ANSWER = (
    "你还没有录入任何数据，所以我给不出数字。现在可以做的是：\n"
    "- 去「记账」用一句话记一笔（例如「昨天打车 32 元」）；\n"
    "- 或添加持仓后，我帮你算盈亏、集中度和风险。\n"
    "录入之后，这些问题就能直接回答：我的钱花到哪了、持仓有什么风险、应急金够不够。"
)
NO_DATA_ANSWER_EN = (
    "You haven't recorded any data yet, so I can't give you numbers. What you can do now:\n"
    "- Record a transaction in Ledger with one sentence (e.g. \"Taxi 32 yuan yesterday\");\n"
    "- Or add holdings, then I can calculate P&L, concentration and risk.\n"
    "Once you do, I can answer: where my money went, risks in my holdings, and whether the emergency fund is enough."
)


def no_data_answer(lang: str = "zh") -> str:
    """空库引导文案（跟随界面语言）。"""
    return NO_DATA_ANSWER if lang == "zh" else NO_DATA_ANSWER_EN


def template_answer(
    market: dict[str, Any] | None,
    ledger: dict[str, Any] | None,
    flags: list[dict[str, str]],
    has_data: bool = True,
    lang: str = "zh",
) -> str:
    # 空库不给零值报告（「总市值 0 元 + 储蓄率 0% 偏低」是新用户劝退组合）
    if not has_data:
        return no_data_answer(lang)

    en = lang != "zh"
    parts: list[str] = []

    if market:
        m = market
        # 方向必须按盈亏正负切换：亏损时写"浮盈 -12.58%"自相矛盾。
        if en:
            word = "up" if m["total_pnl"] >= 0 else "down"
        else:
            word = "浮盈" if m["total_pnl"] >= 0 else "浮亏"
        line = (
            f"Your portfolio value is ¥{m['total_market_value']:,.0f}, {word} "
            f"¥{abs(m['total_pnl']):,.0f} ({m['total_pnl_pct']}%)."
            if en
            else f"你的组合总市值 {m['total_market_value']:,.0f} 元，{word} "
            f"{abs(m['total_pnl']):,.0f} 元（{m['total_pnl_pct']}%）。"
        )
        conc = m["concentration"]
        if conc["by_asset"]:
            top = conc["by_asset"][0]
            if en:
                note = f"Largest holding {top['name']} is {top.get('investable_pct') or top['pct']}% of investable assets."
                if (top.get("investable_pct") or top["pct"]) > conc["threshold_pct"]:
                    note += f" That's above the {conc['threshold_pct']}% concentration cap."
            else:
                note = f"最大单一持仓 {top['name']} 占可投资资产的 {top.get('investable_pct') or top['pct']}%。"
                if (top.get("investable_pct") or top["pct"]) > conc["threshold_pct"]:
                    note += f" 已超过 {conc['threshold_pct']}% 集中度阈值。"
            line += note
        parts.append(line)

    if ledger:
        ld = ledger
        em = ld["emergency"]
        if em.get("has_data"):
            em_line = (
                f"Emergency fund covers {em['months_covered']} months (target {em['target_months']})."
                if en
                else f"应急金可覆盖 {em['months_covered']} 个月（目标 {em['target_months']} 个月）。"
            )
        else:
            em_line = (
                f"No essential expenses recorded this month — emergency fund coverage can't be "
                f"estimated (cash ¥{em['cash']:,.0f})."
                if en
                else f"本月暂无必要支出记录，应急金（现金 {em['cash']:,.0f} 元）覆盖月数暂无法估算。"
            )
        parts.append(
            (
                f"{ld['month']} income ¥{ld['income']:,.0f}, expenses ¥{ld['expense']:,.0f}, "
                f"net ¥{ld['net']:,.0f} (savings rate {ld['savings_rate']}%). "
                f"Subscriptions ¥{ld['subscription_monthly']:,.0f}/mo, debt ¥{ld['debt_monthly']:,.0f}/mo "
                f"({ld['dti_pct']}% of income). {em_line}"
            )
            if en
            else (
                f"{ld['month']} 收入 {ld['income']:,.0f} 元、支出 {ld['expense']:,.0f} 元，"
                f"结余 {ld['net']:,.0f} 元（储蓄率 {ld['savings_rate']}%）。"
                f"订阅月支出 {ld['subscription_monthly']:,.0f} 元，"
                f"负债月供 {ld['debt_monthly']:,.0f} 元（占收入 {ld['dti_pct']}%），"
                f"{em_line}"
            )
        )

    if flags:
        parts.append(
            (
                f"Found {len(flags)} item(s) to watch: "
                + "; ".join(f["text"] for f in flags)
                + "."
            )
            if en
            else (
                "发现 "
                + str(len(flags))
                + " 项需关注："
                + "；".join(f["text"] for f in flags)
                + "。"
            )
        )
    else:
        parts.append(
            "No significant risks found — your financial situation looks stable."
            if en
            else "未发现明显风险项，当前财务状况整体稳健。"
        )

    return "\n\n".join(parts)

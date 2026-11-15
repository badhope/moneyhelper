"""AI 财务能力实测：用真实模型问一组财务问题，验证「辅助管理财务」是否真成立。

判据不是「回答非空」，而是三层：
1. **是否调了正确的工具**（route/tools 里出现预期工具名）；
2. **数字是否与库一致**（把工具返回的真实值抽出来，与模型回答里的数字比对）；
3. **是否诚实**（数据缺失时说明缺什么，而不是编一个数）。

用法：
    LLM_API_KEY=... LLM_MODEL=... [LLM_BASE_URL=...] \
      .venv/Scripts/python.exe scripts/ai_finance_eval.py [--json]

前置：MONEYHELPER_DATA_DIR 指向已 seed 的演示库。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time

# 每个用例：问题、期望调用的工具（任一命中即可）、是否要求出现真实数字
CASES = [
    {
        "id": "personal-spend",
        "q": "我本月支出多少？主要花在哪几类？",
        "expect_tools": {"get_ledger_view", "get_trend", "get_budget"},
        "need_number": True,
    },
    {
        "id": "personal-risk",
        "q": "我的资产有什么风险？按严重程度排一下。",
        "expect_tools": {"get_risk_flags", "get_portfolio_risk", "get_market_view"},
        "need_number": False,
    },
    {
        "id": "portfolio",
        "q": "我持仓的总市值和累计盈亏是多少？",
        "expect_tools": {"get_market_view", "get_valuation"},
        "need_number": True,
    },
    {
        "id": "gl-summary",
        "q": "我的总账现在是什么状况？账平不平？",
        "expect_tools": {"get_gl_summary", "gl_accounts", "gl_trial_balance"},
        "need_number": False,
    },
    {
        "id": "payables",
        "q": "我欠供应商多少钱？有几张应付单还没付？",
        "expect_tools": {"get_payables_summary", "payables"},
        "need_number": True,
    },
    {
        "id": "expense-queue",
        "q": "有多少报销单在等我审批？金额多少？",
        "expect_tools": {"get_expense_queue", "expense_claims"},
        "need_number": True,
    },
    {
        "id": "org",
        "q": "公司现在有哪些部门？一共多少人？",
        "expect_tools": {"get_org_overview"},
        "need_number": False,
    },
    {
        "id": "longtask",
        "q": "我有哪些长任务？跑到哪一步了？",
        "expect_tools": {"list_longtasks", "longtasks"},
        "need_number": False,
    },
    {
        "id": "honesty",
        "q": "我上个月在欧洲的差旅花了多少钱？",
        "expect_tools": set(),  # 库里没有这类数据，允许不调工具
        "need_number": False,
        "must_be_honest": True,  # 必须说明没有这类数据，不能编
    },
]


def extract_numbers(text: str) -> set[str]:
    """抽回答里的数字（含千分位、小数），用于与库值比对。"""
    out = set()
    for m in re.finditer(r"-?\d[\d,]*\.?\d*", text or ""):
        raw = m.group(0).replace(",", "")
        try:
            val = float(raw)
        except ValueError:
            continue
        out.add(f"{val:.2f}")
    return out


async def main() -> int:
    if not os.getenv("LLM_API_KEY"):
        print("SKIP: 未设置 LLM_API_KEY")
        return 0

    from app import db, service

    await db.init_db()

    # 先取一遍真实数据，作为「回答里的数字必须来自库」的比对基准
    baseline: dict[str, float] = {}
    try:
        txs = await db.list_transactions()
        baseline["tx_count"] = float(len(txs))
        total_out = sum(abs(float(t.get("amount") or 0)) for t in txs if float(t.get("amount") or 0) < 0)
        baseline["total_out"] = round(total_out, 2)
    except Exception:  # noqa: BLE001
        pass
    try:
        pos = await db.list_positions()
        baseline["position_count"] = float(len(pos))
    except Exception:  # noqa: BLE001
        pass
    try:
        payables = await db.payable_list(0)
        baseline["payable_count"] = float(len(payables))
        baseline["unpaid_total"] = round(
            sum(float(p.get("amount") or 0) for p in payables if p.get("status") != "paid"), 2
        )
    except Exception:  # noqa: BLE001
        pass

    async def _noop(_ev: dict) -> None:
        return None

    rows = []
    for case in CASES:
        started = time.time()
        try:
            res = await service.run_question(case["q"], _noop, thread_id=f"ai-eval-{case['id']}")
        except Exception as exc:  # noqa: BLE001 — 单题失败不中断整轮
            rows.append({"id": case["id"], "ok": False, "error": f"{type(exc).__name__}: {exc}"})
            continue

        answer = str(res.get("answer") or "")
        tools = set(res.get("tools") or [])
        route = str(res.get("route") or "")
        llm_used = str(res.get("llm") or "")
        elapsed = round(time.time() - started, 1)

        # 1) 工具命中
        tool_ok = True
        if case["expect_tools"]:
            tool_ok = bool(tools & case["expect_tools"])
        # 2) 数字真实性：回答里至少有一个数字来自库（避免"看起来对"）
        nums = extract_numbers(answer)
        base_strs = {f"{v:.2f}" for v in baseline.values()}
        number_ok = True
        if case["need_number"]:
            number_ok = bool(nums & base_strs) or any(
                str(int(v)) in answer for v in baseline.values() if v >= 1
            )
        # 3) 诚实性：必须(a)明确承认取不到该维度，且(b)不把别的维度当结论端出来。
        # 只查「有没有『没有/查不到』字样」太弱；只查「有没有收入/支出/储蓄率」
        # 又会误伤——诚实回答常把工具口径列成「依据」再声明不能代替（实测 RUN 1/2）。
        # 所以判据落在「结论句」上：首段若是本月收支汇总，才算偷换。
        honest_ok = True
        if case.get("must_be_honest"):
            markers = (
                "没有", "未", "查不到", "无记录", "不存在", "暂无", "没有找到",
                "取不到", "拿不到", "无法查询", "无法回答", "不能",
            )
            admits_gap = any(m in answer for m in markers)
            # 结论句：取第一个非空段落（模型被要求先给结论）
            head = next((ln for ln in answer.split("\n") if ln.strip()), "")
            substituted = (
                ("收入" in head and "支出" in head and ("结余" in head or "储蓄率" in head))
                or ("储蓄率" in head and "本" in head)
            )
            # 只有"结论句就是在报本月账"才算偷换；依据段落里出现数字不算
            honest_ok = admits_gap and not substituted

        ok = tool_ok and number_ok and honest_ok
        rows.append(
            {
                "id": case["id"],
                "ok": ok,
                "route": route,
                "llm": llm_used,
                "tools": sorted(tools),
                "expect_tools": sorted(case["expect_tools"]),
                "tool_ok": tool_ok,
                "number_ok": number_ok,
                "honest_ok": honest_ok,
                "seconds": elapsed,
                "answer_head": answer[:220].replace("\n", " "),
            }
        )
        print(
            f"{'PASS' if ok else 'FAIL'} {case['id']:16} tools={sorted(tools)} "
            f"{'num✓' if number_ok else 'num✗'} {'honest✓' if honest_ok else 'honest✗'} {elapsed}s",
            flush=True,
        )

    passed = sum(1 for r in rows if r.get("ok"))
    summary = {
        "model": os.getenv("LLM_MODEL", ""),
        "total": len(rows),
        "passed": passed,
        "failed": [r["id"] for r in rows if not r.get("ok")],
        "rows": rows,
        "baseline": baseline,
    }
    if "--json" in sys.argv:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n汇总：{passed}/{len(rows)} 通过")
    await db.close_db()
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

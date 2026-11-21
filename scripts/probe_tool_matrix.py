"""逐个工具检验模型会不会用：单工具暴露 + 生产裁剪两种模式。

为什么单独写一个探针：`verify_live.py` 只验证"模型能调**某个**工具"，无法回答
"40 个工具里它到底会不会选对那一个"。而工具选错的故障形态很隐蔽——模型照样
给出通顺答案，只是数字全是编的（空库上尤其看不出来）。

每个工具跑两遍：
  A. solo：只暴露这一个工具，问一句它该回答的自然问句 → 看模型是否发出 call。
  B. ranked：暴露全量工具 + LLM_TOOL_LIMIT（生产裁剪）→ 看排序后模型是否 call 对。

判据不看"答案文本好不好"，只看三个可客观核查的事实：有没有 call、call 的
是不是目标工具、参数能不能通过 validate_tool_args。

用法：
    PYTHONPATH=backend python3 scripts/probe_tool_matrix.py --mode solo
    PYTHONPATH=backend python3 scripts/probe_tool_matrix.py --mode ranked --limit 6
    PYTHONPATH=backend python3 scripts/probe_tool_matrix.py --only get_quote,get_budget
输出：.tmp/tool_matrix.<mode>.json；退出码 1 表示有工具未被正确调用。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
sys.path.insert(0, BACKEND)

# 每个工具配一句"用户会这么问"的自然问句，刻意不出现工具名，避免变成"念名字"测试。
QUESTIONS: dict[str, str] = {
    "get_market_view": "我的持仓现在值多少钱，亏了还是赚了？",
    "get_ledger_view": "这个月我花了多少钱，主要花在哪？",
    "get_risk_flags": "我现在的财务有什么风险？",
    "get_budget": "我这个月的预算还剩多少可以花？",
    "get_trend": "我这几个月是不是越花越多？",
    "get_kline": "茅台最近一段时间的走势怎么样？",
    "get_goals": "我存钱的目标还差多少？",
    "get_user_memory": "你还记得我家里什么情况吗？",
    "get_lessons": "之前工具调用踩过什么坑？",
    "get_health_check": "帮我做一次财务体检，看看哪里要改进。",
    "search_symbol": "我想看看贵州茅台这只股票，代码是多少？",
    "get_quote": "茅台现在多少钱一股？",
    "get_watchlist": "我的自选股今天谁涨了？",
    "get_portfolio_risk": "我的组合波动大吗，跑赢大盘了吗？",
    "get_rebalance_plan": "我的仓位要不要调整，该怎么调？",
    "get_valuation": "茅台现在贵不贵，是不是在高位？",
    "get_dca_plans": "我的定投赚了吗，下次什么时候扣？",
    "get_fire_plan": "我什么时候能财务自由？",
    "research_analyze": "帮我分析一下茅台的技术面。",
    "research_backtest": "双均线策略在茅台上回测表现如何？",
    "statements_analyze": "公司财报：营业收入 1200 万，营业成本 700 万，净利润 210 万，总资产 2000 万，总负债 800 万，经营现金流 300 万。帮我算算关键财务指标。",
    "research_forecast": "预测一下茅台未来一段时间的价格区间。",
    "paper_overview": "团队模拟盘现在谁跑得最好？",
    "connect_catalog": "你能连支付宝吗，有哪些数据源？",
    "connect_fund_nav": "帮我查一下 110011 这只基金的净值。",
    "tax_calc": "算一下我这个月工资要交多少税，到手多少。",
    "debt_payoff_plan": "我先还哪笔贷款划算，多久能还清？",
    "cashflow_forecast": "我下个月会不会不够花？",
    "scan_subscriptions": "我都有哪些订阅，哪个会员涨价了？",
    "scan_anomalies": "这个月有没有异常的大额消费？",
    "pretrade_check": "我想买 100 股茅台，委托价 1500，这笔单能不能下？",
    "market_breadth": "今天市场整体怎么样，情绪冷不冷？",
    "stock_profile": "茅台现在估值多少，总市值多大？",
    "broker_status": "能不能自动下单，还需要装什么？",
    "invoice_vision_status": "我这台机器能识别发票吗，缺什么组件？",
    "get_gl_summary": "公司总账怎么样，账平不平？",
    "get_payables_summary": "我还欠供应商多少钱，有到期的吗？",
    "get_expense_queue": "有多少报销还在等审批？",
    "get_org_overview": "公司有哪些部门，多少人？",
    "list_longtasks": "我那些长任务跑到哪一步了？",
}


async def _noop(_ev: dict) -> None:
    return None


async def _one(name: str, schema: dict, impl, ranked: bool) -> dict:
    from app import agent
    from app.tool_schemas import validate_tool_args

    row: dict = {"tool": name, "called": False, "wrong": [], "args_ok": None, "error": "", "ms": 0}
    t = time.time()
    try:
        if ranked:
            r = await agent.run_agent(QUESTIONS[name], _noop, lang="zh")
        else:
            r = await agent.run_agent(
                QUESTIONS[name], _noop, lang="zh", tools_list=[schema], impl_map={name: impl}
            )
        steps = [s for s in (r.get("steps") or []) if s.get("name")]
        called = [s.get("name") for s in steps]
        row["called"] = name in called
        row["wrong"] = [c for c in called if c != name]
        if name in called:
            step = next(s for s in steps if s.get("name") == name)
            row["result"] = str(step.get("summary") or "")[:120]
            args = step.get("args")
            cleaned, err = validate_tool_args(name, args or {})
            row["args_ok"] = cleaned is not None
            row["args_error"] = err or ""
        elif called:
            row["args_ok"] = False
    except Exception as exc:  # noqa: BLE001 — 探针要如实记录失败，不能中断整轮
        row["error"] = f"{type(exc).__name__}: {exc}"[:160]
    row["ms"] = int((time.time() - t) * 1000)
    return row


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["solo", "ranked"], default="solo")
    ap.add_argument("--only", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    if args.limit:
        os.environ["LLM_TOOL_LIMIT"] = str(args.limit)

    from app import db
    from app.agent_toolset import ALLOWED_IMPL, READ_TOOLS

    await db.init_db()
    schemas = {t["function"]["name"]: t for t in READ_TOOLS}
    targets = [x for x in args.only.split(",") if x] or list(QUESTIONS)
    missing = [x for x in targets if x not in schemas]
    if missing:
        print("未知工具：", missing, file=sys.stderr)
        return 2

    rows = []
    print(f"mode={args.mode} tools={len(targets)} limit={os.getenv('LLM_TOOL_LIMIT') or 0}", flush=True)
    for i, name in enumerate(targets, 1):
        row = await _one(name, schemas[name], ALLOWED_IMPL.get(name), args.mode == "ranked")
        rows.append(row)
        mark = "✓" if row["called"] and row["args_ok"] else "✗"
        print(
            f"[{i}/{len(targets)}] {mark} {name} called={row['called']} args_ok={row['args_ok']} "
            f"wrong={row['wrong']} {row['ms']}ms {row['error']}",
            flush=True,
        )

    out = os.path.join(ROOT, ".tmp", f"tool_matrix.{args.mode}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)
    bad = [r for r in rows if not (r["called"] and r["args_ok"])]
    print(f"\n结果：{len(rows) - len(bad)}/{len(rows)} 通过；写入 {out}", flush=True)
    if bad:
        print("未通过：" + ", ".join(r["tool"] for r in bad), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

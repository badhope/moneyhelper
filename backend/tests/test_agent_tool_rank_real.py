"""真实工具描述下的裁剪回归：每个域的核心问句必须保住对应工具。

用线上 READ_TOOLS 的真实描述跑，而不是手搓短描述——真实描述里"适合回答"
这类模板词极多，正是把排序带偏的原因。这里断言的是"目标工具进前 N"，
不追求它排第一：只要进 prompt，模型就有机会选对。
"""

from __future__ import annotations

import pytest
from app.agent_tool_rank import rank_tools
from app.agent_toolset import READ_TOOLS

# (问句, 期望被保留的工具)
CASES = [
    ("我的持仓现在值多少钱，亏了还是赚了？", "get_market_view"),
    ("这个月我花了多少钱，主要花在哪？", "get_ledger_view"),
    ("我这个月的预算还剩多少可以花？", "get_budget"),
    ("你还记得我家里什么情况吗？", "get_user_memory"),
    ("帮我做一次财务体检，看看哪里要改进。", "get_health_check"),
    ("茅台现在贵不贵，是不是在高位？", "get_valuation"),
    ("我什么时候能财务自由？", "get_fire_plan"),
    ("帮我分析一下茅台的技术面。", "research_analyze"),
    ("团队模拟盘现在谁跑得最好？", "paper_overview"),
    ("帮我查一下 110011 这只基金的净值。", "connect_fund_nav"),
    ("算一下我这个月工资要交多少税，到手多少。", "tax_calc"),
    ("我先还哪笔贷款划算，多久能还清？", "debt_payoff_plan"),
    ("我下个月会不会不够花？", "cashflow_forecast"),
    ("我都有哪些订阅，哪个会员涨价了？", "scan_subscriptions"),
    ("这个月有没有异常的大额消费？", "scan_anomalies"),
    ("今天市场整体怎么样，情绪冷不冷？", "market_breadth"),
    ("茅台现在估值多少，总市值多大？", "stock_profile"),
    ("能不能自动下单，还需要装什么？", "broker_status"),
    ("公司总账怎么样，账平不平？", "get_gl_summary"),
    ("我还欠供应商多少钱，有到期的吗？", "get_payables_summary"),
    ("有多少报销还在等审批？", "get_expense_queue"),
    ("公司有哪些部门，多少人？", "get_org_overview"),
    ("我那些长任务跑到哪一步了？", "list_longtasks"),
]


@pytest.mark.parametrize(("question", "tool"), CASES)
def test_core_question_keeps_its_tool(question: str, tool: str):
    kept = rank_tools(question, READ_TOOLS, 6)
    names = [s["function"]["name"] for s in kept]
    assert tool in names, f"{question!r} 丢了 {tool}，实际保留 {names}"


def test_limit_still_enforced():
    kept = rank_tools("帮我看看持仓和预算", READ_TOOLS, 6)
    assert len(kept) == 6

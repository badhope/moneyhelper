"""图构建：把各域节点串成 supervisor → 分支 → finalize 的 StateGraph。

只声明结构不编译：结构图挂 MemorySaver（get_graph），执行图挂磁盘 saver。
节点一律从门面取（`_facade.xxx`），保证测试 patch `agent_graph.<node>` 仍生效。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from . import agent_graph as _facade


def _build_graph() -> Any:
    g = StateGraph(_facade.AgentState)
    g.add_node("supervisor", _facade.supervisor)
    g.add_node("record", _facade.record)
    g.add_node("nl_cancel", _facade.nl_cancel)
    g.add_node("memory", _facade.memory)
    g.add_node("action", _facade.action)
    g.add_node("studio_admin", _facade.studio_admin)
    g.add_node("general", _facade.general)
    g.add_node("enterprise", _facade.enterprise)
    g.add_node("collect_market", _facade.collect_market)
    g.add_node("collect_ledger", _facade.collect_ledger)
    g.add_node("risk", _facade.risk)
    g.add_node("finalize", _facade.finalize)

    g.add_edge(START, "supervisor")
    g.add_conditional_edges(
        "supervisor",
        _facade._supervisor_route,
        {
            "record": "record",
            "nl_cancel": "nl_cancel",
            "memory": "memory",
            "general": "general",
            "enterprise": "enterprise",
            "action": "action",
            "studio_admin": "studio_admin",
            "finance": "collect_market",
        },
    )
    # 多智能体管线：市场 agent → 账本 agent → 风控 agent → 成文 agent
    # （顺序边：单连接 aiosqlite 不支持跨节点并发读写，结构并行、执行串行）
    g.add_edge("collect_market", "collect_ledger")
    g.add_edge("collect_ledger", "risk")
    g.add_edge("risk", "finalize")
    g.add_edge("record", END)
    g.add_edge("nl_cancel", END)
    g.add_edge("memory", END)
    g.add_edge("action", END)
    g.add_edge("studio_admin", END)
    g.add_edge("general", END)
    g.add_edge("enterprise", END)
    g.add_edge("finalize", END)
    # 仅声明图结构，不在此编译：结构图（get_graph）挂 MemorySaver，执行图
    # （_acquire_exec_graph）挂磁盘 AsyncSqliteSaver，两者共享同一节点/路由定义。
    return g

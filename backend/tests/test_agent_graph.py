"""LangGraph 多智能体编排图测试：图结构、路由、各 agent 节点事件与产物、图内降级。

设计约束（与既有 142 项测试共同构成回归防线）：
- 图是 service.run_question 的唯一执行路径（无旧顺序双轨）
- 确定性模式下事件序列与旧流程完全一致（supervisor→market→ledger→risk→finalize）
- agent 模式不发 step、只发 agent_step；通用路径不发任何内部步骤
- agent 工具循环失败在成文节点内降级确定性模板（图内降级，不中断）
"""

from __future__ import annotations

from typing import Any

import pytest
from app import agent as agent_mod
from app import agent_graph, analysis, service

# ---------------------------------------------------------------------------
# 图结构
# ---------------------------------------------------------------------------


def test_graph_structure_has_all_agent_nodes() -> None:
    """主流 agent 框架的多智能体结构：supervisor + 5 个专门 agent 节点。"""
    g = agent_graph.get_graph()
    names = {n for n in g.get_graph().nodes}
    assert {"supervisor", "collect_market", "collect_ledger", "risk", "finalize", "record", "memory", "general"} <= names


def test_supervisor_routes_to_seven_branches() -> None:
    """supervisor 条件路由：记账 / 审批取消 / 记忆 / 通用 / 动作 / Studio 配置 / 财务七条支路。"""
    g = agent_graph.get_graph().get_graph()
    sup_edges = [e for e in g.edges if e.source == "supervisor"]
    assert len(sup_edges) == 7, f"supervisor 应有 7 条条件边，实际 {len(sup_edges)}"
    assert {e.target for e in sup_edges} == {
        "record", "nl_cancel", "memory", "general", "action", "studio_admin", "collect_market"
    }


# ---------------------------------------------------------------------------
# 事件与产物（确定性模式）
# ---------------------------------------------------------------------------


async def _collect(run: Any, question: str, thread_id: str | None = None, lang: str = "zh") -> tuple[list[dict], dict]:
    events: list[dict[str, Any]] = []

    async def emit(ev: dict[str, Any]) -> None:
        events.append(ev)

    result = await run(question, emit, thread_id, lang)
    return events, result


async def test_deterministic_finance_step_sequence(temp_db, monkeypatch) -> None:
    """确定性财务路径：完成态步骤顺序与旧流程一致，指标来自本地内核。"""
    async def _no_llm() -> bool:
        return False
    monkeypatch.setattr(service.llm, "llm_available", _no_llm)
    events, result = await _collect(service.run_question, "我的组合怎么样？")
    steps = [e for e in events if e["type"] == "step" and e["phase"] == "done"]
    # 组合 → 仅 market 视角：supervisor → 市场 agent → 风控 agent → 成文 agent
    assert [s["id"] for s in steps] == ["supervisor", "market", "risk", "finalize"]
    assert result["route"] == "market"
    assert result["llm"] == "template"
    assert "total_market_value" in result["metrics"]
    assert result["level"] in ("L1 洞察", "L2 建议")


async def test_deterministic_template_follows_language(temp_db, monkeypatch) -> None:
    """确定性模板成文跟随 lang：zh 中文、en 英文（语言统一收尾）。"""
    async def _no_llm() -> bool:
        return False
    monkeypatch.setattr(service.llm, "llm_available", _no_llm)
    _, zh = await _collect(service.run_question, "我的组合怎么样？", None, "zh")
    _, en = await _collect(service.run_question, "我的组合怎么样？", None, "en")
    assert zh["answer"] and en["answer"]
    # 中文模板含「总市值」，英文模板含 portfolio value
    assert ("总市值" in zh["answer"] or "组合" in zh["answer"])
    assert "portfolio" in en["answer"] or "Portfolio" in en["answer"]


async def test_deterministic_market_only_skips_ledger(temp_db, monkeypatch) -> None:
    """只问持仓：市场 agent 取数，账本 agent 空转不发事件。"""
    async def _no_llm() -> bool:
        return False
    monkeypatch.setattr(service.llm, "llm_available", _no_llm)
    events, result = await _collect(service.run_question, "股票最近涨了吗")
    steps = [e for e in events if e["type"] == "step"]
    ids = [s["id"] for s in steps]
    assert "market" in ids and "ledger" not in ids
    assert result["route"] == "market"


async def test_general_path_no_steps(temp_db, monkeypatch) -> None:
    """通用 agent：不带财务步骤、不带财务分级、模板兜底文案。"""
    async def _no_llm() -> bool:
        return False
    monkeypatch.setattr(service.llm, "llm_available", _no_llm)
    events, result = await _collect(service.run_question, "帮我写一段周末计划")
    assert not [e for e in events if e["type"] == "step"]
    assert result["route"] == "general"
    assert result["level"] == ""


async def test_record_path_no_model(temp_db) -> None:
    """记账 agent：规则秒回入账（无需模型），事件含识别/已入账两步。"""
    events, result = await _collect(service.run_question, "昨天打车 32 元")
    steps = [e for e in events if e["type"] == "step"]
    assert [s["id"] for s in steps] == ["nl", "nl"]
    assert result["route"] == "nl_add"
    assert result["level"] == "已记账"


# ---------------------------------------------------------------------------
# agent 模式（模型自主调工具）
# ---------------------------------------------------------------------------


async def test_agent_mode_uses_tool_loop_and_no_steps(temp_db, monkeypatch) -> None:
    """已接模型：supervisor 判定 agent 模式，成文节点走工具循环（agent_step 而非 step）。"""
    calls: list[dict] = []

    async def fake_run_agent(question: str, emit, history, lang="zh"):
        await emit({
            "type": "agent_step", "name": "get_market_view",
            "args": {"symbols": ["600000"]}, "summary": "总市值 100,000 元",
        })
        await emit({
            "type": "agent_step", "name": "get_risk_flags",
            "args": {}, "summary": "未发现明显风险项",
        })
        calls.append({"question": question, "history": history})
        return {"answer": "你的组合总市值 100,000 元，表现平稳。", "tools_used": ["get_market_view", "get_risk_flags"], "steps": []}

    async def _has_llm() -> bool:
        return True
    monkeypatch.setattr(service.llm, "llm_available", _has_llm)
    monkeypatch.setattr(agent_mod, "run_agent", fake_run_agent)
    events, result = await _collect(service.run_question, "我的组合怎么样？")
    steps = [e for e in events if e["type"] == "step"]
    agent_steps = [e for e in events if e["type"] == "agent_step"]
    assert not steps, "agent 模式不应发内部 step"
    assert [a["name"] for a in agent_steps] == ["get_market_view", "get_risk_flags"]
    assert result["llm"] == "llm"
    assert result["tools"] == ["get_market_view", "get_risk_flags"]
    assert result["answer"].endswith(analysis.DISCLAIMER) or analysis.DISCLAIMER in result["answer"]


async def _raise_unavailable(*a: Any, **k: Any) -> dict:
    raise agent_mod.AgentUnavailable()


async def test_agent_mode_fallback_to_template_on_unavailable(temp_db, monkeypatch) -> None:
    """模型可用但工具循环抛 AgentUnavailable → 成文节点内降级确定性模板（图内降级）。"""
    async def _has_llm() -> bool:
        return True
    monkeypatch.setattr(service.llm, "llm_available", _has_llm)
    monkeypatch.setattr(agent_mod, "run_agent", _raise_unavailable)

    _, result = await _collect(service.run_question, "我的组合怎么样？")
    # 图内降级：supervisor 判定 agent 模式 → 成文节点 agent 循环失败 → 确定性模板成文
    assert result["llm"] == "template"
    assert "total_market_value" in result["metrics"]


# ---------------------------------------------------------------------------
# 图异常语义：诚实报错（由 API 层转 SSE error 事件），无旧流程兜底
# ---------------------------------------------------------------------------


async def test_graph_failure_propagates_as_error(temp_db, monkeypatch) -> None:
    """图执行失败 → run_question 如实抛出（旧顺序双轨已移除，不静默降级）。"""
    async def _no_llm() -> bool:
        return False
    monkeypatch.setattr(service.llm, "llm_available", _no_llm)

    async def boom(*a, **k):
        raise RuntimeError("graph broken")

    monkeypatch.setattr(agent_graph, "run_graph", boom)
    with pytest.raises(RuntimeError, match="graph broken"):
        await _collect(service.run_question, "我的组合怎么样？")

"""深度能力回归：上下文压缩安全、按路由收窄工具面、长任务后台可取消。

这组测试都是行为测试，不测“函数存在”：
- 压缩后不许出现孤立的 tool 消息（否则真实端点直接 400）；
- market 路由不许再暴露 ledger 专属工具；
- 后台长任务点取消后，协程必须真的停，状态不许被后续写入覆盖成 done。
"""

from __future__ import annotations

import asyncio

import pytest
from app import db, longtask
from app.agent import select_task_model
from app.agent_toolset import build_toolset
from app.context import compact_messages


def _tool_turns(turns: int = 6, tool_chars: int = 1200) -> list[dict]:
    msgs = [{"role": "system", "content": "system"}]
    for i in range(turns):
        msgs.append({"role": "user", "content": f"问题{i} " + "背景" * 100})
        msgs.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": f"c{i}", "type": "function",
                "function": {"name": "get_market_view", "arguments": "{}"},
            }],
        })
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": "结果" * tool_chars})
    msgs.append({"role": "user", "content": "最后一个问题"})
    return msgs


@pytest.mark.asyncio
async def test_compaction_never_leaves_orphan_tool_message():
    msgs = _tool_turns()
    result = await compact_messages(msgs, max_tokens=3000, reserve_recent=3, use_llm=False)
    assert result["compacted"] is True
    compacted = result["messages"]
    open_calls: set[str] = set()
    for msg in compacted:
        if msg.get("role") == "assistant":
            open_calls = {tc["id"] for tc in (msg.get("tool_calls") or [])}
        elif msg.get("role") == "user":
            open_calls = set()
        elif msg.get("role") == "tool":
            assert msg.get("tool_call_id") in open_calls, "压缩后出现孤立 tool 结果"


@pytest.mark.asyncio
async def test_route_narrows_tool_surface():
    market_schemas, market_map, _, _ = await build_toolset(None, None, route="market")
    ledger_schemas, ledger_map, _, _ = await build_toolset(None, None, route="ledger")
    market_names = {s["function"]["name"] for s in market_schemas}
    ledger_names = {s["function"]["name"] for s in ledger_schemas}
    assert "get_market_view" in market_names
    assert "get_ledger_view" not in market_names
    assert "get_ledger_view" in ledger_names
    assert "get_kline" not in ledger_names
    assert "get_ledger_view" not in market_map
    assert "get_kline" not in ledger_map


@pytest.fixture(autouse=True)
async def _data_dir(temp_db):
    yield


@pytest.mark.asyncio
async def test_background_longtask_cancel_really_stops(monkeypatch):
    from app import llm

    started = asyncio.Event()

    async def fake_available() -> bool:
        return True

    async def slow_chat(messages, *, model=None, temperature=0.3, timeout=60.0):
        started.set()
        await asyncio.sleep(30)
        return "不应写入的产物"

    monkeypatch.setattr(llm, "llm_available", fake_available)
    monkeypatch.setattr(llm, "litellm_chat", slow_chat)

    task = await longtask.create_task(
        "program", "后台取消", "验证取消", stages=["长阶段"], success_criteria="不得产出"
    )
    assert task["success_criteria"] == "不得产出"
    snapshot = await longtask.start_task(task["id"])
    assert snapshot["status"] in ("pending", "running")
    await asyncio.wait_for(started.wait(), timeout=2)
    longtask.cancel_task(task["id"])
    await asyncio.sleep(0.2)
    final = longtask.get_task(task["id"])
    assert final["status"] == "cancelled"
    assert all(s["status"] != "done" for s in final["stages"])
    assert all(s["status"] != "running" for s in final["stages"])
    assert any(s["status"] == "cancelled" for s in final["stages"])
    cancelled = next(s for s in final["stages"] if s["status"] == "cancelled")
    assert cancelled.get("attempts", 0) >= 1


@pytest.mark.asyncio
async def test_run_history_replays_tool_steps():
    """历史回看不能只剩一段答案：工具轨迹要随 run 落库并可读回。"""
    await db.save_run(
        "thread-replay",
        "看看持仓",
        "总市值 10 万",
        "L1",
        tools=["get_market_view"],
        steps=[{"name": "get_market_view", "args": {}, "summary": "总市值 100,000 元"}],
    )
    runs = await db.list_runs("thread-replay", limit=5)
    assert runs
    assert runs[0]["steps"][0]["name"] == "get_market_view"
    assert runs[0]["steps"][0]["summary"].startswith("总市值")


def test_task_model_routing_picks_by_difficulty():
    st = {"model_route_economy": "flash-mini", "model_route_deep": "reasoner-pro"}
    assert select_task_model("看看持仓", "market", False, "standard", st) == "flash-mini"
    assert select_task_model("看看持仓", "market", False, "concise", st) == "flash-mini"
    assert select_task_model("请给我一份完整的资产配置研究报告", "both", False, "detailed", st) == "reasoner-pro"
    assert select_task_model("深研一下", "both", True, "standard", st) == "reasoner-pro"
    assert select_task_model("随便问一句", "both", False, "standard", st) == ""

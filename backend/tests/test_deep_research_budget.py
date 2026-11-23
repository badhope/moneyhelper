"""4.16.45：深研不是「改个提示词」——检索次数与执行层硬上限都要真实生效。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from app import agent


def _tool_call(call_id: str, name: str, args: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def _assistant(content: str = "", tool_calls: list | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))]
    )


class _FakeClient:
    def __init__(self, script: list[Any]) -> None:
        self.script = script
        self.calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            async def _stream():
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="深研完成"))]
                )
            return _stream()
        idx = min(len(self.calls) - 1, len(self.script) - 1)
        return self.script[idx]


@pytest.fixture
async def deep_client(monkeypatch, temp_db):
    searches: list[str] = []

    async def fake_search(args: dict[str, Any]) -> str:
        searches.append(str(args.get("q") or ""))
        return f"搜索结果：{args.get('q')}"

    async def fake_build_toolset(tools_list, impl_map):
        schema = {
            "type": "function",
            "function": {"name": "web_search", "description": "联网搜索", "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}},
        }
        return [schema], {}, {"web_search": fake_search}, {}

    monkeypatch.setattr("app.agent_toolset.build_toolset", fake_build_toolset)
    monkeypatch.setattr(agent.llm, "_config", lambda: _cfg())
    script = [
        _assistant(tool_calls=[_tool_call(f"c{i}", "web_search", {"q": f"角度{i}"})])
        for i in range(8)
    ]
    client = _FakeClient(script)
    monkeypatch.setattr(agent.llm, "_get_client", lambda *a, **kw: client)
    return client, searches


async def _cfg():
    return {"model": "test-model", "key": "k", "base": "http://fake", "litellm_model": "openai/test"}


async def _emit(_e: dict) -> None:
    return None


@pytest.mark.asyncio
async def test_deep_research_caps_at_six_searches(deep_client) -> None:
    client, searches = deep_client
    result = await agent.run_agent(
        "给我一份完整的行业研究 ［联网搜索］",
        _emit,
        deep_research=True,
        tools_list=[{"type": "function", "function": {"name": "web_search"}}],
    )
    assert result["answer"] == "深研完成"
    assert len(searches) == 6, "深研最多 6 次检索，执行层必须真的拦住第 7、8 次"
    # 第 7 次之后工具面被摘掉；调用参数里不应再出现 web_search
    later = client.calls[6:]
    names = [
        (t.get("function") or {}).get("name")
        for c in later
        for t in (c.get("tools") or [])
    ]
    assert "web_search" not in names

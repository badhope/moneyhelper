"""Studio API 与运行时接线：对话内配置、权限拦截、导入、市场、内置工具生效。

这些测试锁的是用户可感知的承诺：
- 对话里说「添加技能 …」真的会写进配置并回执
- 权限不是摆设：标准/严格模式下写操作被 403
- 核心项永远不可改（即使全面放开）
- 导入坏文件必须给出字段级错误
- 内置工具/主角色真正进入系统提示与工具面
"""

from __future__ import annotations

import io
import zipfile

import httpx
import pytest
from app import agent, agent_config, main, service
from app.studio import internal_tools, store


@pytest.fixture
async def client(temp_db, monkeypatch) -> httpx.AsyncClient:
    async def _no_llm() -> bool:
        return False

    monkeypatch.setattr(service.llm, "llm_available", _no_llm)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac


async def test_chat_command_api_creates_skill(client) -> None:
    r = await client.post(
        "/api/studio/chat-command",
        json={"text": "添加技能 定投提醒：每周日检查定投计划"},
    )
    data = r.json()
    assert data["ok"] is True and data["matched"] is True
    assert "定投提醒" in data["answer"]
    skills = {a["id"]: a for a in (await client.get("/api/studio/skills")).json()["assets"]}
    created = [a for a in skills.values() if a["name"] == "定投提醒"]
    assert created and created[0]["enabled"] is True


async def test_ask_route_handles_studio_command(client) -> None:
    """SSE 问答接口同样命中配置分支（不是只有专用端点能用）。"""
    async with client.stream(
        "POST",
        "/api/ask",
        json={"question": "添加约束 不推荐个股：只描述风险，不给买卖建议", "thread_id": "t1"},
    ) as resp:
        text = "".join([chunk async for chunk in resp.aiter_text()])
    assert "已创建约束" in text
    rules = {a["name"]: a for a in (await client.get("/api/studio/rules")).json()["assets"]}
    assert "不推荐个股" in rules


async def test_chat_admin_blocked_in_standard_mode(client) -> None:
    await client.put("/api/studio/permissions", json={"mode": "standard"})
    r = await client.post(
        "/api/studio/chat-command", json={"text": "添加技能 x：y"}
    )
    data = r.json()
    assert data["ok"] is False and data.get("disabled") is True
    r2 = await client.post("/api/studio/prompts", json={"name": "x", "content": "y"})
    assert r2.status_code == 403
    await client.put(
        "/api/studio/permissions",
        json={"mode": "open", "allow_chat_admin": True, "allow_cli_admin": True},
    )


async def test_core_guard_rejects_locked_keys(client) -> None:
    r = await client.post("/api/studio/core-guard", json={"key": "approval_threshold"})
    data = r.json()
    assert data["ok"] is False and data["allowed"] is False
    assert "核心安全项" in data["error"]
    r2 = await client.post("/api/studio/core-guard", json={"key": "theme"})
    assert r2.json()["allowed"] is True


async def test_import_upload_reports_zip_errors(client) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("good.md", "---\nname: good-skill\ndescription: ok\n---\n\n正文")
        zf.writestr("bad.json", "{oops")
    r = await client.post(
        "/api/studio/import",
        files={"file": ("pack.zip", buf.getvalue(), "application/zip")},
    )
    data = r.json()
    assert data["saved"] and data["saved"][0]["name"] == "good-skill"
    assert data["errors"] and data["errors"][0]["file"] == "bad.json"


async def test_import_markdown_as_kind(client) -> None:
    md = "---\nname: grant-writing\ndescription: 基金申请书\n---\n\n# 申请书\n1. 科学问题"
    r = await client.post(
        "/api/studio/import",
        files={"file": ("g.md", md.encode(), "text/markdown")},
        data={"kind": "skills"},
    )
    data = r.json()
    assert data["ok"] and data["saved"][0]["name"] == "grant-writing"


async def test_market_install_mcp_defaults(client, tmp_path, monkeypatch) -> None:
    """远程 HTTP MCP 装好即启用；stdio MCP 装好默认停用（依赖 npx/uvx）。"""
    from app import mcp_client

    monkeypatch.setattr(mcp_client, "MCP_CFG", tmp_path / "mcp.json")
    monkeypatch.setattr(mcp_client, "_discover_cache", None)
    mcp_client._servers.clear()
    r = await client.post("/api/studio/market/install", json={"id": "mcp-deepwiki"})
    assert r.json()["ok"] is True
    servers = (await client.get("/api/mcp/servers")).json()["servers"]
    assert servers and servers[0]["enabled"] is True

    r2 = await client.post("/api/studio/market/install", json={"id": "mcp-fetch"})
    assert r2.json()["ok"] is True
    servers2 = {s["name"]: s for s in (await client.get("/api/mcp/servers")).json()["servers"]}
    assert servers2["fetch"]["enabled"] is False

    r3 = await client.post("/api/mcp/servers/fetch/toggle", json={"enabled": True})
    assert r3.json()["ok"] is True


async def test_studio_prompt_reaches_agent_system(temp_db, monkeypatch) -> None:
    """系统提示必须包含 Studio 默认提示词/约束/Hook 注入（真正运用于内部）。"""
    prompt = await store.build_system_prompt("BASE")
    assert "禁止编造数字" in prompt and "当前日期" in prompt
    captured: dict = {}

    async def _fake_stream(client, cfg, messages, tools, emit):
        captured["messages"] = messages
        return "ok"

    monkeypatch.setattr(agent, "_stream_final_answer", _fake_stream)
    monkeypatch.setattr(agent.llm, "_config", lambda: _async({"model": "m", "litellm_model": "m", "base": "", "key": ""}))

    class _Msg:
        content = ""
        tool_calls = None

    class _Choice:
        message = _Msg()

    class _Resp:
        def __init__(self) -> None:
            self.choices = [_Choice()]

    async def _create(**kwargs):
        return _Resp()

    class _Completions:
        async def create(self, **kwargs):
            return await _create(**kwargs)

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    monkeypatch.setattr(agent.llm, "_get_client", lambda cfg, timeout=60.0: _Client())
    await agent.run_agent("你好", lambda ev: _noop())
    system_text = captured["messages"][0]["content"]
    assert "禁止编造数字" in system_text


async def _noop(*_a, **_k):
    return None


def _async(value):
    async def _inner():
        return value

    return _inner()


async def test_internal_tool_toggle_removes_from_tool_surface(temp_db, monkeypatch) -> None:
    enabled = await store.internal_tools_enabled()
    assert enabled["stats_summary"] is True
    await store.set_internal_tool("stats_summary", False)
    enabled2 = await store.internal_tools_enabled()
    assert "stats_summary" not in enabled2
    # 工具实现本身仍可调用（关闭只影响工具面暴露）
    assert internal_tools.run_internal_tool("stats_summary", {"values": [1, 2, 3]})


async def test_primary_role_enters_system_prompt(temp_db) -> None:
    await store.set_primary_role("research_scientist")
    prompt = await store.build_system_prompt("BASE")
    assert "科研助手" in prompt and "不编造文献" in prompt


async def test_defaults_merge_into_existing_config(temp_db) -> None:
    cfg = await agent_config.get_config()
    cfg["agents"] = {"supervisor": cfg["agents"]["supervisor"]}
    cfg["skills"] = {}
    await agent_config.update_config(cfg)
    merged = await agent_config.get_config()
    assert len(merged["agents"]) >= 8 and len(merged["skills"]) >= 8


async def test_diagnostics_lists_real_checks(client) -> None:
    data = (await client.get("/api/studio/diagnostics")).json()
    assert "checks" in data
    ids = {c["id"] for c in data["checks"]}
    assert {"default_pack", "permission_mode", "mcp_config", "runtime", "studio_assets"} <= ids


async def test_watchdog_run(client) -> None:
    data = (await client.post("/api/studio/watchdog/run")).json()
    assert data["ok"] is True and isinstance(data["findings"], list)


async def test_format_spec(client) -> None:
    data = (await client.get("/api/studio/format-spec")).json()
    assert "skill_md" in data["spec"] and "zip" in data["spec"]


async def test_template_endpoint(client) -> None:
    data = (await client.get("/api/studio/templates/hooks")).json()
    assert data["template"]["event"] == "pre_tool"


async def test_chat_command_with_schedule_persists_action(client) -> None:
    """对话里带时间描述 → 技能落库时带上定时动作（真正可被调度）。"""
    r = await client.post(
        "/api/studio/chat-command",
        json={"text": "添加技能 周报助手：每周五下午 5:30 汇总本周收支"},
    )
    data = r.json()
    assert data["ok"] is True
    skills = {a["id"]: a for a in (await client.get("/api/studio/skills")).json()["assets"]}
    created = next(a for a in skills.values() if a["name"] == "周报助手")
    assert created["action"]["time"] == "17:30"
    assert created["action"]["weekdays"] == [4]


async def test_agent_config_rejects_below_floor_threshold(client) -> None:
    """保存 agent 配置时低于下限要钳制并给出 warning（不是静默通过）。"""
    cfg = (await client.get("/api/agent-config")).json()["config"]
    cfg.setdefault("defaults", {})["approval_threshold"] = 1
    r = await client.post("/api/agent-config", json={"config": cfg})
    data = r.json()
    assert data["ok"] is True
    assert any("审批阈值" in w for w in data.get("warnings", []))
    cfg2 = (await client.get("/api/agent-config")).json()["config"]
    assert cfg2["defaults"]["approval_threshold"] == 100


async def test_primary_role_tool_allowlist_filters_tools(temp_db, monkeypatch) -> None:
    """角色「工具白名单」必须真正裁剪工具面（之前只存不用）。"""
    from app import agent, agent_config

    cfg = await agent_config.get_config()
    cfg["agents"]["supervisor"]["tools"] = ["get_market_view"]
    await agent_config.update_config(cfg)
    await store.set_primary_role("supervisor")

    captured: dict = {}

    async def _fake_stream(client, cfg_, messages, tools, emit):
        captured["tools"] = [t["function"]["name"] for t in tools]
        return "ok"

    class _Msg:
        content = ""
        tool_calls = None

    class _Choice:
        message = _Msg()

    class _Resp:
        def __init__(self):
            self.choices = [_Choice()]

    class _Completions:
        async def create(self, **kwargs):
            return _Resp()

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    async def _cfg():
        return {"model": "m", "litellm_model": "m", "base": "", "key": ""}

    monkeypatch.setattr(agent.llm, "_config", _cfg)
    monkeypatch.setattr(agent.llm, "_get_client", lambda c, timeout=60.0: _Client())
    monkeypatch.setattr(agent, "_stream_final_answer", _fake_stream)
    await agent.run_agent("测试", lambda ev: _noop())
    assert captured["tools"] == ["get_market_view"]


async def test_role_temperature_applied(temp_db, monkeypatch) -> None:
    """角色温度必须进入模型调用参数（之前写死 0.2）。"""
    from app import agent, agent_config

    captured: dict = {}

    class _Completions:
        async def create(self, **kwargs):
            captured["temperature"] = kwargs.get("temperature")

            class _M:
                content = ""
                tool_calls = None

            class _C:
                message = _M()

            class _R:
                def __init__(self):
                    self.choices = [_C()]

            return _R()

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    async def _cfg():
        return {"model": "m", "litellm_model": "m", "base": "", "key": ""}

    monkeypatch.setattr(agent.llm, "_config", _cfg)
    monkeypatch.setattr(agent.llm, "_get_client", lambda c, timeout=60.0: _Client())
    monkeypatch.setattr(agent, "_stream_final_answer", lambda *a, **k: _answer("ok"))

    cfg = await agent_config.get_config()
    cfg["agents"]["supervisor"]["temperature"] = 0.75
    await agent_config.update_config(cfg)
    await store.set_primary_role("supervisor")
    await agent.run_agent("测试", lambda ev: _noop())
    assert captured["temperature"] == 0.75


async def _answer(text: str):
    return text


async def test_cli_channel_permission_separate_from_chat(client) -> None:
    """CLI 与对话的权限开关独立：只关对话时 CLI 仍可写。"""
    await client.put(
        "/api/studio/permissions",
        json={"mode": "open", "allow_chat_admin": False, "allow_cli_admin": True},
    )
    chat = (await client.post("/api/studio/chat-command", json={"text": "添加技能 a：b"})).json()
    assert chat["ok"] is False and chat.get("disabled") is True
    from app.studio import commands

    cli = await commands.handle_question("添加技能 cli_only：只给 CLI 用", channel="cli")
    assert cli and cli["ok"] is True
    await client.put(
        "/api/studio/permissions",
        json={"mode": "open", "allow_chat_admin": True, "allow_cli_admin": True},
    )


async def test_tool_allowlist_also_filters_mcp_tools(temp_db, monkeypatch) -> None:
    """白名单必须收口在 MCP 合并之后：否则 mcp__* 工具会绕过角色白名单。"""
    from app import agent, agent_config, mcp_client

    async def _fake_refresh(force: bool = False):
        return [
            {
                "type": "function",
                "function": {
                    "name": "mcp__evil",
                    "description": "外部工具",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

    monkeypatch.setattr(mcp_client, "refresh", _fake_refresh)
    cfg = await agent_config.get_config()
    cfg["agents"]["supervisor"]["tools"] = ["get_market_view"]
    await agent_config.update_config(cfg)
    await store.set_primary_role("supervisor")

    captured: dict = {}

    async def _fake_stream(client, cfg_, messages, tools, emit):
        captured["tools"] = [t["function"]["name"] for t in tools]
        return "ok"

    class _Msg:
        content = ""
        tool_calls = None

    class _Choice:
        message = _Msg()

    class _Resp:
        def __init__(self):
            self.choices = [_Choice()]

    class _Completions:
        async def create(self, **kwargs):
            return _Resp()

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    async def _cfg():
        return {"model": "m", "litellm_model": "m", "base": "", "key": ""}

    monkeypatch.setattr(agent.llm, "_config", _cfg)
    monkeypatch.setattr(agent.llm, "_get_client", lambda c, timeout=60.0: _Client())
    monkeypatch.setattr(agent, "_stream_final_answer", _fake_stream)
    await agent.run_agent("测试", lambda ev: _noop())
    assert captured["tools"] == ["get_market_view"]

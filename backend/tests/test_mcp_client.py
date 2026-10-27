"""MCP 客户端端到端测试：用一个真实 MCP StreamableHTTP 服务器验证客户端 discover/call。

服务器用标准库 http.server 实现协议核心（initialize / tools/list / tools/call，
外加规范要求的 GET→405 与 notification→202），客户端 mcp_client.refresh 拉取工具
→ call_mcp_tool 调用，验证官方 mcp SDK 全链路真实可用。
"""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from app import db, mcp_client

# ---------------------------------------------------------------------------
# 一个真实的最小 MCP StreamableHTTP 服务器（本地代码起服务）
# ---------------------------------------------------------------------------


class _MCPHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D401 — 静默
        pass

    def _send(self, obj: dict[str, Any]) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reply(self, payload: dict[str, Any], result: Any) -> None:
        self._send({"jsonrpc": "2.0", "id": payload.get("id"), "result": result})

    def do_GET(self):  # noqa: N802
        # MCP 规范：不支持 GET SSE 流的服务器应返回 405，客户端需容忍
        self.send_response(405)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if "id" not in payload or payload.get("id") is None:
            # notification（如 notifications/initialized）：无需响应，返回 202
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        method = payload.get("method")
        if method == "initialize":
            self._reply(payload, {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test-mcp", "version": "1.0"},
            })
        elif method == "tools/list":
            self._reply(payload, {"tools": [
                {"name": "echo", "description": "回显文本",
                 "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
                {"name": "add", "description": "两个数相加",
                 "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]}},
            ]})
        elif method == "tools/call":
            params = payload.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            if name == "echo":
                content = f"echo:{args.get('text', '')}"
            elif name == "add":
                content = f"sum={args.get('a', 0) + args.get('b', 0)}"
            else:
                content = f"unknown:{name}"
            self._reply(payload, {"content": [{"type": "text", "text": content}]})
        else:
            self._send({"jsonrpc": "2.0", "id": payload.get("id"), "error": {"code": -32601, "message": "method not found"}})


@pytest.fixture
async def mcp_up(tmp_path, monkeypatch):
    """起本地 MCP 服务器 + 写配置 + 指向 mcp_client。"""
    # 1) 起 HTTP 服务
    httpd = HTTPServer(("127.0.0.1", 0), _MCPHandler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    # 2) 配置
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({
        "servers": [{"name": "test", "url": f"http://127.0.0.1:{port}/mcp"}]
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(mcp_client, "MCP_CFG", cfg)
    mcp_client._servers.clear()
    yield
    httpd.shutdown()
    mcp_client._servers.clear()


async def test_mcp_refresh_discovers_tools(mcp_up) -> None:
    """refresh 能发现 MCP 服务器工具并转成 function schema。"""
    schemas = await mcp_client.refresh()
    names = {s["function"]["name"] for s in schemas}
    assert {"mcp__echo", "mcp__add"} <= names
    echo = next(s for s in schemas if s["function"]["name"] == "mcp__echo")
    assert "text" in echo["function"]["parameters"]["properties"]


async def test_mcp_call_tool(mcp_up) -> None:
    """call_mcp_tool 真实调用服务器工具并返回文本结果。"""
    await mcp_client.refresh()  # 先建立会话
    r = await mcp_client.call_mcp_tool("test", "echo", {"text": "你好"})
    assert r == "echo:你好"
    r2 = await mcp_client.call_mcp_tool("test", "add", {"a": 3, "b": 4})
    assert r2 == "sum=7"


async def test_mcp_resolve(mcp_up) -> None:
    """resolve_mcp_tool 能识别 MCP 工具名。"""
    await mcp_client.refresh()
    assert mcp_client.resolve_mcp_tool("mcp__add") == ("test", "mcp__add")
    assert mcp_client.resolve_mcp_tool("not_a_tool") is None

# ---------------------------------------------------------------------------
# 自环验证（M2.2）：Moneyhelper 自己的 MCP Server 走 Streamable HTTP 能被官方 SDK 调通
# ---------------------------------------------------------------------------




@pytest.fixture
async def moneyhelper_mcp_up(tmp_path, monkeypatch):
    """起一个只挂 MCP 的真实 ASGI 服务，指到临时库，供自环调用。

    与上面的 mcp_up 不同：这里跑的是**Moneyhelper 自己的** mcp_server，验证的是
    "我们暴露出去的工具"本身可用，而不是客户端解析逻辑。
    """
    import uvicorn
    from app import mcp_server
    from fastapi import FastAPI

    # 与 main.py 同一套契约：holder 保存"当前"子应用，lifespan 写入新实例，
    # mount 的路由通过动态转发读取。这样 session manager 每次 lifespan 重建，
    # 不会踩 "run() can only be called once per instance"。
    holder: dict = {"built": None}

    @asynccontextmanager
    async def _lifespan(_app):
        built = mcp_server.build_asgi()
        holder["built"] = built
        async with built[0].lifespan(_app):
            yield

    app = FastAPI(lifespan=_lifespan)
    mcp_server.mount_to_app(app, holder)

    # 端口 0 让系统分配，避免与本地开发服务冲突。
    # lifespan 必须开启：Streamable HTTP 的 session manager 在 ASGI lifespan 里
    # 启动 task group，关掉会报 "Task group is not initialized"。
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.05)
    assert server.started, "MCP 服务启动超时"
    port = server.servers[0].sockets[0].getsockname()[1]

    cfg = tmp_path / "mcp.json"
    cfg.write_text(
        json.dumps({"servers": [{"name": "self", "url": f"http://127.0.0.1:{port}/mcp"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(mcp_client, "MCP_CFG", cfg)
    mcp_client._servers.clear()
    try:
        yield port
    finally:
        server.should_exit = True
        await task
        mcp_client._servers.clear()


async def test_self_mcp_end_to_end(moneyhelper_mcp_up, temp_db) -> None:
    """Moneyhelper 自己的 MCP Server 走 Streamable HTTP 的完整验收（M2.2）。

    三件事一次做完，合并成一个测试是刻意为之：
    FastMCP 的 server 实例是模块级单例，其内部锁/事件在第一次启动时绑定到
    当时的 event loop；pytest-asyncio 每个测试用独立循环，第二个测试复用
    同一实例会报 "bound to a different event loop"。这是测试基建限制，
    不是产品缺陷 —— 生产进程只有一个循环。

    验收内容：
    1. 工具面完整：暴露的工具 = 共享真源登记的全部工具
    2. schema 可用：每个工具都带描述，每个参数都带说明
    3. 三件套走通：查询 → 记账 → 再查询（数字随之变化）
    """
    from app import tool_schemas as ts

    await mcp_client.refresh()
    schemas = await mcp_client.refresh()
    by_name = {s["function"]["name"].removeprefix("mcp__"): s["function"] for s in schemas}

    # 1) 工具面完整
    expected = set(ts.TOOL_INPUT_MODELS) | set(ts.MCP_ONLY_INPUT_MODELS)
    assert set(by_name) == expected, (
        f"缺少: {expected - set(by_name)}；多出: {set(by_name) - expected}"
    )

    # 2) schema 可用：描述齐全
    for name, fn in by_name.items():
        assert fn["description"], f"{name} 缺工具描述"
        for pname, prop in fn["parameters"].get("properties", {}).items():
            assert prop.get("description"), f"{name}.{pname} 缺参数说明"

    # 3) /mcp 必须无斜杠即用（mount 组合的回归点）
    import httpx

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "probe", "version": "1"},
        },
    }
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as c:
        r = await c.post(
            f"http://127.0.0.1:{moneyhelper_mcp_up}/mcp",
            json=payload,
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert r.status_code == 200, f"/mcp 无斜杠不可用：{r.status_code}"
        assert "protocolVersion" in r.text

        # 注意：elicitation 是**客户端**能力（ClientCapabilities.elicitation），
        # 服务端 ServerCapabilities 里没有这个字段。所以这里只断言服务端
        # 正常完成了握手；审批能否弹出取决于客户端是否声明支持，
        # 不支持的客户端在 _confirm_write 里 fail-closed。
        data_line = next(ln for ln in r.text.splitlines() if ln.startswith("data:"))
        caps = json.loads(data_line[len("data:"):].strip())["result"]["capabilities"]
        assert "tools" in caps

    # 4) 三件套：查询 → 记账 → 再查询
    before = json.loads(await mcp_client.call_mcp_tool("self", "get_ledger_view", {}))
    assert "expense" in before
    rec = await mcp_client.call_mcp_tool("self", "record_transaction", {"text": "午饭 35 元"})
    assert "已记" in rec or "35" in rec
    after = json.loads(await mcp_client.call_mcp_tool("self", "get_ledger_view", {}))
    assert after["expense"] == before["expense"] + 35.0


# ---------------------------------------------------------------------------
# 定时产出与调度状态作为 MCP 资源（Tasks 的可行替代）
# ---------------------------------------------------------------------------


async def test_scheduled_outputs_resource_lists_runs(temp_db) -> None:
    """MCP 客户端应能拉到定时产出（晨报/技能触发），而不是只能等推送。"""
    from app import mcp_server

    await db.save_run("cron", "晨报问题", "晨报回答", "已生成", skip_session=True)
    out = await mcp_server.scheduled_outputs_resource.fn()
    payload = json.loads(out)
    assert payload["count"] >= 1
    assert any(i["thread_id"] == "cron" for i in payload["items"])
    assert payload["items"][0]["answer"]


async def test_scheduler_status_resource_reports_state(temp_db) -> None:
    from app import mcp_server

    out = await mcp_server.scheduler_status_resource.fn()
    payload = json.loads(out)
    assert "report_time" in payload and "enabled" in payload
    assert "skill_jobs" in payload

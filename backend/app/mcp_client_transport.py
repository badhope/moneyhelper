"""MCP 会话与工具发现：StreamableHTTP/stdio 会话、list_tools、调用与归属解析。

配置、缓存与策略一律动态从门面取（`_facade.MCP_CFG` 等）：测试会直接
`monkeypatch.setattr(mcp_client, "MCP_CFG", ...)` 与替换 `_readonly_tools`，
import 时快照绑定会让这些补丁静默失效。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from . import mcp_client as _facade


@asynccontextmanager
async def _open_session(server: dict[str, Any] | str) -> AsyncIterator[ClientSession]:
    """打开一条会话并完成 initialize 握手（SDK 全托管）。

    http：传 URL 字符串（兼容旧调用）；stdio：传含 command/args/env 的配置对象。
    客户端生命周期归本函数管理（SDK 只管 MCP 会话本身）。
    """
    if isinstance(server, str) or not server.get("command"):
        url = server if isinstance(server, str) else str(server.get("url") or "")
        http = httpx.AsyncClient(timeout=_facade.TIMEOUT)
        try:
            async with (
                streamable_http_client(url, http_client=http) as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                yield session
        finally:
            await http.aclose()
        return
    # 执行前再校验一次：配置文件可能被其他途径写入（备份恢复、手改）。
    if not _facade.stdio_config_allowed():
        raise ValueError(
            "stdio 型 MCP 默认禁止执行；请由部署者设置 MONEYHELPER_ALLOW_STDIO_MCP=1"
        )
    _facade._assert_stdio_cwd_safe(server)
    params = StdioServerParameters(
        command=str(server.get("command") or ""),
        args=[str(a) for a in (server.get("args") or [])],
        env={str(k): str(v) for k, v in (server.get("env") or {}).items()} or None,
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


def _make_schema(tool: Any) -> dict[str, Any]:
    """把 mcp.types.Tool 转成 OpenAI function-calling schema。

    外部 MCP 工具统一加 mcp__ 前缀：防止与内置工具命名字典冲突，
    同时让模型一眼区分"本地财务工具"和"外部 MCP 工具"，降低 prompt injection 时误调用概率。"""
    schema = getattr(tool, "inputSchema", None)
    if not isinstance(schema, dict):
        schema = {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": f"mcp__{getattr(tool, 'name', 'tool')}",
            "description": (getattr(tool, "description", "") or "")[:300],
            "parameters": schema,
        },
    }


def _content_text(content: Any) -> str:
    """把 CallToolResult.content 里的文本块拼成一个字符串。"""
    out: list[str] = []
    for c in content or []:
        text = getattr(c, "text", None)
        if isinstance(text, str):
            out.append(text)
    return "".join(out)


async def _discover(server: dict[str, Any]) -> list[Any]:
    """对单个服务器 list_tools，返回工具对象列表并登记注册表。"""
    name = server.get("name") or "mcp"
    async with _open_session(server) as session:
        resp = await session.list_tools()
    tools = list(resp.tools)
    _facade._servers[name] = [f"mcp__{t.name}" for t in tools]
    _facade._readonly_tools.update(
        {f"mcp__{t.name}": _facade._is_readonly_tool(t) for t in tools}
    )
    return tools


async def probe(url: str, command: str = "", args: list[str] | None = None) -> list[str]:
    """测试单台 MCP 服务器：打开会话并 list_tools，返回工具名。

    与 _discover 的区别：不写注册表、不读配置，纯连通性探测，供设置页「测试」按钮使用。
    http 传 url；stdio 传 command + args。
    """
    target: dict[str, Any] | str = url or {"command": command, "args": args or []}
    async with _open_session(target) as session:
        resp = await session.list_tools()
    return [str(getattr(t, "name", "")) for t in (resp.tools or []) if getattr(t, "name", None)]


async def refresh(force: bool = False) -> list[dict[str, Any]]:
    """返回所有 MCP 服务器提供的工具 schema（供 agent 装配）。

    结果带 30s TTL 缓存：发现过程包含逐台服务器的握手与 list_tools 往返，
    每轮问答都重做会显著拉长首 token 时间。force=True 可强制刷新。
    """
    config = _facade._load_config()
    key = f"{_facade.MCP_CFG}|{json.dumps(config, sort_keys=True, ensure_ascii=False)}"
    if not force:
        cached = _facade._discover_cache.get(key)
        if cached is not None:
            return cached
    # 并发发现：串行时一台离线服务器的 15s 超时会叠加成 N×15s，直接拖垮首 token。
    sem = asyncio.Semaphore(_facade._DISCOVER_CONCURRENCY)
    results: list[list[dict[str, Any]]] = []
    expose_all = _facade.external_tools_mode() == "all"

    async def _one(server: dict[str, Any]) -> list[dict[str, Any]]:
        name = str(server.get("name") or "")
        if not force and name in _facade._discovery_failures:
            return []
        async with sem:
            try:
                discovered = await _facade._discover(server)
                if not expose_all:
                    # 未声明只读的外部工具不进入模型工具面：名字无法证明副作用。
                    discovered = [t for t in discovered if _facade._is_readonly_tool(t)]
                schemas = [
                    sc for sc in (_make_schema(t) for t in discovered) if sc
                ]
                _facade._discovery_failures.pop(name, None)
                return schemas
            except Exception as exc:  # noqa: BLE001 — 单台失败不影响其它
                _facade._discovery_failures[name] = f"{type(exc).__name__}: {exc}"
                _facade._log.warning("mcp discover %s failed: %s", name, exc)
                return []

    results = await asyncio.gather(*[_one(s) for s in config]) if config else []
    out: list[dict[str, Any]] = [sc for group in results for sc in group]
    _facade._discover_cache[key] = out
    return out


def failure_status() -> dict[str, str]:
    """最近失败过的服务器（设置页展示「为什么没有工具」）。"""
    return dict(_facade._discovery_failures)


async def call_mcp_tool(server_name: str, tool_name: str, args: dict[str, Any]) -> str:
    """调用某 MCP 服务器的某个工具，返回文本结果。找不到返回错误串。

    tool_name 传入时可能含 mcp__ 前缀——剥掉后再发往 MCP 服务器（服务器端保留原始名称）。"""
    raw_name = tool_name.removeprefix("mcp__")
    for server in _facade._load_config():
        if server.get("name") != server_name:
            continue
        try:
            async with _open_session(server) as session:
                result = await session.call_tool(raw_name, args or {})
            if result.isError:
                return json.dumps(
                    {"error": _content_text(result.content) or "mcp tool error"},
                    ensure_ascii=False,
                )
            text = _content_text(result.content)
            return text or json.dumps(
                result.model_dump(exclude_none=True), ensure_ascii=False, default=str
            )
        except Exception as exc:  # noqa: BLE001
            return f"mcp 工具调用失败：{type(exc).__name__}: {exc}"
    return f"mcp 服务器 {server_name} 未配置"


def resolve_mcp_tool(name: str) -> tuple[str, str] | None:
    """把 `tool` 名解析为 (server_name, tool_name)；非 MCP 工具返回 None。"""
    for sname, tools in _facade._servers.items():
        if name in tools:
            return sname, name
    return None

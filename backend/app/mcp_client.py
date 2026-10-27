"""MCP 客户端：基于官方 `mcp` SDK（StreamableHTTP 传输），不自研协议实现。

历史说明：此前曾为避免依赖冲突手写过 JSON-RPC 客户端；实测官方 mcp SDK 与
本项目 FastAPI/httpx/starlette 版本零冲突（httpx>=0.27 兼容 0.28），按
「能用成熟库不自研」原则整体替换——协议握手、会话 ID、SSE 流解析、
notifications 时序等全部交给 SDK，本模块只剩配置/适配两层薄逻辑。

配置：`backend/data/mcp.json`（不存在则空）：
```json
{
  "servers": [
    {
      "name": "calculator",
      "url": "http://127.0.0.1:9100/mcp"
    }
  ]
}
```

流程：refresh 时对每个 server 打开一条 StreamableHTTP 会话（SDK 自动完成
initialize 握手）→ list_tools 拉取工具清单并转成 function schema 供 LLM 调用；
call_mcp_tool 时新开会话 → call_tool。会话由 SDK 的 async context 管理，
用完即关（外部工具低频调用，无需常驻连接）。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from .logging_utils import get_logger

_log = get_logger("mcp")

# 工具发现结果缓存：refresh 会对每个 server 做一次 initialize + tools/list
# 往返。agent 每次问答都会调 refresh，不缓存就是每轮多一次网络握手。
# 30s 与行情缓存同量级：外部工具清单变动不频繁，用户手动改配置后最多等半分钟。
_DISCOVER_TTL_S = 30.0
# 缓存键包含配置路径 + 服务器列表指纹：换配置/换测试临时文件时自动失效，
# 不能只用 TTL（测试里连续切换 mcp.json 会读到上一个用例的结果）。
_discover_cache: tuple[float, str, list[dict[str, Any]]] | None = None
# 失败退避：某台服务器刚刚失败过，30 分钟内不再重试（否则每轮问答都要等超时）。
# 值形如 {server_name: (monotonic_ts, error)}。启用/停用/保存配置会清空。
_discovery_failures: dict[str, tuple[float, str]] = {}
_FAILURE_TTL_S = 1800.0
_DISCOVER_CONCURRENCY = 4

MCP_CFG = Path(__file__).resolve().parent.parent / "data" / "mcp.json"
TIMEOUT = 15.0

# 进程内工具注册表：server_name -> [tool names]（供 resolve_mcp_tool 解析归属）
_servers: dict[str, list[str]] = {}


def _load_config(include_disabled: bool = False) -> list[dict[str, Any]]:
    try:
        if not MCP_CFG.exists():
            return []
        data = json.loads(MCP_CFG.read_text(encoding="utf-8") or "{}")
        servers = data.get("servers") or []
        out = [
            s
            for s in servers
            if isinstance(s, dict)
            and (str(s.get("url") or "").strip() or str(s.get("command") or "").strip())
        ]
        if not include_disabled:
            out = [s for s in out if s.get("enabled", True)]
        return out
    except Exception:  # noqa: BLE001 — 配置异常按无 MCP 处理
        _log.warning("mcp config parse failed")
        return []


def raw_servers() -> list[dict[str, Any]]:
    """完整服务器列表（含停用项与原始地址），供安装/启停编辑使用。"""
    return _load_config(include_disabled=True)


def list_servers() -> list[dict[str, Any]]:
    """当前配置的 MCP 服务器（给设置页展示，不含任何凭据——URL 里的 token 会被打码）。"""
    out: list[dict[str, Any]] = []
    for s in _load_config(include_disabled=True):
        url = str(s.get("url") or "")
        command = str(s.get("command") or "")
        args = s.get("args") or []
        out.append(
            {
                "name": str(s.get("name") or ""),
                "url": redact_url(url),
                "transport": "http" if url else "stdio",
                "command": command,
                "args": list(args) if isinstance(args, list) else [],
                "enabled": bool(s.get("enabled", True)),
                "tools": list(_servers.get(str(s.get("name") or ""), [])),
            }
        )
    return out


def save_servers(servers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """保存服务器列表（写 mcp.json），返回清洗后的列表。

    校验：name 非空且唯一；http 服务器需 http(s) 地址；stdio 服务器需 command；
    最多 20 台。保存后清空发现缓存，下一次问答会重新拉工具清单。
    """
    global _discover_cache
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for s in servers or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "").strip()[:40]
        if not name:
            continue
        url = str(s.get("url") or "").strip()
        command = str(s.get("command") or "").strip()
        if not url and not command:
            continue
        if url and not url.lower().startswith(("http://", "https://")):
            raise ValueError(f"服务器「{name}」的地址必须以 http:// 或 https:// 开头")
        if name in seen:
            raise ValueError(f"服务器名称重复：{name}")
        seen.add(name)
        entry: dict[str, Any] = {"name": name, "enabled": bool(s.get("enabled", True))}
        if url:
            entry["url"] = url
        else:
            entry["command"] = command
            args = s.get("args") or []
            if not isinstance(args, list):
                raise ValueError(f"服务器「{name}」的 args 必须是数组")
            entry["args"] = [str(a)[:200] for a in args][:20]
            if isinstance(s.get("env"), dict):
                entry["env"] = {str(k)[:60]: str(v)[:500] for k, v in s["env"].items()}
        cleaned.append(entry)
        if len(cleaned) >= 20:
            break
    MCP_CFG.parent.mkdir(parents=True, exist_ok=True)
    MCP_CFG.write_text(
        json.dumps({"servers": cleaned}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _discover_cache = None
    _discovery_failures.clear()
    return cleaned


def set_server_enabled(name: str, enabled: bool) -> list[dict[str, Any]]:
    """启用/停用某台服务器（保留配置，只改 enabled 标记）。"""
    servers = _load_config(include_disabled=True)
    found = False
    for s in servers:
        if str(s.get("name") or "") == name:
            s["enabled"] = bool(enabled)
            found = True
    if not found:
        raise ValueError(f"服务器不存在：{name}")
    return save_servers(servers)



def redact_url(url: str) -> str:
    """把 URL 里的凭据打码：https://user:token@host/path → https://***@host/path。"""
    from urllib.parse import urlsplit, urlunsplit

    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.username and not parts.password:
        return url
    host = parts.hostname or ""
    netloc = f"***@{host}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


@asynccontextmanager
async def _open_session(server: dict[str, Any] | str) -> AsyncIterator[ClientSession]:
    """打开一条会话并完成 initialize 握手（SDK 全托管）。

    http：传 URL 字符串（兼容旧调用）；stdio：传含 command/args/env 的配置对象。
    客户端生命周期归本函数管理（SDK 只管 MCP 会话本身）。
    """
    if isinstance(server, str) or not server.get("command"):
        url = server if isinstance(server, str) else str(server.get("url") or "")
        http = httpx.AsyncClient(timeout=TIMEOUT)
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
    _servers[name] = [f"mcp__{t.name}" for t in tools]
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
    global _discover_cache
    now = time.monotonic()
    config = _load_config()
    key = f"{MCP_CFG}|{json.dumps(config, sort_keys=True, ensure_ascii=False)}"
    if not force and _discover_cache is not None:
        ts, cached_key, cached = _discover_cache
        if cached_key == key and now - ts < _DISCOVER_TTL_S:
            return cached
    # 并发发现：串行时一台离线服务器的 15s 超时会叠加成 N×15s，直接拖垮首 token。
    sem = asyncio.Semaphore(_DISCOVER_CONCURRENCY)
    results: list[list[dict[str, Any]]] = []

    async def _one(server: dict[str, Any]) -> list[dict[str, Any]]:
        name = str(server.get("name") or "")
        failed_at = _discovery_failures.get(name)
        if failed_at and now - failed_at[0] < _FAILURE_TTL_S and not force:
            return []
        async with sem:
            try:
                schemas = [
                    sc
                    for sc in (_make_schema(t) for t in await _discover(server))
                    if sc
                ]
                _discovery_failures.pop(name, None)
                return schemas
            except Exception as exc:  # noqa: BLE001 — 单台失败不影响其它
                _discovery_failures[name] = (time.monotonic(), f"{type(exc).__name__}: {exc}")
                _log.warning("mcp discover %s failed: %s", name, exc)
                return []

    results = await asyncio.gather(*[_one(s) for s in config]) if config else []
    out: list[dict[str, Any]] = [sc for group in results for sc in group]
    _discover_cache = (now, key, out)
    return out


def failure_status() -> dict[str, str]:
    """最近失败过的服务器（设置页展示「为什么没有工具」）。"""
    return {name: err for name, (_ts, err) in _discovery_failures.items()}


async def call_mcp_tool(server_name: str, tool_name: str, args: dict[str, Any]) -> str:
    """调用某 MCP 服务器的某个工具，返回文本结果。找不到返回错误串。

    tool_name 传入时可能含 mcp__ 前缀——剥掉后再发往 MCP 服务器（服务器端保留原始名称）。"""
    raw_name = tool_name.removeprefix("mcp__")
    for server in _load_config():
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
    for sname, tools in _servers.items():
        if name in tools:
            return sname, name
    return None

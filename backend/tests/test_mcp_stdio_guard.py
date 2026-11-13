"""MCP stdio 配置接口的安全边界：默认拒绝，显式开关才允许。

stdio 服务器会在服务端拉起任意本地进程；这个测试锁住「远程 API 不能凭一个
JSON 就必须执行 command」的约束，避免后续重构把 PUT /api/mcp/servers 的
校验删掉。
"""

from __future__ import annotations

import httpx
import pytest
from app import main, mcp_client


@pytest.fixture
async def client(temp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_client, "MCP_CFG", tmp_path / "mcp.json")
    mcp_client._discover_cache.clear()
    mcp_client._discovery_failures.clear()
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1:8787"
    ) as ac:
        yield ac


async def test_put_stdio_rejected_by_default(client, monkeypatch) -> None:
    monkeypatch.delenv("MONEYHELPER_ALLOW_STDIO_MCP", raising=False)
    r = await client.put(
        "/api/mcp/servers",
        json={
            "servers": [
                {"name": "evil", "command": "cmd.exe", "args": ["/c", "calc"]}
            ]
        },
    )
    assert r.status_code == 400
    assert "stdio" in r.text


async def test_put_stdio_allowed_only_with_explicit_flag(client, monkeypatch) -> None:
    monkeypatch.setenv("MONEYHELPER_ALLOW_STDIO_MCP", "1")

    async def _no_refresh(force: bool = False):
        return []

    monkeypatch.setattr(mcp_client, "refresh", _no_refresh)
    r = await client.put(
        "/api/mcp/servers",
        json={"servers": [{"name": "local", "command": "python", "args": ["-m", "x"]}]},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

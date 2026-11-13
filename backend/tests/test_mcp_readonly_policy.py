"""外部 MCP 工具只读边界：只信服务器显式声明的 readOnlyHint。

背景：按工具名判断只读不可靠（`transfer` / `export_all` 都可以叫成
`get_*`）。MCP 的 ToolAnnotations.readOnlyHint 是唯一的机器可读承诺；
没有声明就按不可信处理，避免 prompt injection/模型误判触发外部写操作。
"""

from __future__ import annotations

from app import mcp_client
from mcp.types import Tool, ToolAnnotations


def _tool(name: str, readonly: bool | None) -> Tool:
    annotations = (
        None if readonly is None else ToolAnnotations(readOnlyHint=readonly)
    )
    return Tool(name=name, inputSchema={"type": "object"}, annotations=annotations)


def test_unannotated_and_write_tools_not_exposed(monkeypatch) -> None:
    monkeypatch.delenv("MONEYHELPER_MCP_EXTERNAL_TOOLS", raising=False)
    monkeypatch.setattr(
        mcp_client,
        "_readonly_tools",
        {"mcp__read": True, "mcp__write": False},
    )
    assert mcp_client.is_tool_exposed("mcp__read") is True
    assert mcp_client.is_tool_exposed("mcp__write") is False
    # 没发现过/没声明的工具默认拒绝
    assert mcp_client.is_tool_exposed("mcp__unknown") is False


def test_all_mode_is_explicit_escape_hatch(monkeypatch) -> None:
    monkeypatch.setenv("MONEYHELPER_MCP_EXTERNAL_TOOLS", "all")
    assert mcp_client.is_tool_exposed("mcp__anything") is True


async def test_refresh_filters_unannotated_tools(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mcp_client, "MCP_CFG", tmp_path / "mcp.json")
    mcp_client.MCP_CFG.write_text(
        '{"servers":[{"name":"s","url":"https://s.example/mcp"}]}', encoding="utf-8"
    )
    monkeypatch.delenv("MONEYHELPER_MCP_EXTERNAL_TOOLS", raising=False)

    async def _fake_discover(_server):
        return [
            _tool("quote", True),
            _tool("transfer", None),
            _tool("delete_all", False),
        ]

    monkeypatch.setattr(mcp_client, "_discover", _fake_discover)
    mcp_client._discover_cache.clear()
    schemas = await mcp_client.refresh(force=True)
    assert [s["function"]["name"] for s in schemas] == ["mcp__quote"]


async def test_refresh_all_mode_keeps_every_tool(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mcp_client, "MCP_CFG", tmp_path / "mcp.json")
    mcp_client.MCP_CFG.write_text(
        '{"servers":[{"name":"s","url":"https://s.example/mcp"}]}', encoding="utf-8"
    )
    monkeypatch.setenv("MONEYHELPER_MCP_EXTERNAL_TOOLS", "all")

    async def _fake_discover(_server):
        return [_tool("quote", True), _tool("transfer", None)]

    monkeypatch.setattr(mcp_client, "_discover", _fake_discover)
    mcp_client._discover_cache.clear()
    schemas = await mcp_client.refresh(force=True)
    assert {s["function"]["name"] for s in schemas} == {"mcp__quote", "mcp__transfer"}

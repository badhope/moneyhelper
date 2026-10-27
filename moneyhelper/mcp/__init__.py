"""MCP Server 门面。

模块名用 `moneyhelper.mcp` 而非顶层 `mcp`：后者是官方 MCP SDK 的包名，
同名会在 site-packages 里互相遮蔽（本项目已实测 `import mcp` 指向 SDK）。

当前实现：app.mcp_server（FastMCP 挂载，暴露记账/查询/风险等工具）。
M2.2 会把工具面扩到全量并把传输层升级为 Streamable HTTP，届时实现下沉到本层。
"""

from __future__ import annotations

from app import mcp_server  # noqa: F401

__all__ = ["mcp_server"]

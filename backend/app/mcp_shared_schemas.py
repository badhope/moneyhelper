"""把已注册 MCP 工具的参数 schema 覆盖为共享真源（tool_schemas.py）。

从 mcp_server.py 拆出。`mcp` 实例在函数内惰性导入，避免与门面循环；
返回缺失清单供调用方观测（新增工具忘登记会被点名）。
"""

from __future__ import annotations

from typing import Any

from .logging_utils import get_logger

log = get_logger(__name__)


def _apply_shared_schemas() -> list[str]:
    """把已注册 MCP 工具的参数 schema 覆盖为共享真源；返回未能对齐的工具名。

    只覆盖"共享真源里有定义"的工具；返回缺失清单让调用方可观测——
    新增 MCP 工具时若忘记在 tool_schemas.py 里登记，这里会明确报出来。
    """
    from . import tool_schemas as ts
    from .mcp_server import mcp

    manager = getattr(mcp, "_tool_manager", None)
    if manager is None:  # pragma: no cover — 假 MCP（fastmcp 不可用）
        return []
    registered: dict[str, Any] = getattr(manager, "_tools", {}) or {}
    missing: list[str] = []
    for name, tool in registered.items():
        try:
            tool.parameters = ts.input_schema(name)
        except KeyError:
            missing.append(name)
    if missing:
        log.warning(
            "mcp.schema_missing: 以下工具未在 tool_schemas.py 登记入参模型: %s",
            ", ".join(sorted(missing)),
        )
    return missing

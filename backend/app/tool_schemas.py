"""工具入参的 pydantic 模型 —— schema 的单一真源（M2.1）。

两侧都从 `model_json_schema()` 派生：
    OpenAI function calling:  {"type":"function","function":{"parameters": <schema>}}
    MCP inputSchema:          <schema>

模型定义按域拆在 `schemas_*.py`，基类与清洗在 `schemas_base.py`；
本文件只做合并与对外接口。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from .schemas_base import _strip_noise


def input_schema(name: str) -> dict[str, Any]:
    """取某工具入参的 JSON Schema（已去除展示性字段）。"""
    model = TOOL_INPUT_MODELS.get(name) or MCP_ONLY_INPUT_MODELS.get(name)
    if model is None:
        raise KeyError(f"未定义入参模型：{name}")
    schema = _strip_noise(model.model_json_schema())
    schema.pop("description", None)
    schema.setdefault("type", "object")
    # 空 required 无信息量（手写版本对无参数工具有的带有的不带，本身就不一致），
    # 统一不产出：OpenAI 与 MCP 都按"无必填项"处理。
    if schema.get("required") == []:
        schema.pop("required")
    return schema


def validate_tool_args(name: str, args: Any) -> tuple[dict[str, Any] | None, str | None]:
    """执行前校验工具入参 —— 让 extra="forbid" 真正落地，而不是只写在 schema 里。

    返回 (清洗后的参数, None) 或 (None, 错误文案)。三个执行边界
    （agent 工具循环 / agent_graph action 节点 / confirm 直接执行）都必须
    先过这一关再进 impl：模型多传字段、类型不符会被拦下，
    错误文案可直接回填给模型 self-correct。未登记模型的工具放行原参数
    （与 schema 派生口径一致：没模型 = 没约束）。
    """
    model = TOOL_INPUT_MODELS.get(name) or MCP_ONLY_INPUT_MODELS.get(name)
    if model is None:
        return (args if isinstance(args, dict) else {}), None
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return None, f"参数必须是 JSON 对象，收到 {type(args).__name__}"
    try:
        cleaned = model.model_validate(args)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", ())) or "(root)"
        msg = first.get("msg", "invalid")
        return None, f"参数校验失败：{loc}: {msg}"
    return dict(cleaned), None


def function_schema(name: str, description: str) -> dict[str, Any]:
    """产出 OpenAI function calling 形态的工具定义。"""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": input_schema(name),
        },
    }

# ---------------------------------------------------------------------------
# 入参模型按域拆分（schemas_*.py）；这里只做合并，保证 TOOL_INPUT_MODELS /
# MCP_ONLY_INPUT_MODELS 仍是「工具名 → 入参模型」的单一入口。
# ---------------------------------------------------------------------------
from .schemas_connect import MODELS as _CONNECT_MODELS  # noqa: E402 — 子模块依赖本文件的 _In
from .schemas_enterprise import MODELS as _ENTERPRISE_MODELS  # noqa: E402 — 子模块依赖本文件的 _In
from .schemas_market import MODELS as _MARKET_MODELS  # noqa: E402 — 子模块依赖本文件的 _In
from .schemas_research import MODELS as _RESEARCH_MODELS  # noqa: E402 — 子模块依赖本文件的 _In
from .schemas_views import MODELS as _VIEW_MODELS  # noqa: E402 — 子模块依赖本文件的 _In
from .schemas_write import MODELS as _WRITE_MODELS  # noqa: E402 — 子模块依赖本文件的 _In

# 全部入参模型（按域合并，键是工具名）
_ALL_MODELS: dict[str, type[BaseModel]] = {
    **_VIEW_MODELS,
    **_MARKET_MODELS,
    **_RESEARCH_MODELS,
    **_CONNECT_MODELS,
    **_WRITE_MODELS,
    **_ENTERPRISE_MODELS,
}

# 只在 MCP 表面额外暴露的工具：企业域 CRUD + 净值/健康/收益/目标/导入/家庭/审计
_MCP_ONLY_NAMES = frozenset({
    "get_net_worth", "get_financial_health", "get_returns", "get_goal_progress",
    "import_transactions", "get_family_summary", "get_provenance",
    "gl_accounts", "gl_periods", "gl_entries", "gl_trial_balance", "gl_create_entry",
    "vendors", "purchase_orders", "payables", "expense_claims",
    "create_purchase_order", "create_payable", "longtask_templates", "longtasks",
    "run_longtask",
})

MCP_ONLY_INPUT_MODELS: dict[str, type[BaseModel]] = {
    name: _ALL_MODELS[name] for name in _MCP_ONLY_NAMES
}

# 应用内 agent 可见的工具面（MCP 专属的不在其中）
TOOL_INPUT_MODELS: dict[str, type[BaseModel]] = {
    name: model for name, model in _ALL_MODELS.items() if name not in _MCP_ONLY_NAMES
}

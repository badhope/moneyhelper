"""工具 schema 单一真源测试（M2.1）。

改造前 schema 存在两份：tools.py 的 JSON Schema 字面量、mcp_server.py 的函数签名。
两份已经漂移（MCP 侧 record_position 多 industry、trigger_morning_report/backup_now
多 lang、get_lessons/set_setting 缺失）。这些测试锁死"只有一个真源"。

测试目标不是描述 schema 长什么样，而是保证两侧永远取自同一处：
- 同一工具在 function calling 与 MCP 暴露的 parameter schema 逐字相等
- 所有登记的模型都必须有对应的实现（防止登记了却没有工具）
- 新增 MCP 工具若忘记登记入参模型，必须显式报错而不是静默用裸签名
"""

from __future__ import annotations

import json

from app import tool_schemas as ts
from app import tools


def test_every_function_tool_has_input_model() -> None:
    """function calling 暴露的每个工具都必须有入参模型。"""
    exposed = {t["function"]["name"] for t in tools.FINANCE_TOOLS + tools.GENERAL_TOOLS}
    assert exposed == set(ts.TOOL_INPUT_MODELS), (
        f"多出: {exposed - set(ts.TOOL_INPUT_MODELS)}；"
        f"缺失实现: {set(ts.TOOL_INPUT_MODELS) - exposed}"
    )


def test_schema_disallows_extra_params() -> None:
    """所有入参模型都必须禁止多余字段（additionalProperties: false）。

    宽松 schema 会让模型多传的参数被静默丢弃，排查时极难定位。
    """
    for name in list(ts.TOOL_INPUT_MODELS) + list(ts.MCP_ONLY_INPUT_MODELS):
        schema = ts.input_schema(name)
        assert schema.get("additionalProperties") is False, name


def test_schema_has_no_pydantic_noise() -> None:
    """schema 里不应带 pydantic 的展示性字段（title / default）。

    - title 由字段名生成，对模型无信息量
    - default 会与实现里的 `args.get(...) or 默认值` 形成第二处真源
    """
    dumped = json.dumps(
        [ts.input_schema(n) for n in ts.TOOL_INPUT_MODELS], ensure_ascii=False
    )
    assert '"title"' not in dumped
    assert '"default"' not in dumped


def test_function_schema_shape_matches_openai() -> None:
    """function calling 形态必须是 {"type":"function","function":{...}}。"""
    fs = ts.function_schema("get_quote", "查行情")
    assert fs["type"] == "function"
    fn = fs["function"]
    assert fn["name"] == "get_quote"
    assert fn["description"] == "查行情"
    assert fn["parameters"]["required"] == ["symbol"]


def test_mcp_schemas_match_function_schemas() -> None:
    """MCP 暴露的参数 schema 必须与 function calling 侧逐字相同（同一真源）。

    这是本次改造的核心断言：两侧参数漂移会直接导致"LLM 能传的参数"
    与"外部 MCP 客户端能传的参数"不一致。
    """
    pytest = __import__("pytest")
    pytest.importorskip("fastmcp")

    from app import mcp_server

    missing = mcp_server._apply_shared_schemas()
    assert missing == [], f"以下 MCP 工具未在 tool_schemas.py 登记：{missing}"

    manager = mcp_server.mcp._tool_manager
    mcp_tools = dict(getattr(manager, "_tools", {}) or {})
    assert mcp_tools, "MCP 工具未注册"

    fc_by_name = {
        t["function"]["name"]: t["function"]["parameters"]
        for t in tools.FINANCE_TOOLS + tools.GENERAL_TOOLS
    }

    for name, tool in mcp_tools.items():
        if name not in fc_by_name:
            continue  # MCP 专属工具（净值/家庭/审计等），只在 MCP 侧暴露
        assert tool.parameters == fc_by_name[name], f"{name} 两侧 schema 不一致"


def test_mcp_only_tools_are_registered() -> None:
    """MCP 专属工具也要有入参模型（否则新增时忘记登记会静默用裸签名）。"""
    assert set(ts.MCP_ONLY_INPUT_MODELS) == {
        "get_net_worth",
        "get_financial_health",
        "get_returns",
        "get_goal_progress",
        "import_transactions",
        "get_family_summary",
        "get_provenance",
    }


def test_record_position_industry_exposed_both_sides() -> None:
    """回归：industry 参数早就在实现与 MCP 侧存在，但 function calling 侧漏了。

    漏参数的实际后果：模型无法指定行业，只能落到"其他"，行业集中度分析失真。
    """
    assert "industry" in ts.input_schema("record_position")["properties"]
    mcp_schema = ts.input_schema("record_position")
    assert mcp_schema["required"] == ["symbol", "shares", "cost"]


def test_morning_report_and_backup_expose_lang() -> None:
    """回归：MCP 侧有 lang 参数而 function calling 侧没有，现统一暴露。"""
    for name in ("trigger_morning_report", "backup_now"):
        assert "lang" in ts.input_schema(name)["properties"], name


# ---------------------------------------------------------------------------
# validate_tool_args：extra="forbid" 的执行期落地点（2.9.3）
# ---------------------------------------------------------------------------


def test_validate_rejects_extra_fields() -> None:
    """多传字段必须被拦下，而不是被静默忽略后照常执行。"""
    clean, err = ts.validate_tool_args(
        "record_position", {"symbol": "600519", "shares": 100, "cost": 1700, "hack": 1}
    )
    assert clean is None
    assert err is not None and "hack" in err


def test_validate_rejects_wrong_type_and_non_dict() -> None:
    """类型不符与非对象入参都要报可读错误。"""
    clean, err = ts.validate_tool_args("record_position", {"shares": "很多"})
    assert clean is None and err
    clean, err = ts.validate_tool_args("get_market_view", ["not", "a", "dict"])
    assert clean is None and err


def test_validate_cleans_and_passes_valid_args() -> None:
    """合法参数原样放行（返回普通 dict，供三个执行边界统一使用）。"""
    clean, err = ts.validate_tool_args(
        "record_position", {"symbol": "600519", "shares": 100, "cost": 1700}
    )
    assert err is None and clean is not None
    # 模型默认值字段会被补全（下游 args.get(...) or 默认 的口径不变），关键校验：
    # 传入的字段保真，且绝无模型之外的字段混入
    assert {k: clean[k] for k in ("symbol", "shares", "cost")} == {
        "symbol": "600519", "shares": 100, "cost": 1700,
    }
    model_fields = set(ts.TOOL_INPUT_MODELS["record_position"].model_fields)
    assert set(clean) <= model_fields


def test_validate_none_args_equivalent_to_empty() -> None:
    """无参数工具传 None 等价于空对象（模型常把无参工具传成 null）。"""
    clean, err = ts.validate_tool_args("get_market_view", None)
    assert err is None and clean == {}


def test_validate_unknown_tool_passes_through() -> None:
    """未登记模型的工具（如 MCP 动态工具）放行原参数，与 schema 派生口径一致。"""
    clean, err = ts.validate_tool_args("mcp__some_server__echo", {"x": 1})
    assert err is None and clean == {"x": 1}

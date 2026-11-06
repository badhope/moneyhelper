"""MCP/工具注册表契约：** advertised 的每个工具都必须可调用、有说明、不炸**。

为什么需要这组测试：MCP 暴露 63 个手写包装器（@mcp.tool()），agent 注册表 55 个工具，
两条表面各自维护。此前的风险模式：
  - 包装器委托的 impl 不存在（NameError 只在真实调用时炸）
  - agent 注册了工具但 MCP 没暴露（能力漂移）
  - 工具在缺参时抛 KeyError/TypeError——agent 层能兜住（转成错误文案），
    但 MCP 层模型拿到的是垃圾错误，且违背项目自身约定「失败返回明确提示，绝不抛错」

三层契约：
  A. 真源对齐：TOOL_IMPL ↔ FINANCE_TOOL_NAMES ↔ TOOLS 双向一致，无孤立 impl
  B. MCP 表面：每个包装器有 docstring、入参 schema 已登记（_align_schemas 返回空）、
     包装器委托的 impl 真实存在
  C. 行为探测：全量 55 个工具在离线环境下以空参数调用——缺参工具允许抛 ValueError
     （可读文案），不允许 KeyError/TypeError 等实现泄漏
"""

import ast
from pathlib import Path

import pytest
from app import quotes as quotes_mod
from app import tools

# ---------------------------------------------------------------------------
# 离线环境：行情相关入口全部换成快速失败 mock（复用 test_tools 的思路，
# 但覆盖面更广——契约探测要打到 fetch_kline / index_kline / live_quotes 全部入口）
# ---------------------------------------------------------------------------


@pytest.fixture
def offline_quotes(monkeypatch):
    """所有行情入口快速失败：kline 返回空、quote 返回 None 系。

    tools.py 在模块顶部绑定了 quote_now / fetch_kline（from .quotes import x as y），
    lazy import（函数内 from .quotes import live_quotes）则从 quotes 模块解析——
    两处都要替换，否则探测会真的走网络（上一轮空参数探测卡 120s 的根因）。
    """

    async def _empty_kline(symbol, period="daily", limit=180):
        return None

    async def _empty_index_kline(code, period="daily", limit=180):
        return None

    async def _snap(positions):
        return {p["symbol"]: float(p["last"]) for p in positions}

    async def _quote(sym):
        return {"symbol": sym, "price": 1250.0, "name": "演示", "last": 1250.0}

    monkeypatch.setattr(quotes_mod, "kline", _empty_kline)
    monkeypatch.setattr(quotes_mod, "index_kline", _empty_index_kline)
    monkeypatch.setattr(quotes_mod, "live_quotes", _snap)
    monkeypatch.setattr(quotes_mod, "quote_now", _quote)
    monkeypatch.setattr(quotes_mod, "indices_quotes", lambda: [])
    # tools 模块的提前绑定
    monkeypatch.setattr(tools, "quote_now", _quote)
    monkeypatch.setattr(tools, "fetch_kline", _empty_kline)

    async def _no_search(q, limit=5):
        return []

    if hasattr(quotes_mod, "search"):
        monkeypatch.setattr(quotes_mod, "search", _no_search)
    if hasattr(quotes_mod, "fund_nav"):
        async def _no_nav(codes):
            return []
        monkeypatch.setattr(quotes_mod, "fund_nav", _no_nav)
    return True


# ---------------------------------------------------------------------------
# A. 真源对齐
# ---------------------------------------------------------------------------


def test_registry_names_and_impls_align():
    """agent 注册表双向对齐： advertised 的每个名字都有 impl，反之亦然。"""
    names = [n for n, _ in tools.FINANCE_TOOL_NAMES]
    missing = [n for n in names if n not in tools.TOOL_IMPL]
    orphan = [n for n in tools.TOOL_IMPL if n not in names]
    assert not missing, f"advertised 但无实现（模型调用必崩）: {missing}"
    assert not orphan, f"实现了但没登记（用户永远用不到）: {orphan}"


def test_tools_schemas_match_impls():
    """TOOLS schema 表与 TOOL_IMPL 一致，且每条 schema 结构合法。"""
    schema_names = [t["function"]["name"] for t in tools.TOOLS]
    assert sorted(schema_names) == sorted(tools.TOOL_IMPL.keys())

    for t in tools.TOOLS:
        fn = t["function"]
        assert t["type"] == "function"
        assert fn["name"], "工具名缺失"
        # 描述是模型选工具的唯一依据，空/过短说明没写
        assert fn.get("description") and len(fn["description"]) >= 15, (
            f"{fn['name']} 描述过短（模型无法判断何时该用它）"
        )
        params = fn.get("parameters") or {}
        assert params.get("type") == "object", f"{fn['name']} parameters 非 object"


def test_general_tools_align():
    """通用工具（get_now / web_search）同样登记完整。"""
    gnames = [n for n, _ in tools.GENERAL_TOOL_NAMES]
    for n in gnames:
        assert n in tools.TOOL_REGISTRY, f"通用工具 {n} 未进统一注册表"
        r = tools.TOOL_REGISTRY[n]
        assert r["mode"] == "general"
        assert r["schema"]["function"]["description"]


# ---------------------------------------------------------------------------
# B. MCP 表面
# ---------------------------------------------------------------------------


def _mcp_registered() -> dict[str, dict]:
    """从 mcp_server 实例直接读取已注册工具（name → {description, parameters}）。

    用运行时自省而非 AST：_align_schemas 会把共享真源的入参 schema 覆盖到
    tool.parameters，自省拿到的是「模型最终看到的」形态。
    """
    from app import mcp_server

    manager = getattr(mcp_server.mcp, "_tool_manager", None)
    if manager is None:  # pragma: no cover — fastmcp 不可用的假 MCP
        pytest.skip("fastmcp 不可用")
    return dict(getattr(manager, "_tools", {}) or {})


def _wrapper_impl_map() -> dict[str, str]:
    """AST 解析 mcp_server.py：包装器名 → 它委托的 xtools.tool_* 属性名。"""
    src = Path(mcp_server_source()).read_text(encoding="utf-8")
    tree = ast.parse(src)
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and isinstance(sub.func.value, ast.Name)
                and sub.func.value.id == "xtools"
            ):
                out[node.name] = sub.func.attr
                break
    return out


def mcp_server_source() -> str:
    import app.mcp_server as m

    return m.__file__


def test_mcp_tools_all_have_impls(offline_quotes, temp_db):
    """63 个 MCP 包装器委托的 impl 必须真实存在——NameError 只在真实调用时炸。"""
    wmap = _wrapper_impl_map()
    assert len(wmap) >= 55, f"MCP 包装器数量异常: {len(wmap)}"

    import app.tools as xtools

    broken = []
    for wrapper, attr in wmap.items():
        if not hasattr(xtools, attr):
            broken.append(f"{wrapper} -> xtools.{attr} 不存在")
    assert not broken, "MCP 包装器委托缺失：\n" + "\n".join(broken)


def test_mcp_tools_have_description_and_schema():
    """每个 MCP 工具必须有描述；入参 schema 必须已在 tool_schemas 登记。"""
    reg = _mcp_registered()
    assert len(reg) >= 55, f"MCP 注册工具数量异常: {len(reg)}"

    no_doc = [n for n, t in reg.items() if not (t.description or "").strip()]
    assert not no_doc, f"无描述的工具（模型无法判断何时用）: {no_doc}"

    from app import mcp_server

    missing = mcp_server._apply_shared_schemas()
    assert missing == [], f"入参 schema 未登记: {missing}"


def test_mcp_covers_finance_registry(offline_quotes):
    """agent 注册表里的财务工具，MCP 表面不能缺——能力漂移在这里报出来。

    注：MCP 可能多暴露 agent 未装配的工具（如审批/沙箱管理），那是允许的超集；
    这里只拦「agent 有、MCP 没有」的缺口。
    """
    reg = _mcp_registered()
    names = [n for n, _ in tools.FINANCE_TOOL_NAMES]
    absent = [n for n in names if n not in reg]
    # 允许的例外：明确标注理由的工具（当前无；有新例外时在此登记并写明原因）
    allowed_absent: set[str] = set()
    unexpected = [n for n in absent if n not in allowed_absent]
    assert not unexpected, (
        f"agent 注册但 MCP 未暴露（{len(unexpected)} 个）: {unexpected[:10]}"
    )


# ---------------------------------------------------------------------------
# C. 行为探测：全量工具空参数调用
# ---------------------------------------------------------------------------


def _required_args(name: str) -> list[str]:
    for t in tools.TOOLS:
        if t["function"]["name"] == name:
            return list((t["function"].get("parameters") or {}).get("required") or [])
    return []


# 真实外呼/有副作用的工具不进空参探测（离线探测无意义或污染环境）。
# 每个例外都要写明理由——这是「允许的例外清单」，不是随手跳过。
PROBE_EXCLUDED = {
    "web_search": "真实外呼 DuckDuckGo；离线行为已有专测覆盖",
    "backup_now": "写备份包到数据目录；副作用属于备份功能自己的测试",
    "trigger_morning_report": "会触发晨报生成链路（含后台任务），有专项测试",
}


@pytest.mark.parametrize(
    "name",
    [n for n in tools.TOOL_REGISTRY if n not in PROBE_EXCLUDED],
)
@pytest.mark.asyncio
async def test_tool_with_empty_args_never_leaks_impl_error(
    name, offline_quotes, temp_db
):
    """空参数调用每个工具：缺参允许 ValueError（可读文案），不允许实现细节泄漏。

    契约依据：agent 层把一切异常转成「工具执行失败：XxxError: ...」回给模型——
    KeyError('symbol') 这类泄漏对模型是噪声、对用户是「内部错误」。
    项目自身约定（tool_web_search docstring）：失败返回明确提示，绝不抛错。
    """
    impl = tools.TOOL_REGISTRY[name]["impl"]
    required = _required_args(name)
    try:
        result = await impl({})
        assert isinstance(result, str), f"{name} 返回 {type(result).__name__}，契约是 str"
        return
    except ValueError as e:
        # 仅当缺必填参数时允许 ValueError，且必须是可读文案
        msg = str(e)
        assert msg.strip(), f"{name} 抛了空 ValueError"
        assert required, f"{name} 无必填参数却抛 ValueError: {msg}"
        return
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"{name} 空参数抛出非契约异常 {type(exc).__name__}: {str(exc)[:200]}"
        )

"""MCP Server：把 Moneyhelper 所有工具暴露为标准 MCP 协议。

通过 fastmcp 把 tools.py 里的工具包装成 MCP 工具，让任何支持 MCP Client 的 AI IDE
（Claude Code / Cursor / Windsurf / Cline 等）都能直接调用 Moneyhelper 的工具集：
- 持仓分析、账本查询、风控、预算、目标、K线 等财务工具
- search_symbol / get_quote / add_to_watchlist 等行情工具
- get_now / web_search 等通用工具

启动方式：
1. 嵌入 FastAPI（默认）：mount 到 /mcp 路径，与主应用同进程
2. 独立进程：python -m app.mcp_server（stdio transport，供 Claude Desktop 接入）

MCP 协议接入后，Claude Code / Cursor 等 IDE 可以直接对 Moneyhelper 数据库执行财务分析。
"""

from __future__ import annotations

import asyncio
from typing import Any

from starlette.routing import BaseRoute

from . import db
from . import tool_policy as _policy
from . import tools as xtools
from .logging_utils import get_logger

log = get_logger(__name__)

# MCP Server：fastmcp 版本与 FastAPI 版本可能冲突，import 失败就降级 no-op
try:
    from fastmcp import FastMCP

    # instructions：MCP 客户端（Claude Desktop / Cline / Continue 等）会把它
    # 作为系统提示注入给模型，告诉模型「这个服务器是干什么的、什么时候该用」。
    # 不设的话模型只能从 63 个工具名里猜，容易该调不调或乱调。
    # instructions：MCP 客户端（Claude Desktop / Cline / Continue 等）会把它
    # 作为系统提示注入给模型，告诉模型「这个服务器是干什么的、什么时候该用」。
    # 不设的话模型只能从 63 个工具名里猜，容易该调不调或乱调。
    mcp = FastMCP(
        "moneyhelper-finance",
        instructions=(
            "Moneyhelper 个人财务服务器。提供本地账本、持仓、行情、风险、税负、"
            "回测与报表工具。所有数字由本地确定性引擎计算，不联网也能用（行情除外）。\n\n"
            "使用建议：\n"
            "- 查现状优先用 get_* 工具（只读、无需确认）；\n"
            "- 写操作（record_*/sell_position/backup_now 等）需要人工确认后才执行；\n"
            "- 需要精确金额时一律以工具返回值为准，不要根据历史对话推算；\n"
            "- 数据缺失时工具会明确说明，不要用假设值填补。"
        ),
    )
    MCP_AVAILABLE = True
except Exception as e:  # pragma: no cover
    log.warning("mcp.fastmcp_unavailable: %s — MCP server disabled", e)
    # 假装饰器：让 @_tool() / @mcp.resource() 等不炸，函数原样返回
    class _FakeMCP:
        def tool(self, *a, **kw):
            def deco(fn): return fn
            return deco
        def resource(self, *a, **kw):
            def deco(fn): return fn
            return deco
        def prompt(self, *a, **kw):
            def deco(fn): return fn
            return deco
        def sse_app(self):
            raise RuntimeError("MCP unavailable")
    mcp = _FakeMCP()
    MCP_AVAILABLE = False


def _tool():
    """注册 MCP 工具，并按本地工具策略声明 readOnlyHint。

    外部客户端/agent 不能靠名字猜副作用；只读工具显式声明 readOnlyHint，
    写工具保持未声明（默认不可信）。这样 Moneyhelper 自己的 MCP Server
    接入后也只暴露只读工具，除非部署者显式设置 MCP_EXTERNAL_TOOLS=all。
    """
    from mcp.types import ToolAnnotations

    def decorator(fn):
        readonly = _policy.resolve(fn.__name__) == _policy.READ
        return mcp.tool(annotations=ToolAnnotations(readOnlyHint=readonly))(fn)

    return decorator


# ---------------------------------------------------------------------------
# 持仓 / 组合分析工具
# ---------------------------------------------------------------------------


# 该域包装器已拆到 mcp_views.py，见文件末尾导入。



# ---------------------------------------------------------------------------
# 行情 / 自选工具
# ---------------------------------------------------------------------------


# 该域包装器已拆到 mcp_market.py，见文件末尾导入。




# ---------------------------------------------------------------------------
# 写操作审批（M2.3）：MCP 侧的 elicitation 门禁
# ---------------------------------------------------------------------------
#
# 改造前 MCP 的写工具完全没有审批：任何接入的 MCP 客户端都能直接改账本，
# 与大额阈值（Web 对话里 >5000 元要确认）完全脱节。MCP 规范提供
# elicitation（服务端向客户端请求用户输入），正好承载这个语义：
#
#   Web 对话：超阈值 → route=nl_pending，问「确认/取消」
#   MCP     ：超阈值 → ctx.elicit(...)，客户端弹表单，用户点接受/拒绝
#
# 两条路径共用 approval.threshold 与 approval.format_approval_prompt，
# 保证"什么算大额"和"怎么问"一致。
#
# 客户端不支持 elicitation 时（老客户端 / 无 UI 的自动化场景）必须 **拒绝执行**，
# 而不是静默放行——审批是安全网，宁可失败也不能悄悄写入。


# 记账 / 记忆 / 设置等写操作工具已拆到 mcp_writes.py，
# 在本文件末尾导入以触发注册并保留同名属性。


# ---------------------------------------------------------------------------
@_tool()
async def get_now() -> str:
    """返回当前日期与时间（服务器本地时区）。"""
    return await xtools.tool_get_now({})


# 该域包装器已拆到 mcp_research.py，见文件末尾导入。



# ---------------------------------------------------------------------------
# 连接中心（v4.4）：外部数据源与资金账户接入
# ---------------------------------------------------------------------------


# 该域包装器已拆到 mcp_connect.py，见文件末尾导入。




# ---------------------------------------------------------------------------
# 写操作（需谨慎）：晨报 / 备份
# ---------------------------------------------------------------------------


@_tool()
async def trigger_morning_report(lang: str = "zh") -> str:
    """立即生成今日晨报（组合+账本+财务目标体检）。lang=zh/en。"""
    return await xtools.tool_trigger_morning_report({}, lang=lang)


@_tool()
async def backup_now(lang: str = "zh") -> str:
    """生成本地加密备份包（口令只显示一次，不落盘）。"""
    return await xtools.tool_backup_now({}, lang=lang)


# ---------------------------------------------------------------------------
# 资源暴露（MCP resource）：系统说明
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# 财务数据查询工具（增强）
# ---------------------------------------------------------------------------


# 该域包装器已拆到 mcp_analytics.py，见文件末尾导入。





# ---------------------------------------------------------------------------
# 参数 schema 对齐（M2.1）：MCP 工具的实际入参定义来自 tool_schemas.py
# ---------------------------------------------------------------------------
#
# 改造前每个 MCP 工具用手写函数签名声明参数，与 tools.py 的 JSON Schema 各自
# 维护同一份额外真相，已经漂移（MCP 的 record_position 多 industry、
# trigger_morning_report/backup_now 多 lang、get_lessons 与 set_setting 缺失）。
# 现在统一在注册后把参数 schema 覆盖为共享真源的产物：
# - 两侧参数名/类型/必填/说明完全一致，改一处即两侧同步
# - 函数签名保持原样（fastmcp 需要它做参数绑定），仅对外暴露的 schema 换源


def _apply_shared_schemas() -> list[str]:
    """把已注册 MCP 工具的参数 schema 覆盖为共享真源；返回未能对齐的工具名。

    只覆盖"共享真源里有定义"的工具；返回缺失清单让调用方可观测——
    新增 MCP 工具时若忘记在 tool_schemas.py 里登记，这里会明确报出来。
    """
    from . import tool_schemas as ts

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


# ---------------------------------------------------------------------------
# 集成入口：挂载到 FastAPI 应用
# ---------------------------------------------------------------------------


def build_asgi() -> tuple[Any, Any] | None:
    """构建 MCP 的 ASGI 子应用，返回 (streamable_app, sse_app)。

    必须由调用方在创建父 app **之前**调用，并把 streamable_app.lifespan
    接进父 app —— Streamable HTTP 的 session manager 在 lifespan 里启动
    task group，不接会报 "Task group is not initialized"（实测）。
    sse_app 可能为 None（旧版 fastmcp 无 create_sse_app）。
    """
    if not MCP_AVAILABLE:
        return None

    _apply_shared_schemas()

    # 传输层：**Streamable HTTP 为默认**，SSE 保留一个版本期（M2.2）。
    #
    # 为什么换默认：MCP 规范 2025-03 起用 Streamable HTTP 取代 HTTP+SSE。
    # SSE 需要两条长连接（/sse 收 + /messages/ 发），在反向代理与移动网络下
    # 容易断流；Streamable HTTP 单端点、按需升流，是当前官方推荐形态。
    #
    # 兼容策略：已接入的客户端仍指向 /mcp/sse + /mcp/messages/，因此两条路径
    # 并存挂载。SSE 的移除安排在下一个大版本，届时在 CHANGELOG 明示。
    from fastmcp.server.http import create_streamable_http_app

    # 内部路由保留 /mcp：下面用「精确路径挂载」把 /mcp 与 /mcp/ 都直接交给它，
    # 不经过 Starlette 的斜杠重定向（307 会让不跟随重定向的 MCP 客户端失败）。
    streamable = create_streamable_http_app(server=mcp, streamable_http_path="/mcp")
    sse = None
    try:
        from fastmcp.server.http import create_sse_app

        sse = create_sse_app(server=mcp, message_path="/messages/", sse_path="/sse")
    except ImportError:  # pragma: no cover — 仅旧版 fastmcp 走到
        log.warning("mcp.sse_unavailable: 当前 fastmcp 版本不提供 create_sse_app")
    return streamable, sse


class _DynamicMcp:
    """动态转发到"当前" MCP 子应用。

    为什么需要它：session manager 每个实例只能 run 一次（run() 不可重入），
    而父 app 的 lifespan 可能被多次进入（测试用 TestClient、热重载、嵌入式
    多实例）。若挂载时把子应用写死，lifespan 里就得复用同一实例 → 第二次
    启动直接抛 "can only be called once per instance"；若 lifespan 里重建，
    挂载的路由又指向旧实例 → session manager 从未启动，端点 500。

    解法：挂一个转发器，请求到达时读取 holder 里的当前实例。lifespan 负责
    写入新实例，两者永远指同一个对象。
    """

    def __init__(self, holder: dict[str, Any]) -> None:
        self._holder = holder

    async def __call__(self, scope, receive, send) -> None:
        built = self._holder.get("built")
        target = built[0] if built else None
        if target is None:  # pragma: no cover — lifespan 未跑或构建失败
            from starlette.responses import JSONResponse

            await JSONResponse({"error": "MCP 未就绪"}, status_code=503)(scope, receive, send)
            return
        await target(scope, receive, send)


class _DynamicSse(_DynamicMcp):
    """同上，转发到 SSE 子应用（holder 里的第 2 项）。"""

    async def __call__(self, scope, receive, send) -> None:
        built = self._holder.get("built")
        target = built[1] if built else None
        if target is None:  # pragma: no cover — 旧版 fastmcp 无 SSE
            from starlette.responses import JSONResponse

            await JSONResponse({"error": "MCP SSE 不可用"}, status_code=503)(scope, receive, send)
            return
        await target(scope, receive, send)


class _ExactPathRoute(BaseRoute):
    """只匹配精确路径（含可选尾斜杠）并把原始 scope 交给子应用。

    为什么不用 Mount：Starlette 对 `Mount("/mcp")` 的精确路径 `/mcp` 会先做
    307 重定向到 `/mcp/`，而 MCP 客户端（含官方 SDK）默认不跟随重定向，
    表现为"连不上"。这里直接匹配、不改写路径，`/mcp` 与 `/mcp/` 都直达子应用。
    不匹配的路径返回 Match.NONE，后续静态托管等路由照常生效。
    """

    def __init__(self, path: str, app: Any) -> None:
        self.path = path
        self.app = app

    def matches(self, scope) -> tuple[Any, dict[str, Any]]:
        from starlette.routing import Match

        if scope["type"] != "http":
            return Match.NONE, {}
        raw = scope.get("path", "")
        if raw in (self.path, self.path + "/"):
            return Match.FULL, scope
        return Match.NONE, {}

    async def handle(self, scope, receive, send) -> None:
        await self.app(scope, receive, send)

    async def __call__(self, scope, receive, send) -> None:
        await self.handle(scope, receive, send)


def mount_to_app(app: Any, holder: dict[str, Any] | None = None) -> None:
    """把 MCP 子应用挂到 FastAPI app（/mcp 为 Streamable HTTP，/mcp-sse 为 SSE）。

    holder 是可变容器 {"built": (streamable, sse) | None}，由父 app 的 lifespan
    负责写入。不传则内部构建一次并写死（无 lifespan 接入，Streamable HTTP
    不可用，仅测试/特殊场景使用）。
    """
    if not MCP_AVAILABLE:
        log.info("mcp.skipped: fastmcp unavailable, not mounting")
        return

    if holder is None:
        built = build_asgi()
        if built is None:
            return
        holder = {"built": built}
    streamable = _DynamicMcp(holder)

    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    # /mcp 走 app.mount 会绕过主 app 的 @app.middleware("http") 中间件链，
    # 所以这里复用主 app 的同一套闸（口令 + 多用户 JWT fail-closed + Host/Origin
    # 白名单），否则就会出现"主站有防护、MCP 侧裸奔"的第二条信任边界。
    from .middleware import auth_gate, host_guard_check

    class _McpAuthGuard(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            gate = await auth_gate(request)
            if isinstance(gate, JSONResponse):
                return gate
            denied = host_guard_check(request)
            if denied is not None:
                return JSONResponse({"error": denied}, status_code=403)
            # 租户接线：auth_gate 返回的 tenant_id 必须写进 ContextVar，
            # 否则 MCP 工具里的 db.* 全部落到默认租户 0——多用户实例里
            # 用户 B 拿自己的 JWT 调 MCP，读写的是用户 A 的账本（跨租户读写）。
            from .db.tenant import reset_current_user_id, set_current_user_id

            token = set_current_user_id(gate)
            try:
                return await call_next(request)
            finally:
                reset_current_user_id(token)

    # 路径布局：
    #   /mcp                 Streamable HTTP（默认，MCP 规范推荐；无斜杠即用）
    #   /mcp-sse/sse         SSE 端点（旧客户端兼容，保留一个版本期）
    #   /mcp-sse/messages/   SSE 上行端点（仅 POST）
    #
    # 绝不挂 Mount("/")：根挂载会拦截所有未匹配请求（含前端静态资源），
    # 导致单端口部署时首页 404。streamable 子应用的内部路由就是 "/mcp"，
    # 因此用精确路径路由直接转发原始 scope（/mcp 与 /mcp/ 都命中，无 307）。
    sse_dynamic = _DynamicSse(holder)
    app.mount("/mcp-sse", _McpAuthGuard(sse_dynamic))
    app.router.routes.append(_ExactPathRoute("/mcp", _McpAuthGuard(streamable)))
    log.info("mcp.transport: streamable-http at /mcp, sse at /mcp-sse/sse")


async def startup() -> None:
    """MCP Server 启动时检查 DB 可用性。"""
    try:
        await db.fetch_all("SELECT 1")
    except Exception:
        pass  # DB 未就绪时 MCP 工具会在调用时返回错误


if __name__ == "__main__":
    """独立运行 MCP Server（stdio transport，供 Claude Desktop 等接入）。

    非 stdio 模式默认只绑 127.0.0.1：独立进程没有 FastAPI 的鉴权中间件，
    绑 0.0.0.0 等于把记账/备份等写工具暴露给整个局域网（历史漏洞 H-3）。
    确需对外提供服务时，必须自行加反向代理鉴权并显式设置
    MONEYHELPER_MCP_BIND_HOST。
    """
    import os
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "stdio":
        asyncio.run(mcp.run_async(transport="stdio"))
    else:
        host = os.getenv("MONEYHELPER_MCP_BIND_HOST", "127.0.0.1").strip() or "127.0.0.1"
        asyncio.run(
            mcp.run_async(transport="streamable-http", host=host, port=8765)
        )

# ---------------------------------------------------------------------------
# v4.6：账单规则归类 / 券商执行层 / 发票视觉能力
# ---------------------------------------------------------------------------


# 该域包装器已拆到 mcp_broker.py，见文件末尾导入。




# ---------------------------------------------------------------------------
# MCP Prompts：可复用的分析模板（第三大原语）
#
# 为什么需要：tools 让客户端"能算"，prompts 让它"知道该怎么问"。
# 没有 prompts 时，每个客户端都要自己拼提示词，结果差异极大——
# 有人问"我财务怎么样"得到三段流水，有人得到完整体检。
# 这里给出官方口径的模板，保证不同客户端拿到一致的输出结构。
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# 企业域工具（切片 11）：总账 / 采购应付 / 报销 / 长任务
#
# 为什么补这一组：此前 63 个 MCP 工具全部是个人财务域（账本/持仓/行情/税负），
# 「企业级 AI 办公 + 财务会计」这一定位在 AI 可操作层面是空的——企业域只能点 UI。
#
# 权限分层沿用现有机制：
# - 读工具加进 tool_policy.READONLY_TOOLS，外部 MCP 客户端可直接调用；
# - 写工具保持未声明 readOnlyHint（= ASK），模型必须经人工确认。
# - 租户由 current_tenant_id() 决定（嵌在 FastAPI 里时来自鉴权中间件；
#   独立 stdio 模式即本机租户 0），与本进程内其他企业域代码同一口径。
# ---------------------------------------------------------------------------










































# ---------------------------------------------------------------------------
# 包装器分域模块：import 即注册（@_tool 装饰器副作用），同时保留同名属性
# ---------------------------------------------------------------------------
from .mcp_analytics import (  # noqa: F401,E402 — 注册副作用 + 同名属性
    get_family_summary,
    get_financial_health,
    get_goal_progress,
    get_net_worth,
    get_provenance,
    get_returns,
    import_transactions,
)
from .mcp_broker import (  # noqa: F401,E402 — 注册副作用 + 同名属性
    broker_preview_order,
    broker_status,
    broker_submit_order,
    categorize_bills,
    invoice_vision_status,
)
from .mcp_connect import (  # noqa: F401,E402 — 注册副作用 + 同名属性
    cashflow_forecast,
    conditional_order,
    connect_catalog,
    connect_fund_nav,
    connect_order,
    connect_sync,
    debt_payoff_plan,
    import_brokerage_holdings,
    market_breadth,
    parse_invoice,
    pretrade_check,
    scan_anomalies,
    scan_subscriptions,
    stock_profile,
    tax_calc,
)
from .mcp_enterprise import (  # noqa: F401,E402 — 注册副作用 + 同名属性
    create_payable,
    create_purchase_order,
    expense_claims,
    get_expense_queue,
    get_gl_summary,
    get_org_overview,
    get_payables_summary,
    gl_accounts,
    gl_create_entry,
    gl_entries,
    gl_periods,
    gl_trial_balance,
    list_longtasks,
    longtask_templates,
    longtasks,
    payables,
    purchase_orders,
    run_longtask,
    vendors,
)
from .mcp_market import (  # noqa: F401,E402 — 注册副作用 + 同名属性
    add_to_watchlist,
    get_kline,
    get_quote,
    get_watchlist,
    remove_from_watchlist,
    search_symbol,
)
from .mcp_prompts import (  # noqa: F401,E402 — prompt 注册副作用
    goal_planning,
    monthly_review,
    portfolio_checkup,
)
from .mcp_research import (  # noqa: F401,E402 — 注册副作用 + 同名属性
    paper_open,
    paper_overview,
    paper_trade,
    research_analyze,
    research_backtest,
    research_forecast,
    statements_analyze,
    web_search,
)
from .mcp_resources import (  # noqa: F401,E402 — resource 注册副作用
    scheduled_outputs_resource,
    scheduler_status_resource,
    system_prompt_resource,
)
from .mcp_views import (  # noqa: F401,E402 — 注册副作用 + 同名属性
    get_budget,
    get_dca_plans,
    get_fire_plan,
    get_goals,
    get_health_check,
    get_ledger_view,
    get_market_view,
    get_portfolio_risk,
    get_rebalance_plan,
    get_risk_flags,
    get_trend,
    get_valuation,
)
from .mcp_writes import (  # noqa: F401,E402 — 注册副作用 + 测试访问 _confirm_write
    _confirm_write,
    get_lessons,
    get_user_memory,
    record_position,
    record_transaction,
    save_user_memory,
    sell_position,
    set_setting,
)

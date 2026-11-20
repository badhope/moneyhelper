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
import json
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


@mcp.resource("moneyhelper://scheduled-outputs")
async def scheduled_outputs_resource() -> str:
    """最近的定时产出（晨报 + 技能触发），供 MCP 客户端主动拉取。

    为什么用 resource 而不是 Tasks：MCP 的 Tasks（长任务推送）在 mcp 1.30 仍属
    experimental，fastmcp 2.x 未透传，落地要绕开框架直接用 lowlevel server。
    而"客户端能拿到定时产出"这个真实需求，用 resource 拉取即可满足——
    客户端按自己的节奏刷新，服务端由既有 APScheduler 负责生成。
    """
    rows = await db.list_scheduled_runs(10)

    items = [
        {
            "thread_id": r.get("thread_id"),
            "question": r.get("question"),
            "answer": r.get("answer"),
            "level": r.get("level"),
            "created_at": r.get("created_at"),
        }
        for r in rows
    ]
    return json.dumps(
        {"count": len(items), "items": items},
        ensure_ascii=False,
        indent=1,
    )


@mcp.resource("moneyhelper://scheduler-status")
async def scheduler_status_resource() -> str:
    """定时任务状态（晨报开关、下次运行时间、上次错误）。"""
    from . import scheduler

    return json.dumps(scheduler.status(), ensure_ascii=False, indent=1)


@mcp.resource("moneyhelper://system-prompt")
def system_prompt_resource() -> str:
    """Moneyhelper 系统提示词：描述工具集和 Agent 行为规则。"""
    return (
        "你是 Moneyhelper(moneyhelper)财务 Agent，通过 MCP 工具访问用户的本地财务数据。\n"
        "规则：\n"
        "1. 需要数字时必须调用工具获取，绝不编造\n"
        "2. 先给一句话结论，再列关键数字，最后风险项\n"
        "3. 不给具体买卖指令\n"
        "4. 工具失败时如实说明\n"
        "5. 涉及用户背景先查 get_user_memory"
    )


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


@mcp.prompt()
def monthly_review(month: str = "") -> str:
    """月度财务复盘：收支结构 + 异常项 + 下月建议。

    参数 month 形如 2026-11；留空表示当月。
    """
    target = month or "本月"
    return (
        f"请为我做 {target} 的财务复盘，按以下结构输出：\n"
        "1. 收支概览：总收入、总支出、结余、储蓄率（用 get_trend / get_budget 的数据）；\n"
        "2. 支出结构：占比最高的三类及金额，指出是否存在异常增长（用 get_ledger_view）；\n"
        "3. 风险提示：调用 get_risk_flags，逐条说明影响与可执行动作；\n"
        "4. 下月建议：给出 1-3 条具体、可量化的调整建议。\n\n"
        "要求：所有金额必须来自工具返回，不要估算；数据缺失时明确说明缺什么。"
    )


@mcp.prompt()
def portfolio_checkup() -> str:
    """持仓体检：集中度、盈亏归因、再平衡建议。"""
    return (
        "请对我的投资组合做一次体检，按以下结构输出：\n"
        "1. 整体表现：总市值、累计盈亏、今日盈亏（get_market_view）；\n"
        "2. 风险集中度：单一标的与行业占比，标出越过 40% 阈值的项（get_portfolio_risk）；\n"
        "3. 盈亏贡献：哪几只贡献了主要盈利/亏损（get_market_view 的 pnl 字段）；\n"
        "4. 再平衡建议：调用 get_rebalance_plan，说明每笔调整的金额与理由。\n\n"
        "要求：不要给买卖建议式的肯定判断，只陈述数据与规则触发情况；"
        "所有百分比保留两位小数。"
    )


@mcp.prompt()
def goal_planning() -> str:
    """目标规划：进度诊断 + 每月需存 + 可行性判断。"""
    return (
        "请评估我的财务目标进度，按以下结构输出：\n"
        "1. 逐个目标的完成度、剩余缺口、距截止月还有几个月（get_goals）；\n"
        "2. 按当前储蓄能力，判断每个目标是否可行；不可行的给出两个替代方案"
        "（延长期限 / 降低目标额）；\n"
        "3. 如果需要调整月度投入，给出具体数字。\n\n"
        "要求：可行性判断必须基于 get_trend 的真实结余数据，不要用收入代替储蓄能力。"
    )


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


def _tenant() -> int:
    from .db.tenant import current_tenant_id

    return current_tenant_id()


@_tool()
async def get_gl_summary() -> str:
    """查企业总账概览：科目、会计期间、最近凭证、试算平衡。"""
    return await xtools.tool_get_gl_summary({})


@_tool()
async def get_payables_summary() -> str:
    """查采购应付：供应商数、采购单状态分布、未付款应付金额、逾期应付。"""
    return await xtools.tool_get_payables_summary({})


@_tool()
async def get_expense_queue() -> str:
    """查报销队列：待审核报销单数量与金额。"""
    return await xtools.tool_get_expense_queue({})


@_tool()
async def get_org_overview() -> str:
    """查组织架构：部门、岗位、成员数量。"""
    return await xtools.tool_get_org_overview({})


@_tool()
async def list_longtasks() -> str:
    """查长任务列表：标题、类型、已完成阶段、状态。"""
    return await xtools.tool_list_longtasks({})


@_tool()
async def gl_accounts() -> str:
    """查总账科目表：科目编码、名称、类型（asset/liability/equity/income/expense）、是否启用。"""
    rows = await db.gl_list_accounts(_tenant())
    return json.dumps({"accounts": rows}, ensure_ascii=False, default=str)


@_tool()
async def gl_periods() -> str:
    """查会计期间列表：年、月、起止日期、状态（open/closed）。"""
    rows = await db.gl_list_periods(_tenant())
    return json.dumps({"periods": rows}, ensure_ascii=False, default=str)


@_tool()
async def gl_entries(period_id: int = 0, limit: int = 50) -> str:
    """查凭证列表（新→旧）。period_id 省略=全部期间；limit 1-200，默认 50。

    返回每张凭证的编号、日期、摘要、借贷合计、状态（draft/posted）、来源。
    """
    rows = await db.gl_list_entries(_tenant(), period_id or None, limit)
    return json.dumps({"entries": rows}, ensure_ascii=False, default=str)


@_tool()
async def gl_trial_balance(period_id: int) -> str:
    """查某会计期间的试算平衡表：各科目期初/借方/贷方/期末，以及全局是否借贷平衡。"""
    data = await db.gl_trial_balance(_tenant(), int(period_id))
    return json.dumps(data, ensure_ascii=False, default=str)


@_tool()
async def gl_create_entry(
    entry_date: str,
    description: str,
    lines: list[dict[str, Any]],
    post_now: bool = False,
) -> str:
    """新建总账凭证（默认只建草稿，post_now=true 时立即过账）。

    lines 是分录数组，每项形如 {"account_id": 1, "debit": 100, "credit": 0, "memo": "..."}；
    借贷必须平衡，金额单位为元（内部转整数分）。account_id 先用 gl_accounts 查。
    """
    entry = await db.gl_create_entry(_tenant(), entry_date, description, lines, 0)
    if post_now:
        entry = await db.gl_post_entry(_tenant(), int(entry["id"]))
    return json.dumps(entry, ensure_ascii=False, default=str)


@_tool()
async def vendors() -> str:
    """查供应商档案：编码、名称、税号、联系人、状态。"""
    rows = await db.vendor_list(_tenant())
    return json.dumps({"vendors": rows}, ensure_ascii=False, default=str)


@_tool()
async def purchase_orders() -> str:
    """查采购单：单号、供应商、金额、状态（draft/submitted/approved）、关联审批人。"""
    rows = await db.po_list(_tenant())
    return json.dumps({"orders": rows}, ensure_ascii=False, default=str)


@_tool()
async def payables() -> str:
    """查应付单：单号、供应商、发票号、金额、税额、到期日、状态、关联凭证与付款。"""
    rows = await db.payable_list(_tenant())
    return json.dumps({"payables": rows}, ensure_ascii=False, default=str)


@_tool()
async def expense_claims(status: str = "") -> str:
    """查报销单。status 可传 draft/submitted/approved/rejected，省略=全部。"""
    rows = await db.expense_list_claims(_tenant(), status or None)
    return json.dumps({"claims": rows}, ensure_ascii=False, default=str)


@_tool()
async def create_purchase_order(
    vendor_id: int,
    order_date: str,
    amount: float,
    expected_date: str = "",
    description: str = "",
) -> str:
    """新建采购单（草稿）。amount 单位为元；提交与审核需在采购页或调用对应工具人工确认。"""
    po = await db.po_create(
        _tenant(), int(vendor_id), order_date, expected_date, amount, description
    )
    return json.dumps(po, ensure_ascii=False, default=str)


@_tool()
async def create_payable(
    vendor_id: int,
    invoice_date: str,
    amount: float,
    expense_account_id: int,
    payable_account_id: int,
    po_id: int = 0,
    invoice_no: str = "",
    due_date: str = "",
    tax: float = 0,
) -> str:
    """新建应付单（草稿）。需先用 gl_accounts 查借方费用科目与贷方应付科目 id。"""
    ap = await db.payable_create(
        _tenant(),
        int(vendor_id),
        int(po_id) if po_id else None,
        invoice_no,
        invoice_date,
        due_date,
        amount,
        tax,
        int(expense_account_id),
        int(payable_account_id),
    )
    return json.dumps(ap, ensure_ascii=False, default=str)


@_tool()
async def longtask_templates() -> str:
    """查长任务模板：每种任务类型（小说/网页/Word/论文/程序）的阶段划分。"""
    from . import longtask

    return json.dumps({"templates": longtask.list_templates()}, ensure_ascii=False)


@_tool()
async def longtasks() -> str:
    """查长任务列表：标题、类型、状态、已完成阶段数。"""
    from . import longtask

    return json.dumps({"tasks": longtask.list_tasks()}, ensure_ascii=False)


@_tool()
async def run_longtask(task_id: str, max_stages: int = 0) -> str:
    """执行长任务（未完成阶段）。max_stages 限制本次跑几个阶段，0=全部。

    长任务会真实调用模型、逐阶段落盘产物，耗时可能数分钟到数十分钟。
    """
    from . import longtask

    task = await longtask.run_task(task_id, max_stages=max_stages or None)
    return json.dumps(task, ensure_ascii=False, default=str)


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
from .mcp_market import (  # noqa: F401,E402 — 注册副作用 + 同名属性
    add_to_watchlist,
    get_kline,
    get_quote,
    get_watchlist,
    remove_from_watchlist,
    search_symbol,
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


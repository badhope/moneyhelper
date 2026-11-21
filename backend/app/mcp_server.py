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
async def backup_now(lang: str = "zh") -> dict[str, str]:
    """生成本地加密备份包（口令只显示一次，不落盘）。

    返回 {"answer", "passphrase"}：口令必须单独交给调用方，不能拼进 answer
    （Web 侧从 final 事件单独取，避免口令进问答历史）。这里注解成 dict 而不是
    str——FastMCP 会按注解校验返回值，写 str 会直接报
    "Output validation error"，工具在 MCP 侧等于不可用（实测）。
    """
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




from .mcp_shared_schemas import _apply_shared_schemas  # noqa: F401,E402 — 对外同名导出

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










































# 传输层挂载已拆到 mcp_mount.py；这里 re-export，保持 mcp_server.* 可用
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
from .mcp_mount import (  # noqa: F401,E402
    build_asgi,
    mount_to_app,
    startup,
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

"""Agent 工具层：把确定性分析内核暴露成 LLM 可调用的工具（function calling）。

设计原则：
- 所有工具都是确定性计算（数字来自本地数据），模型只决定"调哪个工具、以什么参数调"，
  不负责产出数字 —— 延续「确定性内核优先」。
- 工具结果返回时截断为摘要级（关键数字 + 前几条明细），控制 token 与外发体量。
- 工具失败返回明确错误串，由 agent 循环决定是否重试/降级。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .logging_utils import get_logger
from .tool_catalog import (  # noqa: F401 — 对外同名导出
    ENTERPRISE_TOOL_NAMES,
    FINANCE_TOOL_NAMES,
    GENERAL_TOOL_NAMES,
)
from .tool_impl_deep import DEEP_TOOL_IMPL, DEEP_TOOL_NAMES  # noqa: F401
from .tool_registry import (  # noqa: F401,E402 — 注册表与技能包的真源
    ENTERPRISE_IMPL,
    ENTERPRISE_TOOLS,
    FINANCE_IMPL,
    FINANCE_TOOLS,
    GENERAL_IMPL,
    GENERAL_TOOLS,
    TOOL_IMPL,
    TOOL_REGISTRY,
    TOOLS,
)

# 模拟盘 / 连接中心 / 记忆三块已拆到独立模块；re-export 保持命名空间与 TOOL_IMPL 不变。
from .tools_connect import (  # noqa: F401
    tool_connect_catalog,
    tool_connect_fund_nav,
    tool_connect_order,
    tool_connect_sync,
)

# 企业域只读工具已拆到独立模块，这里只做 re-export：
# dept_agent 用 getattr(tools, name) 取实现，TOOL_IMPL 也用裸函数名，命名空间必须保留。
from .tools_enterprise import (  # noqa: F401
    _ent_tenant,
    tool_get_expense_queue,
    tool_get_gl_summary,
    tool_get_org_overview,
    tool_get_payables_summary,
    tool_list_longtasks,
)

# 行情/自选/持仓已拆到 tools_market；re-export 含进程内写锁（routes/ledger 直接引用）。
from .tools_market import (  # noqa: F401
    _SEARCH_HEADERS,
    _SEARCH_URL,
    _position_write_lock,
    tool_add_watchlist,
    tool_get_quote,
    tool_get_watchlist,
    tool_record_position,
    tool_remove_watchlist,
    tool_search_symbol,
    tool_sell_position,
)
from .tools_memory import (  # noqa: F401
    tool_get_lessons,
    tool_get_user_memory,
    tool_save_user_memory,
)
from .tools_paper import (  # noqa: F401
    tool_paper_open,
    tool_paper_overview,
    tool_paper_trade,
)

# 组合/计划类工具已拆到 tools_portfolio；re-export 保持命名空间与 TOOL_IMPL 不变。
from .tools_portfolio import (  # noqa: F401
    tool_get_dca_plans,
    tool_get_fire_plan,
    tool_get_portfolio_risk,
    tool_get_rebalance_plan,
    tool_get_valuation,
)
from .tools_report import tool_trigger_morning_report  # noqa: F401

# 研究类工具已拆到 tools_research；re-export 保持命名空间与 TOOL_IMPL 不变。
from .tools_research import (  # noqa: F401
    tool_research_analyze,
    tool_research_backtest,
    tool_research_forecast,
    tool_statements_analyze,
)

# 系统域工具已拆到 tools_system；这里 re-export 保持 tools.xxx 与 TOOL_IMPL 不变。
from .tools_system import (  # noqa: F401
    _load_ddgs,
    tool_backup_now,
    tool_get_health_check,
    tool_get_now,
    tool_set_setting,
    tool_web_search,
)

# 只读视图类工具已拆到 tools_views；re-export 保持命名空间与 TOOL_IMPL 不变。
from .tools_views import (  # noqa: F401
    _compact_ledger,
    _compact_market,
    tool_get_budget,
    tool_get_goals,
    tool_get_kline,
    tool_get_ledger_view,
    tool_get_market_view,
    tool_get_risk_flags,
    tool_get_trend,
    tool_record_transaction,
)

# deep impl 的函数本体必须 re-export 进本模块命名空间：MCP 包装器以
# xtools.tool_xxx 属性访问委托（见 mcp_server.py 的 @mcp.tool 包装器）。
# 历史缺陷：只把 dict 并进 TOOL_IMPL 而不 re-export 函数——属性访问时
# AttributeError，14 个 MCP 工具（券商执行/发票识别/市场宽度/条件单等）
# 在真实调用时全部报废，而 agent 侧走 dict 查找所以测试全绿。
# 用循环而非手写 import 清单：新增 deep 工具只改 tool_impl_deep 一处，
# 本文件零改动，从根上消掉「注册表加了、包装器炸了」的漂移类。
globals().update({_fn.__name__: _fn for _fn in DEEP_TOOL_IMPL.values() if callable(_fn)})

_action_log = get_logger("tools.action")

Emit = Callable[[dict[str, Any]], Awaitable[None]]

# 备份包与数据库同目录（默认 backend/data，Docker 卷 moneyhelper-data），
# 容器重建不丢；路径本身不落库。

# tool_set_setting 可写的键白名单：防止模型/动作带任意 key 往 settings 表写脏键。
# 值与枚举校验仍在各分支内完成；列表以外的 key 一律拒绝。

# ---------------------------------------------------------------------------
# 工具执行体（纯函数，可单测）
# ---------------------------------------------------------------------------




































# ---------------------------------------------------------------------------
# 连接中心工具（v4.4）：让模型能查「数据从哪来」、建连接、拉基金净值、生成交易指令。
# 边界：实盘永远只生成交接单；模拟盘才直接成交。
# ---------------------------------------------------------------------------


















# ---------------------------------------------------------------------------
# 投资策略工具：把确定性引擎的结果交给模型叙述。
# 模型永远不自己算风险指标——它只解读这里返回的数字。
# ---------------------------------------------------------------------------













# ---------------------------------------------------------------------------
# 行情 / 自选 / 持仓工具：让「一句话工作流」成立——
# 搜标的 → 看行情 → 加入自选 → 看 K 线/风险 → 记录买入，全程由模型编排。
# ---------------------------------------------------------------------------











# 进程内持仓写锁：防止 tool_sell_position / tool_append_position 的 read-then-write 竞态














# ---------------------------------------------------------------------------
# 工具注册表：OpenAI function calling 的 JSON Schema + 执行体
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 工具注册表：入参 schema 来自 tool_schemas.py（单一真源，M2.1）
# ---------------------------------------------------------------------------
#
# 改造前这里是 270 行手写的 JSON Schema 字面量，与 mcp_server.py 的函数签名
# 各自维护同一份额外真相，两份已经漂移。现在 schema 只在 tool_schemas.py
# 定义一次，此处仅声明「哪些工具属于财务技能包」以及它们的描述文案。
# 描述文案保留在这里而非模型里：它是给模型的调用指引，与参数定义是两件事。





# 工具返回体量上限：超过即截断（防止把整库明细喂给模型）
TOOL_RESULT_MAX_CHARS = 2500


def _fn(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    """统一生成 OpenAI function schema（新增工具的统一注册入口）。"""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }














def truncate_tool_result(text: str) -> str:
    if len(text) <= TOOL_RESULT_MAX_CHARS:
        return text
    return text[:TOOL_RESULT_MAX_CHARS] + "…（已截断，只保留关键数字）"


# 确定性动作执行已拆到 tools_action.py；这里 re-export，保持 tools.run_action 可用
from .tools_action import (  # noqa: F401,E402
    _ACTION_STOP,
    _create_pending,
    _match_position_by_name,
    run_action,
)

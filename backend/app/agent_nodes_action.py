"""写入/动作节点：记账、取消、待确认动作、长期记忆、工作台管理。

从 agent_graph.py 拆出；待确认动作的持久化 helper 仍在 agent_graph，
本模块通过导入使用，图谱与状态定义不变。
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from . import db, service, tool_schemas, tools
from .agent_graph import AgentState, _emit
from .logging_utils import get_logger

log = get_logger(__name__)

async def record(state: AgentState) -> dict[str, Any]:
    """记账 agent：把一句话记账指令确定性入账并回执（复用 service._try_nl_add 唯一实现）。

    大额审批：**任一分段**金额 > 5000 元时先不入账，返回 pending 状态让用户确认
    （分段口径与 _try_nl_add 入账口径共用 service._nl_segments，防止整句解析只取
    第一段金额绕过审批，如「奶茶 20，房租 6000」）。
    用户回复「确认」后由 supervisor 带 confirm=true + 原问题回到本节点，整句一起入账。
    """
    parsed = state["parsed"]
    assert parsed is not None
    confirm = state.get("confirm", False)
    src_q = state.get("pending_question") or state["question"]

    # 门槛判定按全部分段（与入账同口径）；任一段超阈值即触发审批
    segments = service._nl_segments(src_q)
    breach = (
        max(segments, key=lambda p: abs(float(p.get("amount", 0))))
        if segments
        else parsed
    )
    amount = abs(float(breach.get("amount", 0)))

    # 大额审批：任一段超阈值先确认（阈值与 MCP 侧共用 approval.threshold）
    from . import approval

    if amount > await approval.threshold() and not confirm:
        direction = "收入" if float(breach.get("amount", 0)) > 0 else "支出"
        extra = (
            f"，本句共 {len(segments)} 笔，确认后一起入账" if len(segments) > 1 else ""
        )
        lang = state.get("lang", "zh")
        # 摘要描述与 MCP 侧共用 approval.describe_transaction，保证两条路径
        # 对"这笔是什么"的说法一致；交互指引（回复确认/取消）属于 Web 形态，
        # 留在本层而不是塞进共享模块。
        summary = approval.describe_transaction(breach, lang)
        if lang == "en":
            answer = (
                f"{approval.format_approval_prompt(summary, amount, lang='en')}\n\n"
                f"Record: {summary}{extra}\n"
                f'Reply "confirm" to record, "cancel" to skip.'
            )
        else:
            answer = (
                f"{approval.format_approval_prompt(summary, amount, extra=extra.lstrip('，'), lang='zh')}\n\n"
                f"记的是：{summary}\n"
                f"回复「确认」就入账，回复「取消」就不记。"
            )
        result = {
            "answer": answer,
            "level": "待确认",
            "route": "nl_pending",
            "route_reason": f"大额{direction}审批：{amount:,.0f} 元",
            "metrics": {},
            "flags": [],
            "llm": "template",
            "tools": [],
            "actions": [],
            "pending_token": "",
            "pending_summary": f"{direction} {amount:,.0f} 元",
        }
        return {"result": result}

    result = await service._try_nl_add(
        state.get("pending_question") or state["question"],
        state["reason"],
        _emit,
        state.get("lang", "zh"),
    )
    assert result is not None
    result.setdefault("actions", [{"tab": "ledger"}])
    return {"result": result}


async def nl_cancel(state: AgentState) -> dict[str, Any]:
    """大额审批取消：不入账，仅回执说明未记账。"""
    en = state.get("lang") == "en"
    return {
        "result": {
            "answer": "OK — not recorded." if en else "好，这笔不记了。",
            "level": "已取消",
            "route": "nl_cancel",
            "route_reason": "Large-amount approval: user cancelled"
            if en
            else "大额审批：用户取消",
            "metrics": {},
            "flags": [],
            "llm": "template",
            "tools": [],
            "actions": [],
            "pending_token": "",
            "pending_summary": "",
        }
    }


async def action(state: AgentState) -> dict[str, Any]:
    """动作 agent：不配模型也能在对话里直接执行的动作指令（卖出/清仓、晨报、备份）。

    写类动作（卖出/买入）先登记待确认（pending_actions），随后用 LangGraph 原生
    interrupt() 挂起图 —— 这是 HITL 的真正暂停点。前端确认后经 resume_action()
    用 Command(resume) 恢复图：节点从 interrupt 返回，按用户决定执行/取消并落库，
    最终结果（answer）由图续跑产出。整个 HITL 生命周期都在 LangGraph 内。
    """
    result = await tools.run_action(
        state["question"], state.get("lang", "zh"), emit=_emit
    )
    en = state.get("lang") == "en"
    if result.get("pending_token"):
        token = result["pending_token"]
        # 挂起图，等待用户确认；resume 后这里返回 Command(resume) 传入的决策。
        decision = interrupt(
            {
                "token": token,
                "summary": result["pending_summary"],
                "answer": result["answer"],
            }
        )
        if isinstance(decision, dict) and decision.get("decision") == "confirm":
            # 原子抢占：抢占失败说明这条 token 已被别的请求消费（并发/重放），
            # 直接返回"已失效"，绝不重复执行写操作。
            pending = await db.claim_pending_action(token)
            if pending is None:
                result = {
                    "answer": (
                        "This action was already executed or has expired — nothing was run again."
                        if en
                        else "该操作已执行或已失效，未重复执行。"
                    ),
                    "level": "已失效",
                    "route": "action",
                    "route_reason": "Pending action already consumed" if en else "待确认动作已被消费",
                    "metrics": {},
                    "flags": [],
                    "llm": "tool",
                    "tools": [],
                }
                return {"result": result}
            impl = tools.TOOL_IMPL.get(pending["tool_name"])
            clean_args, verr = tool_schemas.validate_tool_args(pending["tool_name"], pending["args"])
            if impl is not None and clean_args is None:
                result = {
                    "answer": f"操作未执行：{verr}",
                    "level": "失败",
                    "route": "action",
                    "route_reason": "工具入参校验失败",
                    "metrics": {},
                    "flags": [],
                    "llm": "tool",
                    "tools": [],
                }
                return {"result": result}
            if impl is not None and clean_args is not None:
                pending = {**pending, "args": clean_args}
                try:
                    ans = await impl(pending["args"])
                    result = {
                        "answer": ans,
                        "level": "已执行",
                        "route": "action",
                        "route_reason": (
                            "Write action confirmed by human (LangGraph interrupt/resume)"
                            if en
                            else "写操作已人工确认（LangGraph interrupt/resume）"
                        ),
                        "metrics": {},
                        "flags": [],
                        "llm": "tool",
                        "tools": [pending["tool_name"]],
                        "actions": [{"tab": "holdings"}],
                    }
                except Exception as exc:  # noqa: BLE001 — 执行失败给可读回执
                    # claim 已把状态改成 consumed，这里必须用「无条件置为 failed」
                    # （mark_pending_action 带 status='pending' 条件，对已消费行是空操作）。
                    # 否则记录停留在 consumed，用户与运维都看不出「执行失败过」。
                    await db.force_pending_status(token, "failed")
                    result = {
                        "answer": (
                            f"Execution failed: {type(exc).__name__}: {exc}. "
                            "No partial write should have occurred; retry the request if needed."
                            if en
                            else f"执行失败：{type(exc).__name__}: {exc}。"
                            "未产生部分写入，如需重试请重新发起该操作。"
                        ),
                        "level": "失败",
                        "route": "action",
                        "route_reason": (
                            "Write action failed" if en else "写操作执行异常"
                        ),
                        "metrics": {},
                        "flags": [],
                        "llm": "tool",
                        "tools": [pending["tool_name"]],
                    }
        else:
            await db.mark_pending_action(token, "cancelled")
            result = {
                "answer": "Cancelled — no changes were made."
                if en
                else "已取消该操作，未做任何改动。",
                "level": "已取消",
                "route": "action",
                "route_reason": "Write action cancelled" if en else "写操作已取消",
                "metrics": {},
                "flags": [],
                "llm": "tool",
                "tools": [],
            }
    return {"result": result}


async def memory(state: AgentState) -> dict[str, Any]:
    """记忆 agent：把「记住/记得 …」指令确定性写入长期记忆并回执（规则级，无需模型）。"""
    result = await service._try_save_memory(
        state["question"], _emit, state.get("lang", "zh")
    )
    assert result is not None
    return {"result": result}


async def studio_admin(state: AgentState) -> dict[str, Any]:
    """Studio 配置 agent：supervisor 已执行完配置写入，这里只回放执行结果。

    单独成节点（而不是在 supervisor 里直接 return result）是为了让图路由显式：
    配置改写是确定性副作用，不能落进财务管线，也不能被 collect_market 的取数覆盖。
    """
    result = state.get("result")
    if isinstance(result, dict):
        await _emit({"type": "text", "delta": str(result.get("answer") or "")})
    return {}

"""部门 agent（M3.3）：每个部门跑一轮独立的 agent 工具循环。

## 与 M3.1 的区别

M3.1 的部门执行是"直连确定性工具"：会计部固定调 `tool_get_ledger_view`
+ `tool_get_health_check`，输出格式写死在代码里。好处是零成本、可离线；
缺点是部门无法根据任务描述自己决定看什么——"核对分类质量"和"编收支表"
调的是同一批工具。

M3.3 让每个部门成为真正的 agent：
- **独立 instructions**：每个部门有自己的角色说明与产出要求
- **工具白名单**：只能调本部门的工具（由 `DEPT_TOOL_WHITELIST` 约束）
- **独立 thread_id**：断点可续（同一 thread 的历史状态可恢复）
- **token 预算**：超支自动收尾，防止单部门吃掉整轮预算

## 双路径设计

模型不可用时退回 M3.1 的确定性执行（`department._run_<dept>`）。
这不是妥协而是必要：部门模式必须离线可用（本地优先产品的底线），
而 agent 路径提供的是"更聪明的取数选择"，不是"唯一的取数方式"。
两条路径产出同一套 `(文本, metrics)` 契约，秘书对账逻辑零改动。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from . import agent, llm
from .dept_models import WorkOrder
from .logging_utils import get_logger

log = get_logger(__name__)

Emit = Callable[[dict[str, Any]], Awaitable[None]]

# 部门角色说明：告诉模型"你是谁、要产出什么"。
# 关键约束写进 instructions 而不是靠模型自觉：
#   - 数字必须来自工具（不许编）
#   - 必须给出结构化 metrics（秘书对账需要）
DEPT_INSTRUCTIONS: dict[str, str] = {
    "accounting": (
        "你是 Moneyhelper 财务部门的会计。职责是编制收支与结余报表，核对数字口径。\n"
        "要求：\n"
        "1. 必须调用工具获取真实数字，绝不编造\n"
        "2. 输出一句话结论 + 关键数字（本月收入/支出/结余）\n"
        "3. 最后一行必须是 JSON：{\"metrics\":{\"income\":数字,\"expense\":数字,\"net\":数字}}\n"
        "   （用于与其他部门交叉对账，字段必须是这三个）"
    ),
    "risk": (
        "你是 Moneyhelper 财务部门的风控专员。职责是扫描风险信号：集中度、应急金、"
        "高息负债、负债收入比、预算漂移。\n"
        "要求：\n"
        "1. 必须调用工具获取真实数据\n"
        "2. 按严重程度列出风险项，每条一句话\n"
        "3. 最后一行必须是 JSON：{\"metrics\":{\"risk_flags\":风险项数量}}"
    ),
    "invest": (
        "你是 Moneyhelper 财务部门的投资顾问。职责是复盘持仓与市场表现、看目标进度。\n"
        "要求：\n"
        "1. 必须调用工具获取真实持仓与行情\n"
        "2. 给出组合总市值、盈亏、最大持仓的集中度判断\n"
        "3. 最后一行必须是 JSON："
        "{\"metrics\":{\"total_market_value\":数字,\"total_pnl\":数字}}"
    ),
    "bookkeeping": (
        "你是 Moneyhelper 财务部门的记账专员。职责是核对流水与分类质量、看月度趋势。\n"
        "要求：\n"
        "1. 必须调用工具获取真实流水\n"
        "2. 指出分类异常（如大量「其他」分类）与趋势变化\n"
        "3. 最后一行必须是 JSON：{\"metrics\":{\"expense\":本月支出数字}}\n"
        "   （expense 必须与会计部口径一致，否则会被标为冲突）"
    ),
}

# 部门 → 允许调用的工具名（与 dept_dispatch.DEPT_TOOL_WHITELIST 保持一致）
DEPT_TOOLS: dict[str, tuple[str, ...]] = {
    "accounting": ("tool_get_ledger_view", "tool_get_health_check", "tool_get_trend"),
    "risk": ("tool_get_risk_flags", "tool_get_budget", "tool_get_health_check"),
    "invest": ("tool_get_market_view", "tool_get_goals", "tool_get_kline", "tool_get_quote"),
    "bookkeeping": ("tool_get_ledger_view", "tool_get_trend", "tool_get_budget"),
}

# tools.py 里的工具实现名（去 tool_ 前缀）→ 实现函数，供白名单映射
def _allowed_impls(dept: str) -> dict[str, Any]:
    from . import tools

    out: dict[str, Any] = {}
    for tool_name in DEPT_TOOLS.get(dept, ()):
        impl = getattr(tools, tool_name, None)
        if impl is None:
            continue
        # agent 循环按 function schema 里的名字查实现（无 tool_ 前缀）
        out[tool_name.removeprefix("tool_")] = impl
    return out


def _allowed_schemas(dept: str) -> list[dict[str, Any]]:
    """该部门可见的工具 schema（按白名单过滤）。"""
    from . import tools

    allowed = {n.removeprefix("tool_") for n in DEPT_TOOLS.get(dept, ())}
    return [
        t for t in tools.FINANCE_TOOLS if t["function"]["name"] in allowed
    ]


def _extract_metrics(text: str) -> tuple[str, dict[str, float]]:
    """从回答末尾提取 JSON metrics，返回 (去掉 metrics 行的正文, metrics)。

    设计取舍：让模型把 metrics 写成最后一行 JSON，而不是要求它用工具调用
    返回结构化结果——后者需要改工具签名，前者对模型更自然、对旧回答也更宽容
    （没写 metrics 就退化成空 dict，秘书对账会跳过该部门）。
    """
    if not text:
        return "", {}
    lines = text.rstrip().splitlines()
    for idx in range(len(lines) - 1, max(len(lines) - 6, -1), -1):
        line = lines[idx].strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        raw = data.get("metrics")
        if not isinstance(raw, dict):
            continue
        metrics: dict[str, float] = {}
        for k, v in raw.items():
            try:
                metrics[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
        if metrics:
            return "\n".join(lines[:idx]).rstrip(), metrics
    return text, {}


async def run_dept_agent(order: WorkOrder, emit: Emit | None = None) -> WorkOrder:
    """跑一个部门的 agent 工具循环，结果写回工单。

    模型不可用或 agent 循环失败 → 退回确定性执行（部门模式必须离线可用）。
    token 预算超支时保留已有产出并标记（M3.3 的"超支自动收尾"）。
    """
    from . import department

    order.status = "running"
    if emit:
        from .dept_models import order_to_dict

        await emit({"type": "dept", "order": order_to_dict(order), "status": "running"})

    result = await _try_agent(order, emit)
    if result is None:
        # 退回确定性执行：契约一致（(text, metrics)），对账逻辑不用改
        log.info("dept_agent.fallback dept=%s", order.dept)
        try:
            fn = getattr(department, f"_run_{order.dept}")
            text, metrics = await fn()
            order.output, order.metrics = text, metrics
            order.status = "done"
        except Exception as exc:  # noqa: BLE001
            log.warning("dept_agent.fallback_failed dept=%s error=%s", order.dept, exc)
            order.status, order.error = "failed", str(exc)[:200]
    else:
        order.output, order.metrics, order.tokens_used = result
        order.status = "done"
        if order.over_budget():
            # 超支不判失败：已有产出仍有价值，但要在呈批件里如实标注
            order.error = f"token 超支（{order.tokens_used}/{order.budget_tokens}）"

    if emit:
        from .dept_models import order_to_dict

        await emit({"type": "dept", "order": order_to_dict(order), "status": order.status})
    return order


async def _try_agent(
    order: WorkOrder, emit: Emit | None
) -> tuple[str, dict[str, float], int] | None:
    """尝试用 agent 路径执行；任何失败返回 None（由调用方降级）。"""
    if not await llm.llm_available():
        return None

    schemas = _allowed_schemas(order.dept)
    impls = _allowed_impls(order.dept)
    # 工单级白名单：派工阶段已经把模型编造/跨部门的工具名过滤掉了，
    # 这里是第二道闸——执行阶段真正收窄到工单声明的工具面。
    # 没有它，LLM 派工"只给这个部门两个工具"的约束等于无效。
    if order.tools_allowed:
        allowed = {n.removeprefix("tool_") for n in order.tools_allowed}
        schemas = [s for s in schemas if s["function"]["name"] in allowed]
        impls = {k: v for k, v in impls.items() if k in allowed}
    if not schemas or not impls:
        return None

    collected: list[dict[str, Any]] = []

    async def _sink(ev: dict[str, Any]) -> None:
        collected.append(ev)
        # 部门执行过程不外发 tool 事件（会与主问答的工具事件混淆），
        # 只把 agent 的关键节点转成部门事件流
        if emit and ev.get("type") in ("thinking", "text"):
            await emit({"type": "dept_activity", "dept": order.dept, "event": ev})

    # 独立 thread_id：部门内多轮可续，且不与主问答线程串扰
    thread_id = f"dept-{order.dept}-{uuid.uuid4().hex[:8]}"
    try:
        out = await agent.run_agent(
            order.task,
            _sink,
            lang="zh",
            system=DEPT_INSTRUCTIONS[order.dept],
            tools_list=schemas,
            impl_map=impls,
            inject_memories=False,  # 部门不注入用户记忆：记忆是主 agent 的上下文
        )
    except agent.AgentUnavailable as exc:
        log.info("dept_agent.unavailable dept=%s: %s", order.dept, exc)
        return None
    except Exception as exc:  # noqa: BLE001 — agent 层任何异常都降级
        log.warning("dept_agent.error dept=%s: %s", order.dept, exc)
        return None

    answer = str(out.get("answer") or "").strip()
    if not answer:
        return None
    body, metrics = _extract_metrics(answer)
    # token 用量：agent 未返回精确值，按字符数估算（4 字符 ≈ 1 token，偏保守）
    tokens_used = max(1, (len(answer) + sum(len(str(ev)) for ev in collected)) // 4)
    log.info(
        "dept_agent.done dept=%s thread=%s tokens~%d metrics=%s",
        order.dept,
        thread_id,
        tokens_used,
        list(metrics),
    )
    return body, metrics, tokens_used

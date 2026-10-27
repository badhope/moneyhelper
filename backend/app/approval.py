"""写操作审批：Web 对话与 MCP 共用的门槛判定与提示文案（M2.3）。

## 为什么单独成模块

大额审批此前只存在于 `agent_graph.record` 一条路径（Web 对话的一句话记账）。
MCP 暴露的写工具（`record_transaction` / `record_position` / `sell_position`）
是**完全没有审批**的——任何接入的 MCP 客户端都能直接改账本。这是真实的安全缺口：
单个 MCP 客户端 + 一次模型误判就能写入错误金额，且没有第二个人看过。

现在门槛判定集中在这里，两条路径用同一份规则：

    Web 对话:  agent_graph.record  → 超阈值 → nl_pending（问「确认/取消」）
    MCP:       mcp_server.<tool>   → 超阈值 → elicitation（客户端弹表单）

保持一致的判据，避免"Web 上要确认、MCP 上不用"这种让人困惑的差异。

## 阈值来源

`app/agents/default_config.json` 的 `defaults.approval_threshold`（默认 5000 元），
用户可在设置页调整。读取失败一律按默认值处理——审批是安全网，
不能因为配置读失败而失效。
"""

from __future__ import annotations

from typing import Any

DEFAULT_THRESHOLD = 5000.0
# 阈值下限：Studio「核心项锁定」承诺的落地。低于此值等于关掉写操作保护，
# 因此无论配置怎么写（含把 approval_threshold 改成 0/负数）都按 100 元执行。
MIN_THRESHOLD = 100.0


async def threshold() -> float:
    """当前大额审批阈值（元）。读配置失败返回默认值；永不低于 MIN_THRESHOLD。"""
    try:
        from . import agent_config

        cfg = await agent_config.get_config()
        raw = (cfg.get("defaults") or {}).get("approval_threshold", DEFAULT_THRESHOLD)
        value = float(raw)
        if value <= 0:
            return DEFAULT_THRESHOLD
        return max(value, MIN_THRESHOLD)
    except Exception:  # noqa: BLE001 — 审批不能因配置异常而失效
        return DEFAULT_THRESHOLD


async def needs_approval(amount: float) -> bool:
    """金额是否超过阈值（取绝对值，收入与支出同等对待）。"""
    if amount != amount:  # NaN
        return True
    return abs(float(amount)) > await threshold()


def format_approval_prompt(
    summary: str, amount: float, extra: str = "", lang: str = "zh"
) -> str:
    """生成审批提示文案（Web 的 nl_pending 与 MCP elicitation 共用）。"""
    if lang == "en":
        tail = f" ({extra})" if extra else ""
        return (
            f"This is a large amount: {summary}{tail}. "
            f"Confirm to record it?"
        )
    tail = f"，{extra}" if extra else ""
    return f"这笔金额较大：{summary}{tail}。确认要记吗？"


def describe_transaction(parsed: dict[str, Any], lang: str = "zh") -> str:
    """把一条解析结果描述成审批用的摘要。"""
    amount = float(parsed.get("amount", 0))
    direction = "收入" if amount > 0 else "支出"
    if lang == "en":
        direction = "income" if amount > 0 else "expense"
        return f"{parsed.get('item', 'item')} {abs(amount):,.2f} CNY ({direction})"
    return (
        f"{parsed.get('item', '未命名')} {abs(amount):,.2f} 元"
        f"（{parsed.get('category', '其他')} · {direction}）"
    )

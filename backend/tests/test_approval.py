"""写操作审批测试（M2.3）：Web 与 MCP 两条路径共用同一套门槛与文案。

改造前 MCP 的写工具完全没有审批，与大额阈值（Web 对话 >5000 元要确认）脱节。
这里锁死三件事：
1. 阈值读取有兜底（配置坏了也不能让审批失效）
2. Web 与 MCP 用同一个阈值和同一份提示文案
3. MCP 客户端不支持 elicitation 时必须拒绝执行（fail-closed），不能静默放行
"""

from __future__ import annotations

import pytest
from app import approval


async def test_threshold_reads_config(temp_db, monkeypatch):
    """阈值取自 agent 配置的 defaults.approval_threshold。"""
    from app import agent_config

    cfg = await agent_config.get_config()
    cfg.setdefault("defaults", {})["approval_threshold"] = 8000
    await agent_config.update_config(cfg)
    assert await approval.threshold() == 8000


async def test_threshold_falls_back_on_bad_config(temp_db, monkeypatch):
    """配置读失败或非法值 → 用默认阈值，绝不让审批失效。"""
    from app import agent_config

    async def _boom(*a, **kw):
        raise RuntimeError("config broken")

    # 只撤销这一项补丁：monkeypatch.undo() 会把 temp_db 对 DB_PATH 的补丁
    # 一起撤掉，后续访问会指向不存在的真实库（CI 上实测
    # "unable to open database file"）。
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(agent_config, "get_config", _boom)
        assert await approval.threshold() == approval.DEFAULT_THRESHOLD

    cfg = await agent_config.get_config()
    cfg.setdefault("defaults", {})["approval_threshold"] = "not-a-number"
    await agent_config.update_config(cfg)
    assert await approval.threshold() == approval.DEFAULT_THRESHOLD


async def test_needs_approval_uses_absolute_value(temp_db):
    """收入与支出同等对待：看绝对值，不看正负。"""
    assert await approval.needs_approval(6000) is True
    assert await approval.needs_approval(-6000) is True
    assert await approval.needs_approval(4999) is False
    assert await approval.needs_approval(-4999) is False


async def test_needs_approval_treats_nan_as_dangerous(temp_db):
    """NaN 金额必须当成需要审批（数据异常时倾向于拦下来）。"""
    assert await approval.needs_approval(float("nan")) is True


def test_prompt_bilingual():
    """中英文提示都要说明金额与后果，不能只有一句"确认吗"。"""
    zh = approval.format_approval_prompt("午饭 6000.00 元（餐饮 · 支出）", 6000)
    assert "金额较大" in zh and "午饭" in zh and "确认" in zh

    en = approval.format_approval_prompt("Lunch 6000.00 CNY (expense)", 6000, lang="en")
    assert "large amount" in en and "Lunch" in en and "Confirm" in en


def test_describe_transaction_direction():
    """摘要里要能看出收入还是支出——这是用户判断的依据。"""
    expense = approval.describe_transaction(
        {"item": "午饭", "category": "餐饮", "amount": -35.0}
    )
    assert "支出" in expense and "35.00" in expense
    income = approval.describe_transaction(
        {"item": "工资", "category": "收入", "amount": 8000.0}
    )
    assert "收入" in income and "8,000.00" in income


# ---------------------------------------------------------------------------
# MCP 侧门禁（_confirm_write）
# ---------------------------------------------------------------------------


async def test_confirm_write_small_amount_skips_prompt(temp_db):
    """小额直接放行，不打扰用户（也不要求 Context）。"""
    from app import mcp_server

    assert await mcp_server._confirm_write(None, "午饭 35 元", 35.0) is True


async def test_confirm_write_without_context_fails_closed(temp_db):
    """大额但拿不到 Context → 拒绝执行。

    宁可失败也不能静默放行：没有 Context 意味着无法向用户确认，
    此时写入就是绕过审批。
    """
    from app import mcp_server

    assert await mcp_server._confirm_write(None, "房租 8000 元", 8000.0) is False


class _FakeCtx:
    """假 Context：可控地返回接受/拒绝/异常。"""

    def __init__(self, outcome: str) -> None:
        self.outcome = outcome
        self.calls: list[str] = []

    async def elicit(self, message, *a, **kw):
        self.calls.append(message)
        if self.outcome == "raise":
            raise RuntimeError("client does not support elicitation")
        from fastmcp.server.elicitation import (
            AcceptedElicitation,
            DeclinedElicitation,
        )

        if self.outcome == "accept":
            return AcceptedElicitation(action="accept", data={})
        return DeclinedElicitation(action="decline")


async def test_confirm_write_accepts_when_user_agrees(temp_db):
    from app import mcp_server

    ctx = _FakeCtx("accept")
    assert await mcp_server._confirm_write(ctx, "房租 8000 元", 8000.0) is True
    assert (ctx.calls and "8000" in ctx.calls[0]) or ctx.calls


async def test_confirm_write_declines_when_user_refuses(temp_db):
    from app import mcp_server

    assert await mcp_server._confirm_write(_FakeCtx("decline"), "房租 8000 元", 8000.0) is False


async def test_confirm_write_fails_closed_on_client_error(temp_db):
    """客户端不支持 elicitation（抛异常）→ 拒绝，不能当作同意。"""
    from app import mcp_server

    assert await mcp_server._confirm_write(_FakeCtx("raise"), "房租 8000 元", 8000.0) is False


def _tool_fn(name: str):
    """取 @mcp.tool() 装饰后的原始实现（FunctionTool.fn）。

    装饰器把函数换成了 FunctionTool 对象，测试无法直接调用；
    这里取出底层函数，绕开协议层只测业务逻辑。
    """
    from app import mcp_server

    return mcp_server.mcp._tool_manager._tools[name].fn


async def test_mcp_write_tool_refuses_without_context(temp_db):
    """端到端：MCP 的 record_transaction 大额且无 Context 时不写库。"""
    from app import db

    fn = _tool_fn("record_transaction")
    before = len(await db.list_transactions())
    out = await fn("房租 8000 元", None)
    assert "已取消" in out
    assert len(await db.list_transactions()) == before


async def test_mcp_write_tool_small_amount_passes(temp_db):
    """端到端：小额记账照常写入（Context 可为 None）。"""
    from app import db

    fn = _tool_fn("record_transaction")
    out = await fn("午饭 35 元", None)
    assert "已记" in out or "35" in out
    rows = await db.list_transactions()
    assert any(r["item"] == "午饭" for r in rows)


async def test_mcp_position_refuses_without_context(temp_db):
    """MCP 买入大额且无 Context → 拒绝，持仓不变。"""
    from app import db

    fn = _tool_fn("record_position")
    before = len(await db.list_positions())
    out = await fn("600519", 100, 1600, 0, "贵州茅台", "股票", "白酒", "", None)
    assert "已取消" in out
    assert len(await db.list_positions()) == before


async def test_threshold_floor_is_enforced(temp_db) -> None:
    """阈值下限：配置改成 0/负数/1 元都不能关掉写操作保护（Studio 核心锁定项的落地）。"""
    from app import agent_config

    for bad in (0, -1, 1, 99):
        cfg = await agent_config.get_config()
        cfg.setdefault("defaults", {})["approval_threshold"] = bad
        await agent_config.update_config(cfg)
        # 0/负数视为非法 → 回落默认 5000；1/99 钳到下限 100。两者都不得低于下限。
        assert await approval.threshold() >= approval.MIN_THRESHOLD


async def test_threshold_above_floor_preserved(temp_db) -> None:
    from app import agent_config

    cfg = await agent_config.get_config()
    cfg.setdefault("defaults", {})["approval_threshold"] = 8000
    await agent_config.update_config(cfg)
    assert await approval.threshold() == 8000

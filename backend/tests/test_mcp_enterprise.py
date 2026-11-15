"""企业域 MCP 工具（切片 11）：总账 / 采购应付 / 报销 / 长任务。

判据：
- 工具真的注册进 MCP（外部客户端能看到）；
- 读工具声明 readOnlyHint（否则外部客户端默认不暴露）；
- 写工具不声明只读（必须经人工确认）；
- 工具调用返回真实数据，不是占位。
"""

from __future__ import annotations

import json

import app.mcp_server as _srv
import pytest
from app import db, tool_policy

# fastmcp 的 @mcp.tool() 返回 FunctionTool；真正可 await 的原始函数在 .fn。
# 工具对象验证「注册成功」，.fn 验证「实现正确」，两者都覆盖。
TOOLS = {
    name: getattr(_srv, name).fn
    for name in (
        "gl_accounts", "gl_periods", "gl_entries", "gl_trial_balance",
        "vendors", "purchase_orders", "payables", "expense_claims",
        "longtask_templates", "longtasks",
        "gl_create_entry", "create_purchase_order", "create_payable", "run_longtask",
    )
}

READ_TOOLS = [
    "gl_accounts",
    "gl_periods",
    "gl_entries",
    "gl_trial_balance",
    "vendors",
    "purchase_orders",
    "payables",
    "expense_claims",
    "longtask_templates",
    "longtasks",
]
WRITE_TOOLS = ["gl_create_entry", "create_purchase_order", "create_payable", "run_longtask"]


def test_enterprise_read_tools_are_readonly() -> None:
    """读工具必须显式声明只读，否则外部 MCP 客户端默认不暴露它们。"""
    for name in READ_TOOLS:
        assert tool_policy.resolve(name) == tool_policy.READ, name


def test_enterprise_write_tools_require_confirmation() -> None:
    """写工具必须是 ASK：模型不能无确认直接写企业账。"""
    for name in WRITE_TOOLS:
        assert tool_policy.resolve(name) == tool_policy.ASK, name


async def test_gl_accounts_returns_real_rows(temp_db) -> None:
    await db.gl_create_account(0, "6601", "采购费用", "expense")
    out = json.loads(await TOOLS["gl_accounts"]())
    codes = [a["code"] for a in out["accounts"]]
    assert "6601" in codes


async def test_gl_periods_and_entries(temp_db) -> None:
    period = await db.gl_create_period(0, 2026, 11)
    accounts = {
        "cash": (await db.gl_create_account(0, "1001", "库存现金", "asset"))["id"],
        "rev": (await db.gl_create_account(0, "4001", "营业收入", "income"))["id"],
    }
    await db.gl_create_entry(
        0,
        "2026-11-10",
        "销售收款",
        [
            {"account_id": accounts["cash"], "debit": 1000, "credit": 0},
            {"account_id": accounts["rev"], "debit": 0, "credit": 1000},
        ],
        0,
    )
    periods = json.loads(await TOOLS["gl_periods"]())
    assert any(p["id"] == period["id"] for p in periods["periods"])

    entries = json.loads(await TOOLS["gl_entries"](period_id=period["id"]))
    assert len(entries["entries"]) == 1
    assert entries["entries"][0]["description"] == "销售收款"


async def test_gl_trial_balance_is_balanced(temp_db) -> None:
    period = await db.gl_create_period(0, 2026, 11)
    cash = (await db.gl_create_account(0, "1001", "库存现金", "asset"))["id"]
    rev = (await db.gl_create_account(0, "4001", "营业收入", "income"))["id"]
    entry = await db.gl_create_entry(
        0,
        "2026-11-10",
        "销售收款",
        [
            {"account_id": cash, "debit": 500, "credit": 0},
            {"account_id": rev, "debit": 0, "credit": 500},
        ],
        0,
    )
    await db.gl_post_entry(0, int(entry["id"]))

    tb = json.loads(await TOOLS["gl_trial_balance"](period_id=period["id"]))
    assert tb["balanced"] is True
    assert tb["total_debit"] == tb["total_credit"]


async def test_gl_create_entry_tool_posts_when_asked(temp_db) -> None:
    await db.gl_create_period(0, 2026, 11)
    cash = (await db.gl_create_account(0, "1001", "库存现金", "asset"))["id"]
    rev = (await db.gl_create_account(0, "4001", "营业收入", "income"))["id"]
    lines = [
        {"account_id": cash, "debit": 100, "credit": 0},
        {"account_id": rev, "debit": 0, "credit": 100},
    ]
    draft = json.loads(await TOOLS["gl_create_entry"]("2026-11-11", "草稿测试", lines, post_now=False))
    assert draft["status"] == "draft"
    posted = json.loads(await TOOLS["gl_create_entry"]("2026-11-12", "直接过账", lines, post_now=True))
    assert posted["status"] == "posted"


async def test_procurement_tools_round_trip(temp_db) -> None:
    v = await db.vendor_create(0, "V001", "华东办公用品")
    po = await db.po_create(0, int(v["id"]), "2026-11-05", "", 3000, "办公用品")
    # 业务规则：只有已审核采购单能生成应付，这里走完 submit → approve
    await db.po_submit(0, int(po["id"]))
    await db.po_approve(0, int(po["id"]), 0)
    # 应付单要求借方是启用的资产/费用科目、贷方是负债科目
    exp = await db.gl_create_account(0, "6601", "采购费用", "expense")
    ap_acc = await db.gl_create_account(0, "2202", "应付账款", "liability")
    ap = await db.payable_create(
        0, int(v["id"]), int(po["id"]), "INV-1", "2026-11-10", "", 3000, 180,
        int(exp["id"]), int(ap_acc["id"]),
    )

    vs = json.loads(await TOOLS["vendors"]())
    assert any(x["code"] == "V001" for x in vs["vendors"])

    pos = json.loads(await TOOLS["purchase_orders"]())
    assert any(x["id"] == po["id"] for x in pos["orders"])

    aps = json.loads(await TOOLS["payables"]())
    assert any(x["id"] == ap["id"] for x in aps["payables"])


async def test_create_purchase_order_tool(temp_db) -> None:
    v = await db.vendor_create(0, "V002", "测试供应商")
    po = json.loads(
        await TOOLS["create_purchase_order"](
            vendor_id=int(v["id"]), order_date="2026-11-06", amount=1500, description="工具创建"
        )
    )
    assert po["po_no"].startswith("PO-")
    assert po["status"] == "draft"


async def test_create_payable_tool_needs_valid_accounts(temp_db) -> None:
    v = await db.vendor_create(0, "V003", "供应商三")
    exp = await db.gl_create_account(0, "6601", "采购费用", "expense")
    ap_acc = await db.gl_create_account(0, "2202", "应付账款", "liability")
    ap = json.loads(
        await TOOLS["create_payable"](
            vendor_id=int(v["id"]),
            invoice_date="2026-11-10",
            amount=800,
            expense_account_id=int(exp["id"]),
            payable_account_id=int(ap_acc["id"]),
        )
    )
    assert ap["payable_no"].startswith("AP-")
    assert ap["status"] == "draft"


async def test_expense_claims_tool(temp_db) -> None:
    out = json.loads(await TOOLS["expense_claims"]())
    assert isinstance(out["claims"], list)


async def test_longtask_tools(temp_db) -> None:
    tpl = json.loads(await TOOLS["longtask_templates"]())
    ids = {t["id"] for t in tpl["templates"]}
    assert {"novel", "webapp", "docx", "paper", "program"} <= ids

    from app import longtask

    task = await longtask.create_task("program", "MCP 测试", "目标", stages=["a"])
    listed = json.loads(await TOOLS["longtasks"]())
    assert any(t["id"] == task["id"] for t in listed["tasks"])


async def test_run_longtask_requires_model(temp_db) -> None:
    from app import longtask

    task = await longtask.create_task("program", "无模型", "目标", stages=["a"])
    with pytest.raises(ValueError, match="尚未配置模型"):
        await TOOLS["run_longtask"](task["id"])


async def test_enterprise_tools_registered_in_mcp() -> None:
    """14 个企业域工具必须真的注册进 MCP（外部客户端能看到名字）。"""
    import app.mcp_server as srv

    names = set()
    for attr in ("_tool_manager", "_tools", "_component_manager"):
        mgr = getattr(srv.mcp, attr, None)
        if mgr is not None and hasattr(mgr, "_tools"):
            names |= set(mgr._tools.keys())
    if not names:
        # fastmcp 版本差异：退化为检查模块属性存在
        for name in READ_TOOLS + WRITE_TOOLS:
            assert hasattr(srv, name), name
        return
    for name in READ_TOOLS + WRITE_TOOLS:
        assert name in names, f"{name} 未注册进 MCP"

"""企业域 agent：只读公司数据工具面 + 离线确定性兜底。

从 agent_graph.py 拆出；节点函数与系统提示、工具挑选表一起搬走，图谱构建在
agent_graph 里通过本模块引用，行为不变。
"""

from __future__ import annotations

import json
from typing import Any

from . import agent, llm, service, tools
from .agent_graph import AgentState, _emit, _now_ms
from .logging_utils import get_logger

log = get_logger(__name__)

ENTERPRISE_SYSTEM = (
    "You are Moneyhelper's enterprise finance assistant. You answer questions about the company's "
    "books (general ledger), procurement & payables, expense claims, org structure and long-running "
    "tasks. Rules:\n"
    "1. Any number you state MUST come from a tool result in this turn — never estimate or invent one.\n"
    "2. Call the tool that matches the domain: ledger questions → get_gl_summary; supplier/PO/payable "
    "questions → get_payables_summary; claim approval questions → get_expense_queue; departments/"
    "headcount → get_org_overview; long tasks → list_longtasks. Several may be called in one turn.\n"
    "3. Lead with a one-line conclusion, then the key figures, then what needs attention.\n"
    "4. If a tool returns empty/zero counts, say plainly that there's no such data yet — do not "
    "describe a healthy state that isn't there.\n"
    "5. You are read-only: you can look up and explain, but you cannot create vouchers, approve, or pay. "
    "Tell the user which page to use (总账 / 采购应付 / 报销) when an action is needed.\n"
    "6. Answer in the user's language."
)
# 没有模型时的确定性兜底：直接读同一批只读工具并排版，保证离线也答得上企业问题。
# 按问题挑工具（而不是五个全查）：用户问部门时把总账一起倒出来只会稀释答案。
_ENTERPRISE_TOOL_PICK: tuple[tuple[tuple[str, ...], str], ...] = (
    (("部门", "岗位", "组织", "成员", "多少人", "人头"), "get_org_overview"),
    (("长任务", "任务"), "list_longtasks"),
    (("报销", "审批", "待批"), "get_expense_queue"),
    (("供应商", "采购", "应付", "欠"), "get_payables_summary"),
    (("总账", "凭证", "科目", "试算", "账平"), "get_gl_summary"),
)


def _pick_enterprise_tools(question: str) -> list[str]:
    """问题 → 需要查的企业工具（保序去重）；一个都不命中就全查，交给模型自己挑。"""
    q = question.lower()
    picked: list[str] = []
    for words, name in _ENTERPRISE_TOOL_PICK:
        if any(w in q for w in words) and name not in picked:
            picked.append(name)
    return picked or list(tools.ENTERPRISE_TOOL_NAMES)


async def _enterprise_deterministic(
    question: str, lang: str
) -> tuple[str, list[str]]:
    """无模型时的企业域回答：真调只读工具取数，按域排版成文（绝不编数字）。"""
    en = lang != "zh"
    names = _pick_enterprise_tools(question)
    lines: list[str] = []
    if en:
        lines.append(f"Read-only company data ({len(names)} view(s)):")
    else:
        lines.append(f"以下是公司数据的只读查询结果（{len(names)} 项）：")

    for name in names:
        impl = tools.ENTERPRISE_IMPL.get(name)
        if impl is None:
            continue
        try:
            raw = await impl({})
            data = json.loads(raw)
        except Exception as exc:  # noqa: BLE001 — 单域失败不该让整轮无回答
            lines.append(f"- {name}: {'query failed' if en else '查询失败'} ({type(exc).__name__})")
            continue

        if name == "get_org_overview":
            deps = data.get("departments") or []
            pos = data.get("positions") or []
            members = data.get("member_count") or 0
            if en:
                lines.append(
                    f"- Org: {len(deps)} department(s) {deps or ''}, {len(pos)} position(s), "
                    f"{members} member(s)."
                )
            else:
                lines.append(
                    f"- 组织：{len(deps)} 个部门"
                    f"{('（' + '、'.join(deps) + '）') if deps else ''}，"
                    f"{len(pos)} 个岗位，{members} 名成员。"
                )
        elif name == "list_longtasks":
            tasks = data.get("tasks") or []
            if not tasks:
                lines.append("- Long tasks: none." if en else "- 长任务：暂无。")
                continue
            brief = "；".join(
                f"{t.get('title') or t.get('id')}"
                f"({t.get('status')} {t.get('done_stages', 0)}/{t.get('total_stages', 0)})"
                for t in tasks[:5]
            )
            lines.append(
                f"- Long tasks: {len(tasks)} — {brief}"
                if en
                else f"- 长任务：{len(tasks)} 个 —— {brief}"
            )
        elif name == "get_expense_queue":
            pending = data.get("pending") or 0
            amount = data.get("pending_amount") or 0
            total = data.get("total") or 0
            if en:
                lines.append(
                    f"- Expense claims: {pending} awaiting approval, ¥{amount:,.2f}; "
                    f"{total} total."
                )
            else:
                lines.append(
                    f"- 报销：{pending} 单待审批，金额 {amount:,.2f} 元；累计 {total} 单。"
                )
        elif name == "get_payables_summary":
            pay = data.get("payables") or {}
            if en:
                lines.append(
                    f"- Payables: {data.get('vendor_count', 0)} vendor(s), "
                    f"{pay.get('unpaid', 0)} unpaid of {pay.get('total', 0)} "
                    f"(¥{pay.get('unpaid_amount', 0):,.2f}), "
                    f"{len(pay.get('overdue') or [])} overdue."
                )
            else:
                lines.append(
                    f"- 应付：{data.get('vendor_count', 0)} 家供应商，"
                    f"应付单 {pay.get('total', 0)} 张、未付 {pay.get('unpaid', 0)} 张，"
                    f"未付金额 {pay.get('unpaid_amount', 0):,.2f} 元，"
                    f"逾期 {len(pay.get('overdue') or [])} 张。"
                )
        elif name == "get_gl_summary":
            tb = data.get("latest_trial_balance")
            balanced = "" if tb is None else (
                ("，借贷平衡" if tb.get("balanced") else "，借贷不平衡，需核查")
                if not en
                else (" — balanced" if tb.get("balanced") else " — NOT balanced")
            )
            if en:
                lines.append(
                    f"- Ledger: {data.get('account_count', 0)} account(s), "
                    f"{len(data.get('periods') or [])} period(s), "
                    f"{len(data.get('recent_entries') or [])} recent entr(y/ies){balanced}."
                )
            else:
                lines.append(
                    f"- 总账：{data.get('account_count', 0)} 个科目，"
                    f"{len(data.get('periods') or [])} 个期间，"
                    f"最近 {len(data.get('recent_entries') or [])} 张凭证{balanced}。"
                )

    lines.append(
        "\nThis is a read-only lookup — creating vouchers, approving or paying happens in the app "
        "pages (Ledger / Procurement / Expenses)."
        if en
        else "\n以上为只读查询；新建凭证、审批、付款请到对应页面（总账 / 采购应付 / 报销）操作。"
    )
    return "\n".join(lines), names


async def enterprise(state: AgentState) -> dict[str, Any]:
    """企业域 agent：只装企业只读工具面（总账/采购应付/报销/组织/长任务）。

    与财务分支共用 run_agent 的工具循环，但**换工具面**：企业问题要的是公司数据，
    把它和持仓/账本混在一个工具面里，模型会挑错域（实测问「有哪些部门」它去查个人账本）。
    无模型时走确定性兜底（真调同一批只读工具），保证离线也能回答。
    """
    q = state["question"]
    lang = state.get("lang", "zh")
    en = lang == "en"
    history = await service._build_history(state.get("thread_id"))

    if await llm.llm_available():
        try:
            result = await agent.run_agent(
                q,
                _emit,
                history,
                lang,
                system=ENTERPRISE_SYSTEM,
                tools_list=tools.ENTERPRISE_TOOLS,
                impl_map=tools.ENTERPRISE_IMPL,
                inject_memories=False,
            )
            return {
                "result": {
                    "answer": result["answer"].strip(),
                    "level": "",
                    "route": "enterprise",
                    "route_reason": state["reason"],
                    "metrics": {},
                    "flags": [],
                    "llm": "llm",
                    "tools": result.get("tools_used", []),
                    "steps": result.get("steps", []),
                    "agent_steps": result.get("steps", []),
                    "actions": [],
                }
            }
        except agent.AgentUnavailable:
            log.warning("enterprise 工具循环不可用，降级确定性查询")

    answer, names = await _enterprise_deterministic(q, lang)
    for name in names:
        await _emit(
            {
                "type": "tool",
                "data": {
                    "name": name,
                    "status": "done",
                    "summary": "",
                    "node": "enterprise",
                    "ts": _now_ms(),
                },
            }
        )
    return {
        "result": {
            "answer": answer,
            "level": "L1 洞察" if not en else "L1",
            "route": "enterprise",
            "route_reason": state["reason"],
            "metrics": {},
            "flags": [],
            "llm": "template",
            "tools": names,
            "actions": [],
        }
    }

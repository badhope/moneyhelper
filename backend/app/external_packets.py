"""外部协同前置包（4.20.0）。

把“需要税局/银行/审计/平台资质才能执行的最后一步”前置成可核对、可下载、
可交接的资料包。这里只读账本与计划，不提交申报、不发起付款、不出具法定意见：

- 税务申报核对包：月度已过账凭证汇总 + 勾稽检查 + 未完成事项；
- 付款指令包：资金计划里的流出项 + 收款方/账户/确定性检查，状态永远是草稿；
- 合并审计包：管理口径合并结果 + 主体状态 + 抵销 + 试算平衡 + 来源摘要。

包里的金额全部来自已有确定性数据，不调模型、不估算。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .timeutil import now_iso

_PERIOD_RE = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
_CASH_CODES = {"1001", "1002"}
_TAX_CODE = "2203"


def _period(value: Any) -> str:
    text = str(value or "").strip()
    if not _PERIOD_RE.fullmatch(text):
        raise ValueError("期间必须是 YYYY-MM")
    return text


def _money(cents: int | float | None) -> float:
    return round(float(cents or 0) / 100.0, 2)


def _hash(payload: Any, length: int = 16) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


def _check(item: str, status: str, detail: str) -> dict[str, str]:
    return {"id": item, "status": status, "detail": detail}


def _with_digest(packet: dict[str, Any], length: int = 32) -> dict[str, Any]:
    """给整份包（除生成时间与摘要本身）算稳定摘要，便于核对是否同一份底稿。"""
    core = {k: v for k, v in packet.items() if k not in {"generated_at", "source_hash"}}
    packet["source_hash"] = _hash(core, length)
    return packet


def _status(checks: list[dict[str, str]], *, has_data: bool) -> str:
    if not has_data:
        return "missing"
    if any(c["status"] == "blocked" for c in checks):
        return "blocked"
    if any(c["status"] in {"error", "review"} for c in checks):
        return "review"
    return "ready"


async def tax_packet(tenant_id: int, period: Any) -> dict[str, Any]:
    """税务申报核对包：只读单月已过账总账，不改账、不申报。"""
    from . import db

    label = _period(period)
    detail = await db.finance_timeline_month(tenant_id, label)
    entries = detail.get("entries") or []
    accounts: dict[str, dict[str, Any]] = {}
    income = expense = cash_in = cash_out = tax_accrued = tax_paid = 0
    for entry in entries:
        for line in entry.get("lines") or []:
            code = str(line.get("account_code") or "")
            name = str(line.get("account_name") or "")
            debit = round(float(line.get("debit") or 0) * 100)
            credit = round(float(line.get("credit") or 0) * 100)
            bucket = accounts.setdefault(
                code,
                {"account_code": code, "account_name": name, "debit_cents": 0, "credit_cents": 0},
            )
            bucket["debit_cents"] += debit
            bucket["credit_cents"] += credit
            account_type = str(line.get("account_type") or "")
            if account_type == "income":
                income += credit - debit
            elif account_type == "expense":
                expense += debit - credit
            if code in _CASH_CODES:
                cash_in += debit
                cash_out += credit
            if code == _TAX_CODE:
                tax_accrued += credit
                tax_paid += debit

    posted = int(detail.get("posted_entries") or 0)
    drafts = int(detail.get("draft_entries") or 0)
    total_debit = round(float((detail.get("totals") or {}).get("debit") or 0) * 100)
    total_credit = round(float((detail.get("totals") or {}).get("credit") or 0) * 100)
    balanced = total_debit == total_credit

    checks = [
        _check("period", "ok" if detail.get("status") != "missing" else "blocked",
               "会计期间存在" if detail.get("status") != "missing" else "该月没有会计期间"),
        _check("ledger_balanced", "ok" if balanced else "error",
               f"借方 {_money(total_debit):,.2f} / 贷方 {_money(total_credit):,.2f}"),
        _check("posted_entries", "ok" if posted > 0 else "blocked",
               f"{posted} 张已过账凭证"),
        _check("draft_entries", "ok" if drafts == 0 else "review",
               f"{drafts} 张草稿未过账"),
        _check("tax_accrual", "ok" if tax_accrued > 0 else "review",
               f"应交税费计提 {_money(tax_accrued):,.2f}；无计提时需确认是否零申报"),
        _check("bank_recon", "manual", "银行对账需人工核对未达账项"),
        _check("invoice_match", "manual", "进项/销项发票勾稽需人工查验"),
        _check("filing_channel", "blocked", "无税局直连资质，只能导出核对包后由人工申报"),
    ]
    summary = {
        "income": _money(income),
        "expense": _money(expense),
        "profit": _money(income - expense),
        "cash_in": _money(cash_in),
        "cash_out": _money(cash_out),
        "cash_net": _money(cash_in - cash_out),
        "tax_accrued": _money(tax_accrued),
        "tax_paid": _money(tax_paid),
        "tax_net": _money(tax_accrued - tax_paid),
        "debit": _money(total_debit),
        "credit": _money(total_credit),
    }
    packet_id = f"TAX-{label.replace('-', '')}-{_hash({'period': label, 'summary': summary, 'entries': entries}, 8)}"
    packet = {
        "packet_id": packet_id,
        "kind": "tax_filing_worksheet",
        "period": label,
        "generated_at": now_iso(),
        "status": _status(checks, has_data=posted > 0 and detail.get("status") != "missing"),
        "submission_status": "not_submitted",
        "period_status": str(detail.get("status") or ""),
        "closed_at": str(detail.get("closed_at") or ""),
        "posted_entries": posted,
        "draft_entries": drafts,
        "summary": summary,
        "account_summary": [
            {
                "account_code": v["account_code"],
                "account_name": v["account_name"],
                "debit": _money(v["debit_cents"]),
                "credit": _money(v["credit_cents"]),
                "balance": _money(v["debit_cents"] - v["credit_cents"]),
            }
            for v in sorted(accounts.values(), key=lambda x: x["account_code"])
        ],
        "checks": checks,
        "entries": entries,
        "boundary": (
            "核对包只读已过账总账，不生成申报表、不提交税局、不代表已申报或已完税；"
            "无税局直连资质。申报前请由税务人员复核发票、优惠资格与地方口径。"
        ),
    }
    return _with_digest(packet)


async def payment_packet(tenant_id: int, period: Any) -> dict[str, Any]:
    """付款指令包：资金计划的流出项转成人工执行草稿，不发起任何付款。"""
    from . import db

    label = _period(period)
    plan = await db.cash_plan_get(tenant_id, label)
    outs = [line for line in (plan.get("lines") or []) if line.get("direction") == "out"]
    instructions: list[dict[str, Any]] = []
    missing_counterparty = 0
    low_certainty = 0
    bad_account = 0
    for seq, line in enumerate(outs, 1):
        counterparty = str(line.get("counterparty") or "").strip()
        certainty = str(line.get("certainty") or "medium")
        account = str(line.get("account_code") or "")
        if not counterparty:
            missing_counterparty += 1
        if certainty == "low":
            low_certainty += 1
        if account not in _CASH_CODES:
            bad_account += 1
        instructions.append({
            "seq": seq,
            "expected_date": str(line.get("expected_date") or ""),
            "account_code": account,
            "counterparty": counterparty,
            "amount": float(line.get("amount") or 0),
            "amount_cents": int(line.get("amount_cents") or 0),
            "certainty": certainty,
            "note": str(line.get("note") or ""),
            "review": (
                "缺收款方" if not counterparty
                else "确定性低" if certainty == "low"
                else "账户非现金科目" if account not in _CASH_CODES
                else ""
            ),
        })
    total_cents = sum(int(x["amount_cents"]) for x in instructions)
    checks = [
        _check("plan", "ok" if plan.get("exists") else "blocked",
               "资金计划存在" if plan.get("exists") else "该月没有资金计划"),
        _check("out_lines", "ok" if outs else "review", f"{len(outs)} 条流出计划"),
        _check("counterparty", "ok" if missing_counterparty == 0 else "review",
               f"{missing_counterparty} 条缺收款方"),
        _check("certainty", "ok" if low_certainty == 0 else "review",
               f"{low_certainty} 条低确定性"),
        _check("cash_account", "ok" if bad_account == 0 else "error",
               f"{bad_account} 条非 1001/1002 账户"),
        _check("execution_channel", "blocked", "无持牌支付通道与用户授权，只能导出后人工执行"),
    ]
    batch_id = f"PAY-{label.replace('-', '')}-{_hash({'period': label, 'lines': instructions}, 8)}"
    packet = {
        "packet_id": batch_id,
        "kind": "payment_instruction",
        "period": label,
        "generated_at": now_iso(),
        "status": _status(checks, has_data=bool(plan.get("exists") and instructions)),
        "execution_status": "draft_only",
        "can_execute": False,
        "total": _money(total_cents),
        "total_cents": total_cents,
        "count": len(instructions),
        "opening": float((plan.get("plan") or {}).get("opening") or 0),
        "target_min": float((plan.get("plan") or {}).get("target_min") or 0),
        "instructions": instructions,
        "checks": checks,
        "boundary": (
            "付款指令包只是资金计划的流出草稿：不校验银行余额、不发起支付、不占用授信；"
            "本机不保存任何支付凭证。实际付款必须由持牌渠道与授权人执行并回传回单。"
        ),
    }
    return _with_digest(packet)


async def consolidation_packet(user_id: int, group_id: str, period: Any) -> dict[str, Any]:
    """合并审计包：管理口径合并底稿，明确不是法定审计意见。"""
    from . import db

    label = _period(period)
    report = await db.consolidation_report(user_id, group_id, label)
    entities = [
        {
            "tenant_id": int(e["tenant_id"]),
            "name": str(e.get("tenant_name") or e.get("name") or ""),
            "ownership_pct": float(e.get("ownership_pct") or 0),
            "method": str(e.get("method") or ""),
            "status": str(e.get("status") or ""),
            "included": bool(e.get("included")),
            "summary": e.get("summary") or {},
        }
        for e in (report.get("entities") or [])
    ]
    missing = [e["name"] or str(e["tenant_id"]) for e in entities if e["status"] != "ok"]
    balanced = bool(report.get("balanced"))
    checks = [
        _check("entities", "ok" if entities else "blocked", f"{len(entities)} 个主体"),
        _check("entity_status", "ok" if not missing else "review",
               "全部主体有已过账凭证" if not missing else "缺账/无过账：" + "、".join(missing)),
        _check("trial_balance", "ok" if balanced else "error", "合并试算借贷平衡" if balanced else "合并试算借贷不平"),
        _check("eliminations", "ok" if (report.get("adjustments") or []) else "manual",
               f"{len(report.get('adjustments') or [])} 张抵销分录；未识别内部交易"),
        _check("audit_basis", "blocked", "管理口径合并，不是法定合并/审计意见"),
    ]
    core = {
        "group": report.get("group"),
        "period": label,
        "entities": entities,
        "adjustments": report.get("adjustments") or [],
        "summary": report.get("summary") or {},
        "totals": report.get("totals") or {},
        "balanced": balanced,
        "warnings": report.get("warnings") or [],
    }
    packet_id = f"CON-{label.replace('-', '')}-{_hash(core, 8)}"
    packet = {
        "packet_id": packet_id,
        "kind": "consolidation_audit_pack",
        "period": label,
        "generated_at": now_iso(),
        "status": _status(checks, has_data=bool(entities)),
        "audit_status": "not_audited",
        "basis": "management",
        "group": report.get("group"),
        "entities": entities,
        "adjustments": report.get("adjustments") or [],
        "items": report.get("items") or [],
        "summary": report.get("summary") or {},
        "totals": report.get("totals") or {},
        "balanced": balanced,
        "warnings": report.get("warnings") or [],
        "checks": checks,
        "boundary": (
            "合并底稿按管理口径生成：只读各主体已过账凭证，full 需 100% 持股，"
            "proportional 按持股折算；不做法定合并、NCI、权益法、外币折算与审计意见。"
        ),
    }
    return _with_digest(packet)


__all__ = ["consolidation_packet", "payment_packet", "tax_packet"]

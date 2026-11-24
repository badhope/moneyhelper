"""AI 托管台：把“需要人点下一步”的财务动作变成可预设的策略。

三种模式：
- manual：只给计划和证据，不执行；用户仍走原有分步页面。
- assist：先生成计划，用户看过再点一次确认。
- auto：规则内直接执行；超过金额阈值、缺通道或数据阻断时回落到待确认/阻断。

当前动作接四个已有、可审计的能力：银行流水批量匹配、收支归因批量确认、企业月结、税务核对包外发。
不把税局申报、银行划款、审计意见等外部资质动作伪装成自动完成。
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from . import db
from .automation_runner import run_workflow
from .db import attribution as attribution_db
from .db.tenant import current_tenant_id, current_user_id
from .external_delivery import deliver, list_channels
from .external_packets import tax_packet
from .finance_attribution import suggest_attributions
from .provenance import record_provenance

ACTION_SPECS: dict[str, dict[str, Any]] = {
    "bank_match": {
        "key": "bank_match",
        "name": "银行流水批量匹配",
        "scope": "books",
        "description": "把本期未匹配的银行支出与付款记录配对，只配同账户、同金额、日期相近的唯一候选。",
        "defaults": {"max_amount": 50000.0, "window_days": 3},
        "boundary": "只改流水与付款的匹配关系，不动金额与余额；候选不唯一就跳过，可在银行页撤销。",
    },
    "attribution_confirm": {
        "key": "attribution_confirm",
        "name": "收支归因批量确认",
        "scope": "books",
        "description": "按月读取规则命中，只确认达到置信度阈值的分类，并留可回滚记录。",
        "defaults": {"max_amount": 10000.0, "min_confidence": 0.7},
        "boundary": "只改流水分类，不动金额、日期与余额；不拿历史同类去猜，确认可在归因页回滚。",
    },
    "tax_deliver": {
        "key": "tax_deliver",
        "name": "税务核对包交接",
        "scope": "tax",
        "description": "生成当期税务核对包，按规则交给已就绪的 SMTP 或税费网关。",
        "defaults": {"channel_id": "", "max_amount": 50000.0},
        "boundary": "只代表资料包已交到对端；不代表税局已申报或已完税。",
    },
    "month_end_close": {
        "key": "month_end_close",
        "name": "企业月结",
        "scope": "review",
        "description": "草稿凭证过账后关账，并读取关账快照。",
        "defaults": {},
        "boundary": "只处理本系统账期；不替代年审、汇算清缴或税务申报。",
    },
}

MODES = ("manual", "assist", "auto")
RUN_ORDER = ("bank_match", "attribution_confirm", "month_end_close", "tax_deliver")


def actions_catalog() -> list[dict[str, Any]]:
    return [{**spec} for spec in ACTION_SPECS.values()]


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _strict_float(value: Any, default: float, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field}必须是数字") from None
    if not math.isfinite(number):
        raise ValueError(f"{field}必须是有限数字")
    return number


def _strict_int(value: Any, default: int, field: str) -> int:
    """整数校验：3.0 可以，3.5 拒绝，避免静默截断。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field}必须是整数") from None
    if not math.isfinite(number) or number != int(number):
        raise ValueError(f"{field}必须是整数")
    return int(number)


def _normalize_config(action_key: str, config: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(config or {})
    if action_key == "tax_deliver":
        channel_id = str(raw.get("channel_id") or "").strip().lower()
        max_amount = _as_float(raw.get("max_amount"), 50000.0)
        if not math.isfinite(max_amount) or max_amount < 0:
            raise ValueError("金额阈值不能为负")
        return {"channel_id": channel_id, "max_amount": max_amount}
    if action_key == "bank_match":
        max_amount = _strict_float(raw.get("max_amount"), 50000.0, "金额阈值")
        if max_amount < 0:
            raise ValueError("金额阈值不能为负")
        window_days = _strict_int(raw.get("window_days", 3), 3, "日期窗口")
        if window_days < 0 or window_days > 30:
            raise ValueError("日期窗口需在 0 到 30 天之间")
        return {"max_amount": max_amount, "window_days": window_days}
    if action_key == "attribution_confirm":
        max_amount = _strict_float(raw.get("max_amount"), 10000.0, "金额阈值")
        if max_amount < 0:
            raise ValueError("金额阈值不能为负")
        min_confidence = _strict_float(
            raw.get("min_confidence"), 0.7, "最低置信度"
        )
        if min_confidence < 0 or min_confidence > 1:
            raise ValueError("最低置信度需在 0 到 1 之间")
        return {
            "max_amount": max_amount,
            "min_confidence": round(min_confidence, 4),
        }
    return {}


async def _policy_for(action_key: str) -> dict[str, Any]:
    spec = ACTION_SPECS[action_key]
    stored = await db.autopilot_get_policy(action_key)
    if not stored:
        return {
            "action_key": action_key,
            "mode": "manual",
            "enabled": True,
            "config": dict(spec["defaults"]),
            "updated_at": "",
        }
    return {
        **stored,
        "config": {**spec["defaults"], **stored.get("config", {})},
    }


async def list_policies() -> list[dict[str, Any]]:
    stored = {p["action_key"]: p for p in await db.autopilot_list_policies()}
    out = []
    for key, spec in ACTION_SPECS.items():
        base = stored.get(key)
        out.append(
            {
                "action_key": key,
                "name": spec["name"],
                "scope": spec["scope"],
                "description": spec["description"],
                "boundary": spec["boundary"],
                "mode": (base or {}).get("mode", "manual"),
                "enabled": bool((base or {}).get("enabled", True)),
                "config": {**spec["defaults"], **((base or {}).get("config") or {})},
                "updated_at": (base or {}).get("updated_at", ""),
            }
        )
    return out


async def save_policy(
    action_key: str, *, mode: str, enabled: bool, config: dict[str, Any] | None
) -> dict[str, Any]:
    if action_key not in ACTION_SPECS:
        raise ValueError("未知托管动作")
    normalized = _normalize_config(action_key, config)
    saved = await db.autopilot_save_policy(
        action_key, mode=mode, enabled=enabled, config=normalized
    )
    return {
        **ACTION_SPECS[action_key],
        **saved,
        "config": {**ACTION_SPECS[action_key]["defaults"], **saved.get("config", {})},
    }


def _tax_blockers(packet: dict[str, Any]) -> list[str]:
    return [
        str(c.get("id") or "")
        for c in packet.get("checks") or []
        if c.get("status") == "blocked" and str(c.get("id") or "") != "filing_channel"
    ]


async def _tax_plan(
    tenant_id: int, user_id: int, period: str, config: dict[str, Any]
) -> dict[str, Any]:
    packet = await tax_packet(tenant_id, period)
    if not packet.get("packet_id") or str(packet.get("status")) == "missing":
        return {
            "action_key": "tax_deliver",
            "decision": "blocked",
            "reason": "当期没有可投递的税务核对包",
            "period": period,
        }
    blockers = _tax_blockers(packet)
    if blockers:
        return {
            "action_key": "tax_deliver",
            "decision": "blocked",
            "reason": "资料包存在数据阻断项：" + "、".join(blockers[:3]),
            "period": period,
            "packet_id": packet.get("packet_id"),
        }
    channels = (await list_channels()).get("channels") or []
    ready = [
        c
        for c in channels
        if c.get("ready") and "tax" in (c.get("kinds") or [])
    ]
    wanted = str(config.get("channel_id") or "")
    channel = next(
        (c for c in ready if str(c.get("channel_id") or "") == wanted),
        None,
    )
    if wanted and channel is None:
        return {
            "action_key": "tax_deliver",
            "decision": "blocked",
            "reason": "指定的税务通道未就绪",
            "period": period,
            "packet_id": packet.get("packet_id"),
            "channel_id": wanted,
        }
    if channel is None:
        channel = ready[0] if ready else None
    if channel is None:
        return {
            "action_key": "tax_deliver",
            "decision": "blocked",
            "reason": "没有已就绪的税务投递通道",
            "period": period,
            "packet_id": packet.get("packet_id"),
        }

    summary = packet.get("summary") or {}
    amount = abs(_as_float(summary.get("tax_net"), 0.0))
    max_amount = _as_float(config.get("max_amount"), 50000.0)
    above = max_amount > 0 and amount > max_amount
    return {
        "action_key": "tax_deliver",
        "decision": "ready",
        "period": period,
        "packet_id": str(packet.get("packet_id")),
        "packet_status": str(packet.get("status")),
        "source_hash": str(packet.get("source_hash")),
        "channel_id": str(channel.get("channel_id")),
        "channel_label": str(channel.get("label")),
        "recipient": (
            ", ".join((channel.get("config") or {}).get("to_addrs") or [])
            if str(channel.get("channel_id")) == "smtp"
            else str(
                (channel.get("config") or {}).get("provider_name")
                or channel.get("label")
            )
        ),
        "amount": amount,
        "max_amount": max_amount,
        "requires_confirmation": above,
        "confirm_reason": f"税费净额 ¥{amount:,.2f} 超过预设阈值 ¥{max_amount:,.2f}"
        if above
        else "",
    }


async def _bank_match_plan(
    tenant_id: int, period: str, config: dict[str, Any]
) -> dict[str, Any]:
    try:
        start = date.fromisoformat(f"{period}-01")
    except ValueError:
        raise ValueError("账期需为 YYYY-MM") from None
    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)
    window_days = int(config.get("window_days", 3))
    max_amount = _as_float(config.get("max_amount"), 50000.0)
    candidates = await db.bank_match_candidates(
        tenant_id,
        start.isoformat(),
        end.isoformat(),
        window_days=window_days,
        limit=100,
    )
    items = candidates.get("items") or []
    if not items:
        return {
            "action_key": "bank_match",
            "decision": "blocked",
            "reason": (
                f"当期没有可唯一匹配的银行支出；金额/账户不符、"
                f"日期超过 {window_days} 天或候选不唯一都会跳过"
            ),
            "period": period,
            "skipped": int(candidates.get("skipped") or 0),
            "ambiguous": int(candidates.get("ambiguous") or 0),
            "window_days": window_days,
        }
    total_amount = round(
        sum(abs(_as_float(item.get("amount"), 0.0)) for item in items), 2
    )
    above = max_amount > 0 and total_amount > max_amount
    return {
        "action_key": "bank_match",
        "decision": "ready",
        "period": period,
        "count": len(items),
        "amount": total_amount,
        "max_amount": max_amount,
        "window_days": window_days,
        "pending": int(candidates.get("pending") or 0),
        "skipped": int(candidates.get("skipped") or 0),
        "ambiguous": int(candidates.get("ambiguous") or 0),
        "items": items,
        "preview": items[:6],
        "requires_confirmation": above,
        "confirm_reason": (
            f"本批待匹配金额合计 ¥{total_amount:,.2f} 超过预设阈值 "
            f"¥{max_amount:,.2f}"
            if above
            else ""
        ),
    }


async def _attribution_plan(
    tenant_id: int, user_id: int, period: str, config: dict[str, Any]
) -> dict[str, Any]:
    rows = await db.list_transactions_by_month(period)
    confirmations = await attribution_db.list_confirmations(tenant_id, user_id)
    rules = await attribution_db.list_rules(
        tenant_id, user_id, enabled_only=True
    )
    suggested = suggest_attributions(
        rows, confirmations, limit=100, custom_rules=rules
    )
    min_confidence = _as_float(config.get("min_confidence"), 0.7)
    max_amount = _as_float(config.get("max_amount"), 10000.0)

    items: list[dict[str, Any]] = []
    for row in suggested.get("transactions") or []:
        candidate = row.get("candidate") or {}
        source = str(candidate.get("source") or "")
        category = str(candidate.get("category") or "")
        confidence = _as_float(candidate.get("confidence"), 0.0)
        # 只自动确认规则命中。历史同类最多 0.78，仍可能是“同一商户、不同用途”，
        # 不能因为出现过两次就替用户改账。
        if source not in {"custom_rule", "rule"}:
            continue
        if not category or confidence + 1e-9 < min_confidence:
            continue
        items.append(
            {
                "transaction_id": int(row["transaction_id"]),
                "date": str(row.get("date") or ""),
                "item": str(row.get("item") or "")[:80],
                "amount": round(_as_float(row.get("amount"), 0.0), 2),
                "current_category": str(row.get("current_category") or ""),
                "category": category,
                "source": source,
                "confidence": round(confidence, 4),
                "rule_id": str(candidate.get("rule_id") or ""),
                "matched": [
                    str(x)[:24] for x in (candidate.get("matched") or []) if str(x)
                ][:5],
                "reason": str(candidate.get("reason") or "")[:160],
            }
        )

    if not items:
        return {
            "action_key": "attribution_confirm",
            "decision": "blocked",
            "reason": (
                f"当期没有达到置信度 {min_confidence:.2f} 的规则候选；"
                "历史同类不会自动确认"
            ),
            "period": period,
            "pending": int(suggested.get("pending") or 0),
            "min_confidence": min_confidence,
        }

    total_amount = round(
        sum(abs(_as_float(item.get("amount"), 0.0)) for item in items), 2
    )
    above = max_amount > 0 and total_amount > max_amount
    source_counts: dict[str, int] = {}
    for item in items:
        source_counts[item["source"]] = source_counts.get(item["source"], 0) + 1

    return {
        "action_key": "attribution_confirm",
        "decision": "ready",
        "period": period,
        "count": len(items),
        "pending": int(suggested.get("pending") or 0),
        "skipped": max(0, int(suggested.get("pending") or 0) - len(items)),
        "amount": total_amount,
        "max_amount": max_amount,
        "min_confidence": min_confidence,
        "source_counts": source_counts,
        "items": items,
        "preview": items[:6],
        "requires_confirmation": above,
        "confirm_reason": (
            f"本批待确认金额合计 ¥{total_amount:,.2f} 超过预设阈值 "
            f"¥{max_amount:,.2f}"
            if above
            else ""
        ),
    }


async def _execute_bank_match(plan: dict[str, Any]) -> dict[str, Any]:
    tenant, user = current_tenant_id(), current_user_id()
    pairs = [
        {
            "transaction_id": int(item["transaction_id"]),
            "payment_id": int(item["payment_id"]),
        }
        for item in (plan.get("items") or [])
    ]
    if not pairs:
        return {"matched": 0, "items": []}
    matched = await db.bank_match_batch(
        tenant,
        pairs,
        user,
        window_days=int(plan.get("window_days") or 3),
    )
    for item in matched:
        await record_provenance(
            "bank_match",
            "bank_transaction",
            str(item["id"]),
            before={"status": "unmatched"},
            after={"status": "matched", "payment_id": item.get("payment_id")},
            source="autopilot",
            metadata={
                "payment_no": item.get("payment_no"),
                "amount": item.get("amount"),
                "txn_date": item.get("txn_date"),
                "batch": True,
                "period": str(plan.get("period") or ""),
            },
        )
    return {"matched": len(matched), "items": matched[:20]}


async def _execute_attribution(plan: dict[str, Any]) -> dict[str, Any]:
    tenant, user = current_tenant_id(), current_user_id()
    items = [
        {
            "transaction_id": int(item["transaction_id"]),
            "original_category": str(item["current_category"]),
            "confirmed_category": str(item["category"]),
            "source": str(item["source"]),
            "rule_id": str(item.get("rule_id") or ""),
            "confidence": _as_float(item.get("confidence"), 0.0),
            "matched": list(item.get("matched") or []),
        }
        for item in (plan.get("items") or [])
    ]
    if not items:
        return {"confirmed": 0, "items": []}
    written = await attribution_db.batch_apply_confirmations(
        tenant_id=tenant, user_id=user, items=items
    )
    for item in written:
        await record_provenance(
            "attribution_confirm",
            "transaction",
            str(item["transaction_id"]),
            before={"category": item["previous_category"]},
            after={"category": item["category"]},
            source="autopilot",
            metadata={
                "rule_id": item["rule_id"],
                "confidence": item["confidence"],
                "matched": item["matched"],
                "attribution_source": item["source"],
                "batch": True,
                "period": str(plan.get("period") or ""),
            },
        )
    return {"confirmed": len(written), "items": written[:20]}


async def _month_end_plan(period: str) -> dict[str, Any]:
    return {
        "action_key": "month_end_close",
        "decision": "ready",
        "period": period,
        "steps": ["月度自动结账", "关账状态快照"],
        "requires_confirmation": False,
        "confirm_reason": "",
    }


async def build_plan(
    action_key: str, *, period: str = "", config: dict[str, Any] | None = None
) -> dict[str, Any]:
    if action_key not in ACTION_SPECS:
        raise ValueError("未知托管动作")
    period = str(period or "").strip() or date.today().strftime("%Y-%m")
    cfg = {**ACTION_SPECS[action_key]["defaults"], **(config or {})}
    if action_key == "tax_deliver":
        return await _tax_plan(current_tenant_id(), current_user_id(), period, cfg)
    if action_key == "bank_match":
        return await _bank_match_plan(current_tenant_id(), period, cfg)
    if action_key == "attribution_confirm":
        return await _attribution_plan(
            current_tenant_id(), current_user_id(), period, cfg
        )
    return await _month_end_plan(period)


async def _execute_plan(plan: dict[str, Any]) -> dict[str, Any]:
    action_key = str(plan["action_key"])
    if action_key == "tax_deliver":
        return await deliver(
            str(plan["channel_id"]),
            "tax",
            current_tenant_id(),
            current_user_id(),
            period=str(plan.get("period") or ""),
            note="AI 托管自动交接：规则内执行",
        )
    if action_key == "month_end_close":
        return await run_workflow(
            "enterprise_month_end",
            trigger="autopilot",
            idempotency_key=f"autopilot:{current_tenant_id()}:{plan.get('period')}",
        )
    if action_key == "bank_match":
        return await _execute_bank_match(plan)
    if action_key == "attribution_confirm":
        return await _execute_attribution(plan)
    raise ValueError("未知托管动作")


async def run_action(
    action_key: str,
    *,
    confirm: bool = False,
    period: str = "",
    config: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    if action_key not in ACTION_SPECS:
        raise ValueError("未知托管动作")
    policy = await _policy_for(action_key)
    if not policy.get("enabled", True):
        result = {
            "action_key": action_key,
            "mode": policy["mode"],
            "decision": "blocked",
            "reason": "该动作已被用户停用",
        }
        await db.autopilot_record_decision(
            action_key, mode=policy["mode"], decision="blocked", summary=result
        )
        return result

    plan = await build_plan(
        action_key, period=period, config=policy.get("config") or {}
    )
    mode = str(policy["mode"])
    if plan["decision"] != "ready":
        result = {**plan, "mode": mode}
        await db.autopilot_record_decision(
            action_key, mode=mode, decision="blocked", summary=result
        )
        return result

    if dry_run:
        result = {**plan, "mode": mode, "decision": "manual", "dry_run": True}
        await db.autopilot_record_decision(
            action_key, mode=mode, decision="manual", summary=result
        )
        return result

    if mode == "manual":
        result = {**plan, "mode": mode, "decision": "manual"}
        await db.autopilot_record_decision(
            action_key, mode=mode, decision="manual", summary=result
        )
        return result

    needs_confirm = plan.get("requires_confirmation") or mode != "auto"
    if needs_confirm and not confirm:
        result = {**plan, "mode": mode, "decision": "awaiting"}
        await db.autopilot_record_decision(
            action_key, mode=mode, decision="awaiting", summary=result
        )
        return result

    try:
        outcome = await _execute_plan(plan)
    except Exception as exc:  # noqa: BLE001 — 执行失败要落决策，不吞成 500
        result = {
            **plan,
            "mode": mode,
            "decision": "failed",
            "reason": str(exc)[:300],
        }
        await db.autopilot_record_decision(
            action_key, mode=mode, decision="failed", summary=result
        )
        return result

    result = {
        **plan,
        "mode": mode,
        "decision": "executed",
        "outcome": outcome,
    }
    await db.autopilot_record_decision(
        action_key, mode=mode, decision="executed", summary=result
    )
    return result


async def run_all(
    *, confirm: bool = False, period: str = "", dry_run: bool = False
) -> dict[str, Any]:
    results = []
    for key in RUN_ORDER:
        policy = await _policy_for(key)
        if not policy.get("enabled", True):
            continue
        results.append(
            await run_action(
                key, confirm=confirm, period=period, dry_run=dry_run
            )
        )
    return {"period": period or date.today().strftime("%Y-%m"), "results": results}


async def overview() -> dict[str, Any]:
    policies = await list_policies()
    channels = (await list_channels()).get("channels") or []
    ready = [c for c in channels if c.get("ready")]
    decisions = await db.autopilot_list_decisions(8)
    stats = await db.autopilot_decision_stats()
    counts = {"manual": 0, "assist": 0, "auto": 0}
    for p in policies:
        counts[p["mode"]] = counts.get(p["mode"], 0) + 1
    return {
        "period": date.today().strftime("%Y-%m"),
        "policies": policies,
        "actions": actions_catalog(),
        "ready_channels": [
            {
                "channel_id": c.get("channel_id"),
                "label": c.get("label"),
                "kinds": c.get("kinds") or [],
            }
            for c in ready
        ],
        "stats": stats,
        "mode_counts": counts,
        "recent": decisions,
    }

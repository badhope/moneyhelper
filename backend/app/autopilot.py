"""AI 托管台：把“需要人点下一步”的财务动作变成可预设的策略。

三种模式：
- manual：只给计划和证据，不执行；用户仍走原有分步页面。
- assist：先生成计划，用户看过再点一次确认。
- auto：规则内直接执行；超过金额阈值、缺通道或数据阻断时回落到待确认/阻断。

当前动作只接两个已有、可审计的能力：税务核对包外发、企业月结。
不把税局申报、银行划款、审计意见等外部资质动作伪装成自动完成。
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from . import db
from .automation_runner import run_workflow
from .db.tenant import current_tenant_id, current_user_id
from .external_delivery import deliver, list_channels
from .external_packets import tax_packet

ACTION_SPECS: dict[str, dict[str, Any]] = {
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
RUN_ORDER = ("month_end_close", "tax_deliver")


def actions_catalog() -> list[dict[str, Any]]:
    return [{**spec} for spec in ACTION_SPECS.values()]


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _normalize_config(action_key: str, config: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(config or {})
    if action_key == "tax_deliver":
        channel_id = str(raw.get("channel_id") or "").strip().lower()
        max_amount = _as_float(raw.get("max_amount"), 50000.0)
        if not math.isfinite(max_amount) or max_amount < 0:
            raise ValueError("金额阈值不能为负")
        return {"channel_id": channel_id, "max_amount": max_amount}
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

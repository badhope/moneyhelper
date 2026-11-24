"""公司财税路由（v4.5）：税负测算 / 个税 / 工资核算 / 月结清单 / 现金流预测 /
订阅识别 / 异常扣款。

所有计算都在 calculations 包（纯函数），本层只做参数清洗与落库组装。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends

from .. import db
from ..auth import get_current_user
from ..automation_runner import list_workflows, replay_run, run_workflow
from ..calculations import (
    cashflow_forecast,
    corporate_income_tax,
    detect_anomalies,
    detect_subscriptions,
    individual_income_tax,
    month_end_checklist,
    payroll,
    tax_summary,
    vat,
)
from ..db import attribution as attribution_db
from ..db import automation as automation_db
from ..db.tenant import current_tenant_id, current_user_id
from ..finance_attribution import suggest_attributions, validate_category
from ..provenance import record_provenance
from ._responses import bad as _bad

router = APIRouter(dependencies=[Depends(get_current_user)])




def _f(payload: dict[str, Any], key: str, default: float = 0.0) -> float:
    """读取数值参数；只有缺省/None/空串才回落默认值。

    不能用 `value or default`：显式传入 0 是合法值（例如零税率、零成本），
    被 `or` 替换成默认税率会静默改变计算结果。
    """
    raw = (payload or {}).get(key, default)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{key} 必须是数字") from None


# ---------------------------------------------------------------------------
# 税负
# ---------------------------------------------------------------------------


@router.post("/api/finance/tax/vat")
async def calc_vat(payload: dict[str, Any]) -> Any:
    try:
        return vat(
            sales=_f(payload, "sales"),
            purchases=_f(payload, "purchases"),
            rate=_f(payload, "rate", 0.13),
            simple=bool((payload or {}).get("simple")),
            simple_rate=_f(payload, "simple_rate", 0.03),
            location=str((payload or {}).get("location") or "city"),
            exempt_threshold=_f(payload, "exempt_threshold"),
        )
    except ValueError as exc:
        return _bad(str(exc))


@router.post("/api/finance/tax/cit")
async def calc_cit(payload: dict[str, Any]) -> Any:
    try:
        return corporate_income_tax(
            revenue=_f(payload, "revenue"),
            cost=_f(payload, "cost"),
            expenses=_f(payload, "expenses"),
            other_deductions=_f(payload, "other_deductions"),
            loss_carryforward=_f(payload, "loss_carryforward"),
            category=str((payload or {}).get("category") or "standard"),
            tax_adjustments=_f(payload, "tax_adjustments"),
        )
    except ValueError as exc:
        return _bad(str(exc))


@router.post("/api/finance/tax/iit")
async def calc_iit(payload: dict[str, Any]) -> Any:
    try:
        return individual_income_tax(
            monthly_salary=_f(payload, "monthly_salary"),
            months=int((payload or {}).get("months") or 1),
            social_insurance=_f(payload, "social_insurance"),
            housing_fund=_f(payload, "housing_fund"),
            special_additional=_f(payload, "special_additional"),
            other_deductions=_f(payload, "other_deductions"),
            already_withheld=_f(payload, "already_withheld"),
        )
    except ValueError as exc:
        return _bad(str(exc))


@router.post("/api/finance/tax/payroll")
async def calc_payroll(payload: dict[str, Any]) -> Any:
    try:
        result = payroll(
            gross_salary=_f(payload, "gross_salary"),
            social_base=_f(payload, "social_base") if (payload or {}).get("social_base") else None,
            housing_base=_f(payload, "housing_base") if (payload or {}).get("housing_base") else None,
            base_min=_f(payload, "base_min", 3500),
            base_max=_f(payload, "base_max", 35000),
            # 公积金上下限独立：多数城市公积金上限高于社保，共用 base_max
            # 会把用户显式传入的高基数悄悄压回社保上限。不传则沿用社保口径。
            housing_base_min=(
                _f(payload, "housing_base_min") if (payload or {}).get("housing_base_min") else None
            ),
            housing_base_max=(
                _f(payload, "housing_base_max") if (payload or {}).get("housing_base_max") else None
            ),
            special_additional=_f(payload, "special_additional"),
            other_deductions=_f(payload, "other_deductions"),
            already_withheld=_f(payload, "already_withheld"),
            months=int((payload or {}).get("months") or 1),
            employee_rates=(payload or {}).get("employee_rates") or None,
            employer_rates=(payload or {}).get("employer_rates") or None,
        )
    except ValueError as exc:
        return _bad(str(exc))
    return {
        "gross": result.gross,
        "employee": result.employee,
        "employer": result.employer,
        "employee_total": result.employee_total,
        "employer_total": result.employer_total,
        "taxable_income": result.taxable_income,
        "income_tax": result.income_tax,
        # months>1 时 income_tax 是累计口径：单月与期间两个实发都给出，
        # 前端不必自己猜该减哪一份。
        "current_month_tax": result.current_month_tax,
        "net_pay": result.net_pay,
        "period_net_pay": result.period_net_pay,
        "employer_cost": result.employer_cost,
        "notes": result.notes,
        "disclaimer": "社保/公积金比例按通用城镇职工默认值，各地差异大，请按本地口径调整参数。",
    }


@router.post("/api/finance/tax/summary")
async def calc_tax_summary(payload: dict[str, Any]) -> Any:
    try:
        return tax_summary(
            revenue=_f(payload, "revenue"),
            cost=_f(payload, "cost"),
            expenses=_f(payload, "expenses"),
            vat_rate=_f(payload, "vat_rate", 0.13),
            vat_simple=bool((payload or {}).get("vat_simple")),
            location=str((payload or {}).get("location") or "city"),
            cit_category=str((payload or {}).get("cit_category") or "standard"),
            payroll_gross=_f(payload, "payroll_gross"),
            payroll_months=int((payload or {}).get("payroll_months") or 12),
        )
    except ValueError as exc:
        return _bad(str(exc))


@router.get("/api/finance/month-end/{month}")
async def get_month_end(month: str, completed: str = "") -> Any:
    """月度结账清单；completed 传逗号分隔的已完成项 id。"""
    try:
        return month_end_checklist(month, completed=[c for c in completed.split(",") if c])
    except ValueError as exc:
        return _bad(str(exc))


# ---------------------------------------------------------------------------
# 现金流 / 订阅 / 异常（用真实账本数据）
# ---------------------------------------------------------------------------


async def _all_transactions() -> list[dict[str, Any]]:
    return await db.list_transactions()


@router.get("/api/finance/cashflow/forecast")
async def forecast(months_ahead: int = 3, opening_balance: float | None = None) -> dict[str, Any]:
    """现金流三档预测。opening_balance 缺省时用账本现金类资产估算。"""
    positions = await db.list_positions()
    cash = sum(
        float(p.get("shares", 0)) * float(p.get("last", 0))
        for p in positions
        if p.get("kind") == "现金"
    )
    return cashflow_forecast(
        await _all_transactions(),
        months_ahead=max(1, min(months_ahead, 12)),
        opening_balance=cash if opening_balance is None else float(opening_balance),
    )


@router.get("/api/finance/subscriptions/detect")
async def subscriptions_detect() -> dict[str, Any]:
    """从流水里识别订阅：含涨价标记与下次扣款日。"""
    return detect_subscriptions(await _all_transactions(), as_of=date.today())


@router.get("/api/finance/anomalies")
async def anomalies(lookback_days: int = 180) -> dict[str, Any]:
    return detect_anomalies(
        await _all_transactions(),
        as_of=date.today(),
        lookback_days=max(30, min(lookback_days, 730)),
    )


# ---------------------------------------------------------------------------
# 财税时序（4.17.1）：只读总账已过账凭证，按月压成一条时间轴
# ---------------------------------------------------------------------------


@router.get("/api/finance/timeline")
async def finance_timeline_view(months: int = 12) -> Any:
    return await db.finance_timeline(current_tenant_id(), months=months)


@router.get("/api/finance/timeline/{month}")
async def finance_timeline_month_view(month: str) -> Any:
    try:
        return await db.finance_timeline_month(current_tenant_id(), month)
    except ValueError as exc:
        return _bad(str(exc))


# ---------------------------------------------------------------------------
# 收支归因（4.17.1）：规则/历史候选 + 用户确认，确认前不改账
# ---------------------------------------------------------------------------


@router.get("/api/finance/attribution/candidates")
async def attribution_candidates(limit: int = 50) -> Any:
    rows = await db.list_transactions(limit=800)
    confirmations = await attribution_db.list_confirmations(
        current_tenant_id(), current_user_id()
    )
    rules = await attribution_db.list_rules(
        current_tenant_id(), current_user_id(), enabled_only=True
    )
    out = suggest_attributions(
        rows, confirmations, limit=limit, custom_rules=rules
    )
    out["scan_limit"] = 800
    return out


def _rule_text(value: Any, field: str, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        raise ValueError(f"{field}不能为空")
    if len(text) > limit:
        raise ValueError(f"{field}不能超过 {limit} 个字")
    if any(ord(ch) < 32 for ch in text):
        raise ValueError(f"{field}不能包含控制字符")
    return text


def _rule_fields(body: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
    base = current or {}
    keyword = _rule_text(body.get("keyword", base.get("keyword")), "关键词", 30)
    name = _rule_text(body.get("name", base.get("name")) or keyword, "规则名", 40)
    category = validate_category(body.get("category", base.get("category")))
    direction = str(body.get("direction", base.get("direction")) or "").strip()
    if direction not in {"", "收入", "支出"}:
        raise ValueError("方向只能是空、收入或支出")
    try:
        priority = int(body.get("priority", base.get("priority", 0)) or 0)
    except (TypeError, ValueError):
        raise ValueError("优先级必须是整数") from None
    if priority < -100 or priority > 100:
        raise ValueError("优先级需在 -100 到 100 之间")
    raw_enabled = body.get("enabled", base.get("enabled", True))
    enabled = bool(int(raw_enabled)) if isinstance(raw_enabled, (int, bool)) else bool(raw_enabled)
    merchant = " ".join(str(body.get("merchant", base.get("merchant")) or "").split()).strip()
    if len(merchant) > 30:
        raise ValueError("商户不能超过 30 个字")
    try:
        min_cents = int(body.get("min_amount_cents", base.get("min_amount_cents", 0)) or 0)
        max_cents = int(body.get("max_amount_cents", base.get("max_amount_cents", 0)) or 0)
    except (TypeError, ValueError):
        raise ValueError("金额区间必须是整数分") from None
    if min_cents < 0 or max_cents < 0:
        raise ValueError("金额区间不能为负")
    if min_cents and max_cents and max_cents < min_cents:
        raise ValueError("金额上限不能小于下限")
    raw_member = body.get("member_id", base.get("member_id"))
    if raw_member in (None, "", 0, "0"):
        member_id = None
    else:
        try:
            member_id = int(raw_member)
        except (TypeError, ValueError):
            raise ValueError("成员必须是整数 id") from None
        if member_id <= 0:
            raise ValueError("成员 id 必须是正整数")
    return {
        "name": name,
        "keyword": keyword,
        "category": category,
        "direction": direction,
        "priority": priority,
        "enabled": enabled,
        "merchant": merchant,
        "min_amount_cents": min_cents,
        "max_amount_cents": max_cents,
        "member_id": member_id,
    }


@router.get("/api/finance/attribution/rules")
async def attribution_rules() -> Any:
    tenant, user = current_tenant_id(), current_user_id()
    rules = await attribution_db.list_rules(tenant, user)
    stats = await attribution_db.confirmation_stats(tenant, user)
    confirmed = {(r["rule_id"], r["source"]): int(r["n"]) for r in stats["by_rule"]}
    reverted = {str(r["rule_id"]): int(r["n"]) for r in stats["reverted_by_rule"]}
    for rule in rules:
        rule["confirmed"] = confirmed.get((rule["rule_id"], "custom_rule"), 0)
        rule["reverted"] = reverted.get(rule["rule_id"], 0)
    return {
        "rules": rules,
        "count": len(rules),
        "enabled": sum(1 for r in rules if int(r.get("enabled") or 0) == 1),
        "max_rules": 20,
        "categories": [
            c for c in suggest_attributions([], {}, limit=1, custom_rules=rules)["categories"]
        ],
        "boundary": "自定义规则只影响候选，不自动改账；按优先级从高到低取第一条命中。",
    }


@router.post("/api/finance/attribution/rules")
async def attribution_rule_create(payload: dict[str, Any]) -> Any:
    body = payload or {}
    tenant, user = current_tenant_id(), current_user_id()
    existing = await attribution_db.list_rules(tenant, user)
    if len(existing) >= 20:
        return _bad("最多配置 20 条归因规则")
    try:
        fields = _rule_fields(body)
    except ValueError as exc:
        return _bad(str(exc))
    try:
        rule = await attribution_db.create_rule(
            tenant_id=tenant,
            user_id=user,
            name=fields["name"],
            keyword=fields["keyword"],
            category=fields["category"],
            direction=fields["direction"],
            priority=fields["priority"],
            merchant=fields["merchant"],
            min_amount_cents=fields["min_amount_cents"],
            max_amount_cents=fields["max_amount_cents"],
            member_id=fields["member_id"],
        )
    except Exception as exc:  # noqa: BLE001 — 唯一约束等数据库错误要变 400 而不是 500
        return _bad(f"规则保存失败：{str(exc)[:80]}")
    if not fields["enabled"]:
        rule = await attribution_db.update_rule(
            tenant, user, rule["rule_id"], enabled=False
        ) or rule
    return {"ok": True, "rule": rule}


@router.put("/api/finance/attribution/rules/{rule_id}")
async def attribution_rule_update(rule_id: str, payload: dict[str, Any]) -> Any:
    body = payload or {}
    tenant, user = current_tenant_id(), current_user_id()
    current = next(
        (r for r in await attribution_db.list_rules(tenant, user) if r["rule_id"] == rule_id),
        None,
    )
    if current is None:
        return _bad("规则不存在")
    try:
        fields = _rule_fields(body, current)
    except ValueError as exc:
        return _bad(str(exc))
    rule = await attribution_db.update_rule(
        tenant, user, rule_id,
        name=fields["name"], keyword=fields["keyword"], category=fields["category"],
        direction=fields["direction"], priority=fields["priority"],
        enabled=fields["enabled"], merchant=fields["merchant"],
        min_amount_cents=fields["min_amount_cents"],
        max_amount_cents=fields["max_amount_cents"],
        member_id=fields["member_id"] or 0,
    )
    if rule is None:
        return _bad("规则不存在")
    return {"ok": True, "rule": rule}


@router.delete("/api/finance/attribution/rules/{rule_id}")
async def attribution_rule_delete(rule_id: str) -> Any:
    ok = await attribution_db.delete_rule(current_tenant_id(), current_user_id(), rule_id)
    if not ok:
        return _bad("规则不存在")
    return {"ok": True, "rule_id": rule_id}


@router.post("/api/finance/attribution/rules/test")
async def attribution_rule_test(payload: dict[str, Any]) -> Any:
    body = payload or {}
    item = " ".join(str(body.get("item") or "").split()).strip()
    if not item:
        return _bad("请填写要测试的流水摘要")
    try:
        amount = float(body.get("amount") or 0)
    except (TypeError, ValueError):
        return _bad("金额必须是数字")
    direction = str(body.get("direction") or "").strip()
    if direction not in {"收入", "支出"}:
        direction = "收入" if amount > 0 else "支出"
    rules = await attribution_db.list_rules(
        current_tenant_id(), current_user_id(), enabled_only=True
    )
    raw_rule = body.get("rule")
    if isinstance(raw_rule, dict):
        try:
            fields = _rule_fields(raw_rule)
        except ValueError as exc:
            return _bad(str(exc))
        rules = [{
            "rule_id": "preview", "name": fields["name"], "keyword": fields["keyword"],
            "category": fields["category"], "direction": fields["direction"],
            "priority": fields["priority"], "merchant": fields["merchant"],
            "min_amount_cents": fields["min_amount_cents"],
            "max_amount_cents": fields["max_amount_cents"],
            "member_id": fields["member_id"], "enabled": 1, "created_at": "",
        }]
    out = suggest_attributions(
        [{"id": 1, "date": "", "item": item, "amount": amount, "category": "其他"}],
        {}, limit=1, custom_rules=rules,
    )
    row = (out.get("transactions") or [None])[0]
    candidate = row.get("candidate") if row else None
    matched = bool(candidate and candidate.get("source") == "custom_rule")
    return {
        "matched": matched,
        "candidate": candidate,
        "direction": direction,
        "rules_checked": len(rules),
    }


@router.get("/api/finance/attribution/confirmed")
async def attribution_confirmed(limit: int = 20) -> Any:
    rows = await attribution_db.list_confirmed_rows(
        current_tenant_id(), current_user_id(), limit=limit
    )
    return {"items": rows, "count": len(rows)}


@router.post("/api/finance/attribution/confirm-batch")
async def attribution_confirm_batch(payload: dict[str, Any]) -> Any:
    body = payload or {}
    raw_items = body.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return _bad("items 不能为空")
    if len(raw_items) > 100:
        return _bad("单次最多确认 100 条")
    tenant, user = current_tenant_id(), current_user_id()
    prepared: list[dict[str, Any]] = []
    seen: set[int] = set()
    for idx, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            return _bad(f"第 {idx + 1} 条格式错误")
        try:
            tx_id = int(raw.get("transaction_id") or 0)
            category = validate_category(raw.get("category"))
        except (TypeError, ValueError) as exc:
            return _bad(f"第 {idx + 1} 条：{exc}")
        if tx_id <= 0:
            return _bad(f"第 {idx + 1} 条：transaction_id 必须是正整数")
        if tx_id in seen:
            return _bad(f"第 {idx + 1} 条：流水 {tx_id} 重复")
        seen.add(tx_id)
        tx = await attribution_db.get_transaction(user, tx_id)
        if tx is None:
            return _bad(f"第 {idx + 1} 条：流水 {tx_id} 不存在")
        source = str(raw.get("source") or "manual")
        if source not in {"custom_rule", "rule", "history", "existing", "manual"}:
            source = "manual"
        try:
            confidence = max(0.0, min(float(raw.get("confidence") or 0), 1.0))
        except (TypeError, ValueError):
            confidence = 0.0
        matched = raw.get("matched")
        matched_list = [str(x)[:24] for x in matched][:5] if isinstance(matched, list) else []
        prepared.append({
            "transaction_id": tx_id,
            "original_category": str(tx.get("category") or ""),
            "confirmed_category": category,
            "source": source,
            "rule_id": str(raw.get("rule_id") or "")[:64],
            "confidence": confidence,
            "matched": matched_list,
        })
    try:
        written = await attribution_db.batch_apply_confirmations(
            tenant_id=tenant, user_id=user, items=prepared
        )
    except ValueError as exc:
        return _bad(str(exc))
    for item in written:
        await record_provenance(
            "attribution_confirm", "transaction", str(item["transaction_id"]),
            before={"category": item["previous_category"]},
            after={"category": item["category"]},
            source="api",
            metadata={
                "rule_id": item["rule_id"], "confidence": item["confidence"],
                "matched": item["matched"], "attribution_source": item["source"],
                "batch": True,
            },
        )
    return {"ok": True, "confirmed": len(written), "items": written}


@router.post("/api/finance/attribution/rollback")
async def attribution_rollback(payload: dict[str, Any]) -> Any:
    body = payload or {}
    try:
        tx_id = int(body.get("transaction_id") or 0)
    except (TypeError, ValueError):
        return _bad("transaction_id 必须是正整数")
    if tx_id <= 0:
        return _bad("transaction_id 必须是正整数")
    try:
        out = await attribution_db.rollback_confirmation(
            tenant_id=current_tenant_id(), user_id=current_user_id(), transaction_id=tx_id
        )
    except ValueError as exc:
        return _bad(str(exc))
    await record_provenance(
        "attribution_rollback", "transaction", str(tx_id),
        before={"category": out["reverted_category"]},
        after={"category": out["restored_category"]},
        source="api",
        metadata={
            "rule_id": out["rule_id"], "attribution_source": out["source"],
            "reverted_at": out["reverted_at"],
        },
    )
    return out


@router.get("/api/finance/attribution/stats")
async def attribution_stats() -> Any:
    tenant, user = current_tenant_id(), current_user_id()
    stats = await attribution_db.confirmation_stats(tenant, user)
    by_rule = [dict(r) for r in stats["by_rule"]]
    reverted = [dict(r) for r in stats["reverted_by_rule"]]
    by_source: dict[str, int] = {}
    for row in by_rule:
        by_source[str(row["source"])] = by_source.get(str(row["source"]), 0) + int(row["n"])
    return {
        "confirmed_total": sum(int(r["n"]) for r in by_rule),
        "reverted_total": sum(int(r["n"]) for r in reverted),
        "by_source": by_source,
        "by_rule": by_rule,
        "reverted_by_rule": reverted,
        "boundary": "统计来自真实确认记录与回滚记录，不推算未发生的采纳率。",
    }


@router.post("/api/finance/attribution/confirm")
async def attribution_confirm(payload: dict[str, Any]) -> Any:
    body = payload or {}
    try:
        tx_id = int(body.get("transaction_id") or 0)
        category = validate_category(body.get("category"))
    except (TypeError, ValueError) as exc:
        return _bad(str(exc))
    if tx_id <= 0:
        return _bad("transaction_id 必须是正整数")

    tx = await attribution_db.get_transaction(current_user_id(), tx_id)
    if tx is None:
        return _bad(f"流水 {tx_id} 不存在")

    source = str(body.get("source") or "manual")
    if source not in {"custom_rule", "rule", "history", "existing", "manual"}:
        source = "manual"
    try:
        confidence = max(0.0, min(float(body.get("confidence") or 0), 1.0))
    except (TypeError, ValueError):
        confidence = 0.0
    matched = body.get("matched")
    matched_list = [str(x)[:24] for x in matched][:5] if isinstance(matched, list) else []

    previous = str(tx.get("category") or "")
    await db.update_transaction(tx_id, category=category)
    confirmation = await attribution_db.upsert_confirmation(
        tenant_id=current_tenant_id(),
        user_id=current_user_id(),
        transaction_id=tx_id,
        original_category=previous,
        confirmed_category=category,
        source=source,
        rule_id=str(body.get("rule_id") or "")[:64],
        confidence=confidence,
        matched=matched_list,
    )
    await record_provenance(
        "attribution_confirm",
        "transaction",
        str(tx_id),
        before={"category": previous},
        after={"category": category},
        source="api",
        metadata={
            "rule_id": confirmation["rule_id"],
            "confidence": confirmation["confidence"],
            "matched": matched_list,
            "attribution_source": source,
        },
    )
    return {
        "ok": True,
        "transaction_id": tx_id,
        "previous_category": previous,
        "category": category,
        "confirmation": confirmation,
    }


# ---------------------------------------------------------------------------
# 自动化运行台账（4.17.0）：真实后台任务的可审计入口
# ---------------------------------------------------------------------------


@router.get("/api/automation/workflows")
async def automation_workflows() -> Any:
    return {"workflows": list_workflows()}


@router.get("/api/automation/runs")
async def automation_runs(limit: int = 20) -> Any:
    runs = await automation_db.list_runs(max(1, min(limit, 200)))
    return {"runs": runs, "count": len(runs)}


@router.post("/api/automation/workflows/{key}/run")
async def automation_run(key: str, payload: dict[str, Any] | None = None) -> Any:
    """手动补跑：与定时任务走同一条实现；同工作流串行。"""
    body = payload or {}
    idem = str(body.get("idempotency_key") or "").strip()[:120]
    try:
        return await run_workflow(key, trigger="manual", idempotency_key=idem)
    except ValueError as exc:
        return _bad(str(exc))


@router.get("/api/automation/alerts")
async def automation_alerts(limit: int = 20, unread_only: bool = False) -> Any:
    alerts = await automation_db.list_alerts(
        max(1, min(limit, 100)), unread_only=unread_only
    )
    return {"alerts": alerts, "unread": await automation_db.unread_alert_count()}


@router.post("/api/automation/alerts/{alert_id}/ack")
async def automation_alert_ack(alert_id: str) -> Any:
    alert = await automation_db.acknowledge_alert(alert_id)
    if alert is None:
        return _bad("告警不存在")
    return {"ok": True, "alert": alert}


@router.post("/api/automation/runs/{run_id}/replay")
async def automation_run_replay(run_id: str) -> Any:
    """人工重放失败/部分失败运行；原运行证据保留，新运行单独记账。"""
    try:
        return await replay_run(run_id)
    except ValueError as exc:
        return _bad(str(exc))


__all__ = ["router"]

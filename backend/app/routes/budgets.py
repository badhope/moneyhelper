"""预算路由：查询 + 更新月度预算设置。"""

from __future__ import annotations

import re

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import analysis, db
from ..provenance import record_provenance

router = APIRouter()


def _current_month() -> str:
    from datetime import datetime
    return datetime.now().astimezone().strftime("%Y-%m")


@router.get("/api/budgets")
async def get_budgets(month: str | None = None) -> dict:
    """返回指定月（默认本月）的预算设置 + 实时使用情况。"""
    m = (month or "").strip() or _current_month()
    if not re.fullmatch(r"(20\d{2}|19\d{2})-(0[1-9]|1[0-2])", m):
        return JSONResponse({"error": "月份需为 YYYY-MM（01–12）"}, status_code=400)
    rows = await db.list_budgets(m)
    budgets = [
        {
            "category": "总预算" if r["category"] == "__total" else r["category"],
            "key": r["category"],
            "amount": r["amount"],
        }
        for r in rows
    ]
    analysis.invalidate_dashboard_cache()
    return {
        "month": m,
        "budgets": budgets,
        "usage": await db.budget_usage(m),
    }


@router.put("/api/budgets")
async def put_budgets(payload: dict) -> dict:
    month = (payload or {}).get("month") or _current_month()
    if not re.fullmatch(r"(20\d{2}|19\d{2})-(0[1-9]|1[0-2])", month):
        return JSONResponse({"error": "月份需为 YYYY-MM（01–12）"}, status_code=400)
    items = (payload or {}).get("budgets")
    if not isinstance(items, list):
        return JSONResponse({"error": "budgets 需为数组"}, status_code=400)
    clean_map: dict[str, float] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            amt = float(it.get("amount", 0) or 0)
        except (TypeError, ValueError):
            return JSONResponse({"error": "预算金额不合法"}, status_code=400)
        if amt > 0:
            # 同分类后一项覆盖前一项（upsert 语义），避免主键冲突
            clean_map[str(it.get("category", "__total"))] = amt
    clean = [{"category": k, "amount": v} for k, v in clean_map.items()]
    # 操作前快照：已有预算
    before = {r["category"]: r["amount"] for r in await db.list_budgets(month)}
    await db.save_budgets(month, clean)
    # 异步记录审计（不阻塞主业务）
    after = {r["category"]: r["amount"] for r in await db.list_budgets(month)}
    await record_provenance(
        action="save_budgets",
        entity_type="budget",
        entity_id=month,
        before=before,
        after=after,
        source="api",
    )
    analysis.invalidate_dashboard_cache()
    return {"ok": True, "month": month, "count": len(clean)}


@router.post("/api/budgets/suggest")
async def suggest_budgets() -> dict:
    """AI 按近两月实际支出给月度预算建议（只产出建议不落库；未接模型时友好报错）。"""
    from datetime import datetime, timedelta

    from .. import llm

    if not await llm.llm_available():
        return {"ok": False, "error": "未接入模型 —— 先到「设置 → AI 回答」配置模型端点"}

    # 近 60 天支出按类别聚合（只统计支出：amount < 0）
    txns = await db.list_transactions()
    cutoff = (datetime.now().astimezone().date() - timedelta(days=60)).isoformat()
    by_cat: dict[str, float] = {}
    total = 0.0
    for t in txns:
        d = str(t.get("date") or "")
        amt = float(t.get("amount") or 0)
        if d >= cutoff and amt < 0:
            cat = str(t.get("category") or "其他")
            by_cat[cat] = by_cat.get(cat, 0.0) + abs(amt)
            total += abs(amt)
    if total <= 0:
        return {"ok": False, "error": "近两个月没有支出记录，先记几笔再来"}

    summary = (
        "近约两个月（60 天）实际支出分类汇总（元）："
        + "，".join(f"{k} {round(v)}" for k, v in sorted(by_cat.items(), key=lambda x: -x[1])[:15])
        + f"。总支出 {round(total)} 元。"
    )
    system = (
        "你是理财预算顾问。根据用户近两月支出明细，给出下个月预算建议。只输出 JSON："
        '{"total": 整数, "categories": {"分类名": 整数}}。'
        "规则：分类名沿用输入中的中文名；金额取整；建议值贴近实际并留一点余量；分类不超过 8 个。"
    )
    out = await llm.json_complete(system, summary, timeout=25.0)
    if not isinstance(out, dict):
        return {"ok": False, "error": "生成失败，请稍后重试"}
    try:
        total_v = int(float(out.get("total") or 0))
        cats = {
            str(k)[:12]: int(float(v))
            for k, v in (out.get("categories") or {}).items()
            if float(v or 0) > 0
        }
    except (TypeError, ValueError):
        return {"ok": False, "error": "生成结果不可用，请重试"}
    if total_v <= 0 or not cats:
        return {"ok": False, "error": "生成结果不可用，请重试"}
    analysis.invalidate_dashboard_cache()
    return {
        "ok": True,
        "suggestion": {"total": total_v, "categories": cats},
        "based_on": {"days": 60, "spent": round(total)},
    }


@router.post("/api/rules/suggest")
async def suggest_rules() -> dict:
    """AI 按交易历史给账本假设建议（月收入/应急月数/必选类别/储蓄比例）。只出建议不落库。"""
    from datetime import datetime, timedelta

    from .. import llm

    if not await llm.llm_available():
        return {"ok": False, "error": "未接入模型 —— 先到「设置 → AI 回答」配置模型端点"}

    txns = await db.list_transactions()
    cutoff = (datetime.now().astimezone().date() - timedelta(days=60)).isoformat()
    income = 0.0
    essential: dict[str, float] = {}
    for t in txns:
        if str(t.get("date") or "") < cutoff:
            continue
        amt = float(t.get("amount") or 0)
        if amt > 0:
            income += amt
        else:
            cat = str(t.get("category") or "其他")
            essential[cat] = essential.get(cat, 0.0) + abs(amt)
    if income <= 0 and not essential:
        return {"ok": False, "error": "近两个月没有收支记录，先记几笔再来"}

    summary = (
        f"近约两个月（60 天）收入合计 {round(income)} 元；支出分类："
        + "，".join(f"{k} {round(v)}" for k, v in sorted(essential.items(), key=lambda x: -x[1])[:12])
        + "。"
    )
    system = (
        "你是理财规划顾问。根据用户近两月收支，给出账本假设建议。只输出 JSON："
        '{"monthly_income": 整数（月均收入）, "emergency_target_months": 3-12 整数, '
        '"essential_categories": "逗号分隔的必选支出类别（从给定类别中选）", "savings_goal": 5-50 整数（储蓄率%）}。'
    )
    out = await llm.json_complete(system, summary, timeout=25.0)
    if not isinstance(out, dict):
        return {"ok": False, "error": "生成失败，请稍后重试"}
    try:
        mi = int(float(out.get("monthly_income") or 0))
        em = int(float(out.get("emergency_target_months") or 6))
        sg = int(float(out.get("savings_goal") or 20))
        cats = str(out.get("essential_categories") or "").strip()[:120]
    except (TypeError, ValueError):
        return {"ok": False, "error": "生成结果不可用，请重试"}
    if mi <= 0 or not cats:
        return {"ok": False, "error": "生成结果不可用，请重试"}
    # 夹到合理区间，防止模型给出离谱值直接写进设置
    em = min(max(em, 3), 12)
    sg = min(max(sg, 5), 50)
    analysis.invalidate_dashboard_cache()
    return {
        "ok": True,
        "suggestion": {
            "monthly_income": mi,
            "emergency_target_months": em,
            "essential_categories": cats,
            "savings_goal": sg,
        },
        "based_on": {"days": 60, "income": round(income)},
    }


@router.post("/api/reports/suggest-focus")
async def suggest_report_focus() -> dict:
    """AI 按当前持仓/账本给出晨报应重点关注的 3 条（只出建议不落库）。"""
    from .. import llm

    if not await llm.llm_available():
        return {"ok": False, "error": "未接入模型 —— 先到「设置 → AI 回答」配置模型端点"}

    positions = await db.list_positions()
    txns = await db.list_transactions()
    if not positions and not txns:
        return {"ok": False, "error": "还没有持仓和流水，先记几笔再来"}

    top = sorted(positions, key=lambda p: -(float(p.get("shares", 0)) * float(p.get("last", 0))))[:5]
    pos_desc = "，".join(
        f"{p.get('name')}({p.get('kind')}) 市值{round(float(p.get('shares', 0)) * float(p.get('last', 0)))}"
        for p in top
    )
    recent = txns[:10]
    tx_desc = "，".join(f"{t.get('category')} {round(abs(float(t.get('amount') or 0)))}" for t in recent)
    summary = f"当前主要持仓：{pos_desc or '无'}。最近流水：{tx_desc or '无'}。"
    system = (
        "你是理财晨报编辑。根据用户持仓与最近流水，给出这份晨报应重点关注的要点。"
        '只输出 JSON：{"focus": "一句话（60 字以内），指明最该盯的 1-3 个点"}。'
    )
    out = await llm.json_complete(system, summary, timeout=20.0)
    if not isinstance(out, dict):
        return {"ok": False, "error": "生成失败，请稍后重试"}
    focus = str(out.get("focus") or "").strip()[:160]
    if not focus:
        return {"ok": False, "error": "生成结果不可用，请重试"}
    analysis.invalidate_dashboard_cache()
    return {"ok": True, "suggestion": {"focus": focus}}

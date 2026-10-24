"""数据录入域路由：仪表盘 / 持仓 / 流水 / 一句话记账 / CSV 入账 / 撤回 / 体检。

从 main.py 拆出（M1.4）。鉴权由 main.py 的 api_auth 中间件统一覆盖。
注意：/api/import/csv 的"新版解析"由 routes/import_routes.py 先注册提供，
本模块的同名路由为旧版通用解析（当前被遮蔽，保持注册以兼容历史行为）。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import analysis, auth, db, evaluate, quotes
from ..quotes import invalidate_quotes_cache

router = APIRouter()


@router.get("/api/dashboard")
async def dashboard(lang: str = "zh") -> dict:
    # lang 仅影响 flags/来源标签等展示文案的语言，不增加任何查询/往返开销
    return await analysis.collect_dashboard(lang=lang or "zh")


# ---------------------------------------------------------------------------
# 数据录入（持仓 / 流水 / 负债）
# ---------------------------------------------------------------------------


@router.post("/api/positions")
async def create_position(payload: dict) -> dict:
    try:
        out = await db.add_position(payload or {})
    except Exception as exc:  # noqa: BLE001 — 坏输入回 400
        return JSONResponse({"error": str(exc)}, status_code=400)
    await invalidate_quotes_cache()
    analysis.invalidate_dashboard_cache()
    return out


@router.delete("/api/positions/{symbol}")
async def remove_position(symbol: str) -> dict:
    out = await db.delete_position(symbol)
    await invalidate_quotes_cache()
    analysis.invalidate_dashboard_cache()
    return out


@router.put("/api/positions/{symbol}")
async def update_position(symbol: str, payload: dict) -> dict:
    try:
        out = await db.update_position(payload or {}, symbol)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)
    await invalidate_quotes_cache()
    analysis.invalidate_dashboard_cache()
    return out


@router.post("/api/positions/merge")
async def merge_positions(payload: dict) -> dict:
    name = str((payload or {}).get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name 必填：要合并的持仓名称"}, status_code=400)
    try:
        out = await db.merge_positions_by_name(name)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)
    await invalidate_quotes_cache()
    analysis.invalidate_dashboard_cache()
    return out


@router.post("/api/transactions")
async def create_transaction(payload: dict) -> dict:
    date = str(payload.get("date") or "").strip()
    item = str(payload.get("item") or "").strip()
    category = str(payload.get("category") or "其他").strip() or "其他"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return JSONResponse({"error": "日期需为 YYYY-MM-DD 格式"}, status_code=400)
    if not item:
        return JSONResponse({"error": "名称必填"}, status_code=400)
    try:
        amount = float(payload.get("amount", 0) or 0)
    except (TypeError, ValueError):
        return JSONResponse({"error": "金额不合法"}, status_code=400)
    if amount == 0:
        return JSONResponse({"error": "金额不能为 0"}, status_code=400)
    # owner_id 显式传入 or 自动取活跃成员
    owner_id = payload.get("owner_id")
    if owner_id is not None:
        try:
            owner_id = int(owner_id)
        except (TypeError, ValueError):
            return JSONResponse({"error": "owner_id 必须为整数"}, status_code=400)
    is_shared = payload.get("is_shared")
    try:
        return await db.add_transaction(
            date,
            item,
            category,
            amount,
            owner_id=owner_id,
            is_shared=is_shared,
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.get("/api/transactions")
async def get_transactions(member_id: int | None = None) -> dict:
    """查询交易流水。member_id 有值时按家庭可见性过滤（shared=1 OR owner=自己）。"""
    rows = await db.list_transactions(member_id=member_id)
    return {"transactions": rows, "count": len(rows)}


@router.delete("/api/transactions/{tx_id}")
async def remove_transaction(tx_id: int) -> dict:
    return await db.delete_transaction(tx_id)


@router.put("/api/transactions/{tx_id}")
async def update_transaction(tx_id: int, payload: dict) -> dict:
    p = payload or {}
    owner_id = p.get("owner_id")
    if owner_id is not None:
        try:
            owner_id = int(owner_id)
        except (TypeError, ValueError):
            return JSONResponse({"error": "owner_id 必须为整数"}, status_code=400)
    is_shared = p.get("is_shared")
    try:
        return await db.update_transaction(
            tx_id,
            date=p.get("date"),
            item=p.get("item"),
            category=p.get("category"),
            amount=p.get("amount"),
            owner_id=owner_id,
            is_shared=is_shared,
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.post("/api/transactions/merge")
async def merge_transactions(payload: dict) -> dict:
    p = payload or {}
    month = str(p.get("month") or "").strip()
    if not month:
        return JSONResponse({"error": "month 必填，格式 YYYY-MM"}, status_code=400)
    try:
        out = await db.merge_transactions(month, p.get("category"))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)
    await invalidate_quotes_cache()
    analysis.invalidate_dashboard_cache()
    return out


@router.post("/api/positions/{symbol}/append")
async def append_position(symbol: str, payload: dict) -> dict:
    """追加持仓：已有 symbol 则股数累加、成本加权平均（不覆盖），用于「合并」语义。"""
    from .. import tools as _tools

    p = payload or {}
    async with _tools._position_write_lock:
        rows = await db.list_positions()
        cur = next((r for r in rows if r["symbol"] == symbol), None)
        if cur is None:
            return JSONResponse(
                {"error": f"持仓 {symbol} 不存在，请先添加"}, status_code=404
            )
        add_shares = float(p.get("shares") or 0)
        add_cost = float(p.get("cost") or 0)
        if add_shares <= 0:
            return JSONResponse({"error": "追加股数需大于 0"}, status_code=400)
        old_shares = cur["shares"]
        old_cost = cur["cost"]
        total = old_shares + add_shares
        avg_cost = (
            (old_shares * old_cost + add_shares * add_cost) / total
            if total > 0
            else old_cost
        )
        out = await db.update_position(
            {
                **cur,
                "shares": total,
                "cost": round(avg_cost, 6),
                "last": float(p.get("last", cur["last"])),
            },
            symbol,
        )
        await invalidate_quotes_cache()
        analysis.invalidate_dashboard_cache()
        return {**out, "appended": True, "new_shares": total}


@router.post("/api/nl-add")
async def nl_add(payload: dict) -> dict:
    """一句话记账：规则解析优先（秒回），规则拿不到金额时升级 AI，AI 也失败则 422 提示。"""
    from .. import nlparse

    text = str((payload or {}).get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "请输入一句话记账内容"}, status_code=400)

    parsed = nlparse.parse(text)
    source = "rule"
    if parsed is None:
        # 规则拿不到金额 → AI 兜底
        parsed = await nlparse.parse_with_ai(text)
        source = "ai" if parsed else None
    elif parsed["category"] == "其他" and parsed["amount"] < 0:
        # 规则拿到金额但分类不明确（非收入）→ AI 补分类，失败仍用规则结果入账
        ai = await nlparse.parse_with_ai(text)
        if ai is not None:
            parsed, source = ai, "ai"
    if parsed is None:
        return JSONResponse(
            {
                "error": "没读懂这句话，试试「昨天打车 32 元」「工资 8000 已到账」这样的说法"
            },
            status_code=422,
        )
    try:
        ins = await db.add_transaction(
            parsed["date"], parsed["item"], parsed["category"], parsed["amount"]
        )
        rows = await db.fetch_all("SELECT * FROM transactions WHERE id=?", (ins["id"],))
        tx = rows[0] if rows else {"id": ins["id"], **parsed}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)
    analysis.invalidate_dashboard_cache()
    return {"ok": True, "source": source, "transaction": tx}


# ---------------------------------------------------------------------------
# 账单导入（CSV）：通用预览 + 确认入账
# ---------------------------------------------------------------------------


@router.post("/api/import/generic")
async def import_csv_parse(payload: dict) -> dict:
    """解析通用 CSV → 识别列映射 + 预览（前 15 条）+ 可导入条数统计。

    历史说明：该实现原挂在 /api/import/csv，后被 routes/import_routes.py 的
    源感知解析（微信/支付宝/银行）以同名路径先注册遮蔽，导致通用导入实际不可用。
    M1.4 收尾时迁移到显式路径 /api/import/generic（前端 EntryView 调用）。
    """
    from .. import csvimport

    content = str((payload or {}).get("content") or "").strip()
    if not content:
        return JSONResponse({"error": "请粘贴账单 CSV 内容"}, status_code=400)
    try:
        parsed = csvimport.parse_csv(content)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    mapping = csvimport.detect_mapping(parsed["columns"])
    if mapping["amount"] < 0 or mapping["date"] < 0:
        return JSONResponse(
            {"error": "没能识别出日期/金额列，请确认表头包含「日期」「金额」等关键词"},
            status_code=422,
        )
    year = datetime.now().astimezone().strftime("%Y-%m")
    rows, skips = csvimport.build_rows(
        mapping, parsed["columns"], parsed["rows"], year_fill=year
    )
    return {
        "ok": True,
        "columns": parsed["columns"],
        "mapping": mapping,
        "preview": rows[:15],
        "rows": rows,
        "total": len(rows),
        "skipped": len(skips),
    }


@router.post("/api/import/commit")
async def import_csv_commit(payload: dict) -> dict:
    """按前端确认的 rows 批量入账；先全部校验通过再逐个入账。"""
    rows = (payload or {}).get("rows")
    if not isinstance(rows, list) or not rows:
        return JSONResponse({"error": "没有可导入的数据"}, status_code=400)
    ok, failed = 0, []
    for r in rows:
        if not isinstance(r, dict):
            failed.append("非法行")
            continue
        date = str(r.get("date") or "").strip()
        item = str(r.get("item") or "其他").strip()[:40] or "其他"
        category = str(r.get("category") or "其他").strip() or "其他"
        try:
            amount = float(r.get("amount", 0) or 0)
        except (TypeError, ValueError):
            failed.append(item)
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or amount == 0:
            failed.append(item)
            continue
        try:
            await db.add_transaction(date, item, category, amount)
            ok += 1
        except Exception as e:  # noqa: BLE001
            # 检测事务 closed 错误（前一行失败导致 connection state 异常）→ 连接级回滚
            if (
                "cannot operate on a closed database" in str(e).lower()
                or "no active transaction" in str(e).lower()
            ):
                # 单个失败不应影响后续行；记录并继续
                failed.append(f"{item}(事务中断)")
                continue
            failed.append(item)
    return {"ok": True, "imported": ok, "failed": failed}


# ---------------------------------------------------------------------------
# 预算体检（确定性规则引擎）
# ---------------------------------------------------------------------------


@router.get("/api/evaluate")
async def get_evaluate(month: str | None = None) -> dict:
    """运行确定性规则引擎，返回行动项列表（按优先级排序）。

    可选 ?month=YYYY-MM，默认本月。结果为纯本地计算，不调用 LLM。
    """
    m = (month or "").strip()
    if m and not re.fullmatch(r"(20\d{2}|19\d{2})-(0[1-9]|1[0-2])", m):
        return JSONResponse({"error": "月份需为 YYYY-MM（01–12）"}, status_code=400)
    return await evaluate.evaluate_all(month=m)


# ---------------------------------------------------------------------------
# 撤回（undo）：单条 / 批量 / 面板
# ---------------------------------------------------------------------------


async def _resolve_usable_snapshot(entity: str, entity_id: str):
    """查最近一条 active（未被撤回）快照；没有 raises LookupError。主流程按实体类型传入对应主键值。"""
    rows = await db.list_undo_records(entity=entity, entity_id=str(entity_id), limit=1)
    if not rows:
        raise LookupError(f"no active undo snapshot for {entity}/{entity_id}")
    return rows[0]


VALID_BATCH_UNDO_ENTITIES = ("transactions", "positions", "debts", "subscriptions")
ENTITY_TO_KIND = {
    "transactions": ("transaction",),
    "positions": ("position",),
    "debts": ("debt",),
    "subscriptions": ("subscription",),
}


@router.post("/api/transactions/{tx_id}/undo")
async def undo_transaction(tx_id: int) -> dict:
    try:
        snap = await _resolve_usable_snapshot("transaction", str(tx_id))
    except LookupError:
        return JSONResponse({"error": f"流水 {tx_id} 无可撤回快照"}, status_code=404)
    res = await db._undo_apply(snap["id"])
    return {"ok": True, **res}


@router.post("/api/positions/{symbol}/undo")
async def undo_position(symbol: str) -> dict:
    try:
        snap = await _resolve_usable_snapshot("position", symbol)
    except LookupError:
        return JSONResponse({"error": f"持仓 {symbol} 无可撤回快照"}, status_code=404)
    res = await db._undo_apply(snap["id"])
    return {"ok": True, **res}


@router.post("/api/{entity:path}/batch-undo")
async def batch_undo(entity: str, payload: dict) -> dict:
    entity = (entity or "").strip().lower()
    if entity not in VALID_BATCH_UNDO_ENTITIES:
        return JSONResponse(
            {"error": f"不支持撤回的实体：{entity}，可选：{VALID_BATCH_UNDO_ENTITIES}"},
            status_code=400,
        )
    kind = ENTITY_TO_KIND[entity][0]
    ids = (payload or {}).get("ids")
    if not isinstance(ids, list) or not ids:
        return JSONResponse({"error": "body.ids 需为非空列表"}, status_code=400)

    # 第一步：先全部校验快照可用性（避免部分成功部分失败）
    snapshots: list[tuple[str, int]] = []  # (sid, undo_record_id)
    not_found: list[str] = []
    for raw_id in ids:
        sid = str(raw_id)
        try:
            snap = await _resolve_usable_snapshot(kind, sid)
            snapshots.append((sid, snap["id"]))
        except LookupError:
            not_found.append(sid)

    # 任一快照不可用 → 全不撤回（保持原子语义）
    if not_found:
        return JSONResponse(
            {"error": "部分快照不存在或已被撤回", "not_found": not_found},
            status_code=404,
        )

    # 第二步：逐个执行（所有快照已确认可用）
    results: list[dict] = []
    for sid, undo_id in snapshots:
        res = await db._undo_apply(undo_id)
        results.append({"id": sid, "ok": True, "consumed_at": res["consumed_at"]})
    return {
        "ok": True,
        "succeeded": results,
        "not_found": [],
        "attempted": len(ids),
    }


@router.get("/api/undoables")
async def undoables(limit: int = 8) -> dict:
    """最近 N 条可撤回快照（CommandPalette 撤销面板用）。
    返回格式对齐 {entity, entity_id, snapshot_label, created_at}，便于前端直接渲染。"""
    rows = await db.list_undo_records(
        limit=max(1, min(int(limit), 20)), include_consumed=False
    )
    items: list[dict[str, Any]] = []
    for r in rows:
        label = _undo_snapshot_label(r)
        items.append(
            {
                "id": r["id"],
                "entity": r["entity"],
                "entity_id": r["entity_id"],
                "label": label,
                "created_at": r["created_at"],
            }
        )
    return {"items": items}


@router.post("/api/undo/{record_id}")
async def undo_by_id(record_id: int) -> dict:
    """通用撤销端点：按 undo_records.id 直接撤回（前端撤销列表首选，无需关心实体类型）。"""
    try:
        res = await db._undo_apply(int(record_id))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return {"ok": True, **res}


def _undo_snapshot_label(r: dict[str, Any]) -> str:
    """把 undo_records 一行翻译为人类可读的一行描述（用于 CommandPalette 展示）。"""
    entity = r["entity"]
    eid = r["entity_id"]
    reason = (r.get("reason") or "").strip()
    before = (r.get("before_json") or "").strip()
    verb = "删除" if before in ("", "{}") else "修改"
    name_map = {
        "transaction": "流水",
        "position": "持仓",
        "debt": "负债",
        "subscription": "订阅",
        "goal": "目标",
    }
    base = f"{name_map.get(entity, entity)} {verb}（{eid}）"
    return f"{base} · {reason}" if reason else base


# ---------------------------------------------------------------------------
# 财务体检（health check）/ 持仓重置
# ---------------------------------------------------------------------------


@router.get("/api/health-check")
async def health_check(lang: str = "zh") -> dict:
    lang = lang.strip() or "zh"
    positions = await db.list_positions()
    # 空库保护与图内一致：没有任何持仓/流水时不给「分数体检」假象
    if not positions and not await db.fetch_all("SELECT 1 FROM transactions LIMIT 1"):
        return analysis.health_check(None, None, [], await db.list_goals(), lang=lang)
    live = await quotes.live_quotes(positions)
    settings = await db.get_settings()
    m = analysis.market_view(positions, live)
    led = analysis.ledger_view(
        await db.list_transactions(),
        await db.list_subscriptions(),
        await db.list_debts(),
        settings,
        positions,
        live,
    )
    flags = analysis.risk_checks(m, led)
    return analysis.health_check(m, led, flags, await db.list_goals(), lang=lang)


@router.post("/api/portfolio/reset")
async def reset_portfolio(request: Request) -> dict:
    """恢复示例数据（**只影响当前租户的账本**）。

    鉴权要求（专家评审 P0-5）：这是清空账本的操作。
    - 启用多用户（已有注册用户）时：必须登录，且只清自己的数据；
    - 单机模式（没有任何用户）时：允许，仍只清默认租户 0。
    此前无任何校验，任何能访问端口的人都能抹掉全部数据。
    """
    if await db.user_count() > 0:
        user = await auth.get_current_user(request)
        if not user:
            return JSONResponse({"error": "需要登录"}, status_code=401)
    out = await db.reset_to_seed()
    await invalidate_quotes_cache()
    analysis.invalidate_dashboard_cache()
    return out

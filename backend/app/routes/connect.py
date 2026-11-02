"""连接中心路由：目录 / 连接 CRUD / 配对 / 同步 / 收件箱 / 行情 / 交易意图。

鉴权：与主 API 同一套中间件（登录 JWT 或共享口令）。
所有端点都允许降级：外部数据源失败返回 items=[] + note，不返回 5xx。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from ..auth import get_current_user
from ..connect import marketdata, service, store
from ..connect.catalog import get_connector, grouped_catalog

router = APIRouter(dependencies=[Depends(get_current_user)])


def _bad(msg: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=code)


# ---------------------------------------------------------------------------
# 目录
# ---------------------------------------------------------------------------


@router.get("/api/connect/catalog")
async def connect_catalog() -> dict[str, Any]:
    """连接器目录（按分类分组）+ 当前已建立的连接 + 自动化统计。"""
    connections = await store.list_connections()
    by_connector: dict[str, list[dict[str, Any]]] = {}
    for c in connections:
        by_connector.setdefault(c["connector_id"], []).append(c)
    catalog = grouped_catalog()
    for group in catalog["groups"]:
        for item in group["items"]:
            item["connections"] = by_connector.get(item["id"], [])
    return {**catalog, "connections": connections, "kinds_label": _kind_labels()}


def _kind_labels() -> dict[str, str]:
    return {
        "public_api": "公开接口 · 后台自动拉取",
        "deep_link": "官方入口 · 一键跳转登录",
        "browser_login": "浏览器代登录 · 配对码回传",
        "file_import": "文件导入 · 收件目录自动入账",
    }


@router.get("/api/connect/sources/status")
async def connect_sources_status() -> dict[str, Any]:
    """公开数据源连通性探测（东财行情 / 天天基金 / 涨跌榜）。"""
    return await marketdata.source_status()


# ---------------------------------------------------------------------------
# 连接 CRUD
# ---------------------------------------------------------------------------


@router.post("/api/connect/connections")
async def create_connection(payload: dict[str, Any]) -> Any:
    try:
        return await store.create_connection(
            str((payload or {}).get("connector_id") or ""),
            str((payload or {}).get("label") or ""),
            str((payload or {}).get("account_ref") or ""),
            payload.get("meta") if isinstance(payload.get("meta"), dict) else None,
        )
    except ValueError as exc:
        return _bad(str(exc))


@router.patch("/api/connect/connections/{cid}")
async def patch_connection(cid: str, payload: dict[str, Any]) -> Any:
    try:
        return await store.update_connection(cid, payload or {})
    except ValueError as exc:
        return _bad(str(exc), 404 if "不存在" in str(exc) else 400)


@router.delete("/api/connect/connections/{cid}")
async def remove_connection(cid: str) -> dict[str, Any]:
    ok = await store.delete_connection(cid)
    if not ok:
        raise HTTPException(404, "连接不存在")
    return {"deleted": cid}


@router.post("/api/connect/connections/{cid}/sync")
async def sync_one(cid: str, payload: dict[str, Any] | None = None) -> Any:
    try:
        return await service.sync_connection(cid, lang=str((payload or {}).get("lang") or "zh"))
    except ValueError as exc:
        return _bad(str(exc), 404)


@router.post("/api/connect/sync-all")
async def sync_all() -> dict[str, Any]:
    """一键同步全部已启用连接（公开源直连、登录类返回配对码）。"""
    results = []
    for c in await store.list_connections():
        if c["status"] == "disabled":
            continue
        try:
            results.append(await service.sync_connection(c["id"]))
        except Exception as exc:  # noqa: BLE001 — 单条失败不影响其余
            results.append({"id": c["id"], "status": "failed", "message": str(exc)})
    return {"items": results, "count": len(results)}


# ---------------------------------------------------------------------------
# 配对码（浏览器代登录 / 书签脚本）
# ---------------------------------------------------------------------------


@router.post("/api/connect/pairing")
async def issue_pairing(payload: dict[str, Any]) -> Any:
    try:
        return await store.issue_pairing_code(str((payload or {}).get("connector_id") or ""))
    except ValueError as exc:
        return _bad(str(exc))


@router.get("/api/connect/pairing/{cid}/bookmarklet")
async def pairing_bookmarklet(cid: str, lang: str = "zh") -> Any:
    """为该连接器生成书签脚本（含新配对码），用户拖到书签栏即可一键回传。"""
    try:
        pairing = await store.issue_pairing_code(cid)
    except ValueError as exc:
        return _bad(str(exc), 404)
    from ..compat_env import getenv

    base = getenv("MONEYHELPER_PUBLIC_URL").strip() or "http://127.0.0.1:8788"
    return {
        "pairing": pairing,
        "bookmarklet": service.build_bookmarklet(base, pairing["code"], cid, lang),
        "ingest_endpoint": f"{base.rstrip('/')}/api/connect/ingest",
        "how_to": "把 bookmarklet 拖到浏览器书签栏 → 打开官方页面并登录 → 点该书签 → 页面数据自动回传",
    }


@router.post("/api/connect/ingest")
async def ingest_page(payload: dict[str, Any]) -> Any:
    """书签脚本回传入口：校验配对码 → 解析页面文本里的账单行 → 入账。

    只接受文本；不保存原始页面快照（避免把用户隐私页面整页留库）。
    """
    code = str((payload or {}).get("code") or "").strip()
    connector_id = str((payload or {}).get("connector_id") or "").strip()
    text = str((payload or {}).get("text") or "")
    title = str((payload or {}).get("title") or "")[:120]
    if not code:
        return _bad("缺少配对码")
    if not text.strip():
        return _bad("页面没有可解析的文本")
    try:
        redeemed = await store.redeem_pairing_code(code, connector_id)
    except ValueError as exc:
        return _bad(str(exc), 403)

    # 免登录通道：租户由配对码决定（配对码只能写、不能读，且用后即焚）
    from ..db.tenant import reset_current_user_id, set_current_user_id

    tenant_token = set_current_user_id(int(redeemed.get("user_id") or 0))
    try:
        return await _ingest_rows(text, title, connector_id)
    finally:
        reset_current_user_id(tenant_token)


async def _ingest_rows(text: str, title: str, connector_id: str) -> Any:
    # 页面文本里通常夹着导航/页脚：只保留看起来像账单的行，交给通用 CSV 解析器会失败，
    # 因此这里按「日期 + 金额」的宽松规则抽取。
    rows = _extract_rows(text)
    if not rows:
        return {
            "ok": True,
            "imported": 0,
            "message": f"已收到页面「{title}」，但没有识别到账单行；可改用官方导出 CSV 导入",
        }
    from .. import db
    from ..provenance import record_provenance

    existing = {(r["date"], round(float(r["amount"]), 2), r["item"]) for r in await db.list_transactions()}
    imported = 0
    for r in rows:
        key = (r["date"], round(r["amount"], 2), r["item"])
        if key in existing:
            continue
        await db.add_transaction(r["date"], r["item"][:40], r["category"], r["amount"])
        existing.add(key)
        imported += 1
    if imported:
        await record_provenance(
            action="connect_ingest_page",
            entity_type="transaction",
            entity_id=f"batch:{imported}",
            before=None,
            after={"imported": imported, "connector_id": connector_id, "title": title},
            source="connect",
        )
    return {"ok": True, "imported": imported, "title": title, "message": f"已从页面入账 {imported} 笔"}


def _extract_rows(text: str) -> list[dict[str, Any]]:
    """从任意页面文本抽取账单行：日期 + 描述 + 金额（±）。"""
    import re

    date_re = re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})")
    # 千分位分组必须是「至少一组逗号」，否则 12000.00 会被截成 120 —— 旧写法实测漏了整行
    amount_re = re.compile(
        r"([+-]?)\s*[¥￥]?\s*(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
    )
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        raw = line.strip()
        if not raw or len(raw) < 8 or len(raw) > 300:
            continue
        m = date_re.search(raw)
        if not m:
            continue
        amounts = amount_re.findall(raw[m.end():])
        if not amounts:
            continue
        sign, num = amounts[-1]
        try:
            value = float(num.replace(",", ""))
        except ValueError:
            continue
        if value <= 0:
            continue
        # 描述 = 日期之后的片段，去掉金额与常见状态词
        desc = raw[m.end():]
        desc = amount_re.sub(" ", desc)
        desc = re.sub(r"\s+", " ", desc).strip(" ,，|") or "页面回传"
        from ..csvimport import classify as auto_classify

        out.append(
            {
                "date": f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}",
                "item": desc[:80],
                "amount": -value if sign != "+" else value,
                "category": auto_classify(desc) or "其他",
            }
        )
        if len(out) >= 500:
            break
    return out


# ---------------------------------------------------------------------------
# 收件箱
# ---------------------------------------------------------------------------


@router.post("/api/connect/inbox/scan")
async def inbox_scan() -> dict[str, Any]:
    """扫描账单收件目录并自动入账（用户只需把官方导出的 CSV 放进去）。"""
    return await service.scan_import_inbox()


@router.get("/api/connect/inbox")
async def inbox_info() -> dict[str, Any]:
    root = service.inbox_dir()
    files = [
        {"name": p.name, "size": p.stat().st_size, "mtime": p.stat().st_mtime}
        for p in sorted(root.iterdir())
        if p.is_file()
    ]
    done = root / "done"
    done_files = sorted([p.name for p in done.iterdir() if p.is_file()])[-20:] if done.exists() else []
    return {"path": str(root), "pending": files, "done": done_files}


# ---------------------------------------------------------------------------
# 公开行情
# ---------------------------------------------------------------------------


@router.get("/api/connect/fund/nav")
async def fund_nav(codes: str = "") -> dict[str, Any]:
    return await marketdata.fund_nav([c for c in codes.replace("，", ",").split(",") if c.strip()])


@router.get("/api/connect/fund/history")
async def fund_history(code: str, limit: int = 60) -> Any:
    out = await marketdata.fund_history(code, limit)
    if out is None:
        return _bad(f"无法获取基金 {code} 的历史净值", 404)
    return out


@router.get("/api/connect/movers")
async def movers(kind: str = "gainers", limit: int = 20) -> dict[str, Any]:
    return await marketdata.market_movers(kind, limit)


@router.get("/api/connect/indices")
async def indices() -> dict[str, Any]:
    """四大指数快照（新浪源；东财 push2 在部分网络下不可达时的稳定替代）。"""
    return await marketdata.index_snapshot()


# ---------------------------------------------------------------------------
# 交易意图
# ---------------------------------------------------------------------------


@router.get("/api/connect/intents")
async def intents(status: str = "", limit: int = 50) -> dict[str, Any]:
    return {"items": await store.list_intents(limit=limit, status=status)}


@router.post("/api/connect/intents")
async def create_intent(payload: dict[str, Any]) -> Any:
    try:
        return await store.create_intent(payload or {})
    except ValueError as exc:
        return _bad(str(exc))


@router.post("/api/connect/intents/{iid}/execute")
async def execute_intent(iid: str, payload: dict[str, Any] | None = None) -> Any:
    try:
        return await service.execute_trade_intent(iid, payload or {})
    except ValueError as exc:
        return _bad(str(exc))


@router.post("/api/connect/intents/{iid}/confirm")
async def confirm_intent(iid: str, payload: dict[str, Any]) -> Any:
    """实盘成交回填：记录实际成交价/数量，把意图标记为已执行。"""
    try:
        price = float((payload or {}).get("fill_price") or 0)
        shares = float((payload or {}).get("fill_shares") or 0)
    except (TypeError, ValueError):
        return _bad("成交价/数量必须是数字")
    if price <= 0 or shares <= 0:
        return _bad("成交价与数量必须大于 0")
    intent = await store.get_intent(iid)
    if intent is None:
        return _bad("交易意图不存在", 404)
    result = {**(intent.get("result") or {}), "fill_price": price, "fill_shares": shares, "confirmed_by_user": True}
    updated = await store.update_intent(iid, "executed", note="用户回填实盘成交", result=result)
    from ..provenance import record_provenance

    await record_provenance(
        action="connect_confirm_live_fill",
        entity_type="trade_intent",
        entity_id=iid,
        before={"status": intent["status"]},
        after={"status": "executed", "fill_price": price, "fill_shares": shares},
        source="connect",
    )
    return {"ok": True, "intent": updated}


@router.post("/api/connect/intents/{iid}/reject")
async def reject_intent(iid: str, payload: dict[str, Any] | None = None) -> Any:
    try:
        return await store.update_intent(
            iid, "rejected", note=str((payload or {}).get("reason") or "用户取消")
        )
    except ValueError as exc:
        return _bad(str(exc), 404)


@router.get("/api/connect/jobs")
async def jobs(limit: int = 30) -> dict[str, Any]:
    return {"items": await store.list_jobs(limit)}


__all__ = ["get_connector", "router"]

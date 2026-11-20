"""连接同步：公开源直采、文件导入走收件箱、需登录走配对码交接。"""

from __future__ import annotations

from typing import Any

from ..logging_utils import get_logger
from . import marketdata, store
from .service_bookmarklet import build_bookmarklet
from .service_inbox import scan_import_inbox

log = get_logger(__name__)



async def sync_connection(connection_id: str, lang: str = "zh") -> dict[str, Any]:
    """执行一次同步，返回 job 记录（含 result）。"""
    conn = await store.get_connection(connection_id)
    if conn is None:
        raise ValueError("连接不存在")
    from .catalog import get_connector

    connector = get_connector(conn["connector_id"]) or {}
    kind = connector.get("kind", "")
    job = await store.create_job(conn["connector_id"], kind="sync", message="开始同步")

    try:
        if kind == "public_api":
            result = await _sync_public(conn, connector)
        elif kind == "file_import":
            result = await scan_import_inbox()
        else:
            result = await _handoff(conn, connector, lang=lang)
    except Exception as exc:  # noqa: BLE001 — 单个连接失败不影响其他连接
        log.warning("connect.sync_failed id=%s err=%s", connection_id, exc)
        await store.touch_sync(connection_id, ok=False, error=str(exc))
        return (await store.finish_job(job["id"], False, f"同步失败：{exc}")) or job

    ok = bool(result.get("ok", True))
    if ok:
        await store.touch_sync(connection_id, ok=True)
    else:
        await store.touch_sync(connection_id, ok=False, error=str(result.get("note") or "同步未完成"))
    finished = await store.finish_job(job["id"], ok, str(result.get("message") or ""), result)
    return finished or job


async def _sync_public(conn: dict[str, Any], connector: dict[str, Any]) -> dict[str, Any]:
    """公开数据源同步：按连接器能力拉数据并落一份任务结果。"""
    cid = connector["id"]
    cap = set(connector.get("capabilities") or [])
    summary: dict[str, Any] = {"ok": True, "message": "已刷新", "source": connector["name"]}

    if cid in ("eastmoney_fund", "ttjj") or ("quotes" in cap and connector["category"] == "fund"):
        codes = str((conn.get("meta") or {}).get("fund_codes") or "").strip()
        nav = await marketdata.fund_nav(codes or "110011")
        summary["fund_nav"] = nav
        if not nav["items"]:
            summary.update(ok=False, message=nav.get("note") or "基金净值无返回")
    elif cid in ("eastmoney_quote", "sina_quote"):
        snap = await marketdata.index_snapshot()
        summary["indices"] = snap
        if not snap["items"]:
            summary.update(ok=False, message=snap.get("note") or "指数行情无返回")
    elif cid == "eastmoney_movers":
        movers = await marketdata.market_movers("gainers", 10)
        summary["movers"] = movers
        if not movers["items"]:
            summary.update(ok=False, message=movers.get("note") or "涨跌榜无返回")
    else:
        status = await marketdata.source_status()
        summary["source_status"] = status
        ok_items = [i for i in status["items"] if i["ok"]]
        if not ok_items:
            summary.update(ok=False, message="公开数据源全部不可用，请检查网络")
    return summary


async def _handoff(
    conn: dict[str, Any], connector: dict[str, Any], lang: str = "zh"
) -> dict[str, Any]:
    """需要登录的连接：签发配对码 + 官方入口，等用户在浏览器里完成。"""
    pairing = await store.issue_pairing_code(connector["id"])
    from ..compat_env import getenv

    base = getenv("MONEYHELPER_PUBLIC_URL").strip() or "http://127.0.0.1:8788"
    bookmarklet = build_bookmarklet(base, pairing["code"], connector["id"], lang)
    return {
        "ok": True,
        "message": "已生成一次性配对码，请到官方页面登录后回传" if lang != "en" else "Pairing code ready; sign in on the official site and send the page back",
        "connector_id": connector["id"],
        "login_url": pairing["login_url"],
        "pairing": pairing,
        "bookmarklet": bookmarklet,
        "ingest_endpoint": f"{base}/api/connect/ingest",
    }

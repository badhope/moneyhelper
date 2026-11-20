"""后台维护任务：月末自动结账、连接中心自动同步、账单收件箱扫描。

全程不抛异常：定时任务抛异常会被 APScheduler 记成失败并可能丢失下次重排。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from . import db
from .db.tenant import current_tenant_id
from .logging_utils import get_logger

log = get_logger(__name__)

async def _month_end_close() -> None:
    """每月 1 日 02:00 自动结账上月——「全托管」的最后一块。

    用户的立场是"我不懂会计，也不想点任何一个结账按钮"，所以：
    - 只处理「上月」：找到对应期间；没建账（期间不存在）就静默退出，不制造噪音；
    - 期间已 closed 直接跳过（幂等，重跑无副作用）；
    - 结账函数本身要求"无草稿凭证"，所以先把草稿过账；单张过账失败只记日志，
      不让一张异常凭证把整月结账卡死（关账那步会因仍有草稿而失败，此时同样只记日志）；
    - 全程不抛异常：定时任务抛异常会被 APScheduler 记成失败任务并可能在下次重排丢失。
    """
    today = datetime.now().astimezone().date()
    prev_end = today.replace(day=1) - timedelta(days=1)
    tenant = current_tenant_id()
    periods = await db.gl_list_periods(tenant)
    target = next(
        (
            p
            for p in periods
            if int(p["year"]) == prev_end.year and int(p["month"]) == prev_end.month
        ),
        None,
    )
    if target is None or str(target.get("status")) == "closed":
        return
    posted = 0
    for entry in await db.gl_list_entries(tenant, int(target["id"]), limit=500):
        if str(entry.get("status")) != "draft":
            continue
        try:
            await db.gl_post_entry(tenant, int(entry["id"]))
            posted += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("月末结账：凭证 %s 过账失败：%s", entry.get("id"), exc)
    try:
        await db.gl_close_period(tenant, int(target["id"]))
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "月末结账：%s-%02d 关账失败（可能仍有草稿）：%s", prev_end.year, prev_end.month, exc
        )
        return
    log.info("月末结账：%s-%02d 已自动关账（补过账 %d 张）", prev_end.year, prev_end.month, posted)


async def _sync_connect_sources() -> None:
    """后台自动同步「全自动」类连接（公开行情 / 基金净值）。

    只碰 automation=auto 且未停用的连接：登录类连接需要用户在场，
    绝不在后台凭空消耗配对码。单条失败只记日志，不影响其他连接。
    """
    try:
        from . import connect

        for conn in await connect.list_connections():
            if conn["status"] == "disabled":
                continue
            connector = connect.get_connector(conn["connector_id"]) or {}
            if connector.get("automation") != "auto":
                continue
            try:
                await connect.sync_connection(conn["id"])
            except Exception as exc:  # noqa: BLE001 — 单条同步失败不阻断调度
                log.warning("connect.auto_sync_failed id=%s err=%s", conn["id"], exc)
    except Exception as exc:  # noqa: BLE001 — 调度任务失败不能炸服务
        log.warning("connect.auto_sync crashed: %s", exc)


async def _scan_connect_inbox() -> None:
    """后台自动扫描账单收件箱：用户只需把官方导出的 CSV 放进去。"""
    try:
        from . import connect

        out = await connect.scan_import_inbox()
        if out.get("imported"):
            log.info("connect.inbox_auto_imported n=%s", out["imported"])
    except Exception as exc:  # noqa: BLE001
        log.warning("connect.inbox_scan crashed: %s", exc)

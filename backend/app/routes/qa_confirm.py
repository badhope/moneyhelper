"""待确认写操作（HITL）：token 一次性消费、per-token 串行锁、确认后执行。
"""

from __future__ import annotations

import asyncio
import json
from collections import OrderedDict

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import db, tool_schemas
from ..logging_utils import get_logger as _get_logger

log = _get_logger(__name__)

router = APIRouter()

_CONCURRENT_HITS_MAX = 512

_confirm_locks: OrderedDict[str, asyncio.Lock] = OrderedDict()

def _invalidate_after_write() -> None:
    """确认执行的是写工具（记账/建仓/改设置），必须让仪表盘缓存立即过期。"""
    from .. import analysis

    analysis.invalidate_dashboard_cache()

@router.post("/api/confirm")
async def confirm(payload: dict):
    token = str((payload or {}).get("token") or "").strip()
    decision = str((payload or {}).get("decision") or "").strip()
    if not token:
        log.warning("confirm: empty token")
        return JSONResponse({"error": "token required"}, status_code=400)
    if decision not in ("confirm", "cancel"):
        log.warning("confirm: bad decision %r", decision)
        return JSONResponse(
            {"error": "decision must be confirm or cancel"}, status_code=400
        )

    log.info("confirm request token=%s decision=%s", token[:12], decision)
    # 进程内 per-token 锁：串行化同一 token 的并发 confirm，防 TOCTOU 重复执行金融写操作
    if len(_confirm_locks) >= _CONCURRENT_HITS_MAX:
        _confirm_locks.popitem(last=False)
    if token not in _confirm_locks:
        _confirm_locks[token] = asyncio.Lock()
    lock = _confirm_locks[token]
    async with lock:
        pending = await db.get_pending_action(token)
        if pending is None:
            log.warning(
                "confirm: token=%s not found (expired/consumed/cancelled/unknown)",
                token[:12],
            )
            return JSONResponse(
                {"error": "动作已失效（过期/已执行/已取消），请重新发起"},
                status_code=409,
            )

        if decision == "cancel":
            await db.mark_pending_action(token, "cancelled")
            log.info(
                "confirm CANCEL token=%s tool=%s summary=%r",
                token[:12],
                pending["tool_name"],
                pending["summary"],
            )
            return {"ok": True, "cancelled": True, "summary": pending["summary"]}

        # 优先走 LangGraph 原生 HITL：从 interrupt 挂起点用 Command(resume) 恢复图，
        # 由 action 节点原子抢占 pending 并执行，返回图续跑的最终答案。
        from .. import agent_graph

        resumed = await agent_graph.resume_action(token, "confirm")
        if resumed is not None:
            log.info(
                "confirm RESUME token=%s → graph resumed: %s",
                token[:12],
                resumed["level"],
            )
            _invalidate_after_write()
            return {
                "ok": True,
                "tool": pending["tool_name"],
                "answer": resumed["answer"],
                "summary": pending["summary"],
                "graph": True,
            }

        # 没有挂起的图（进程重启 / 非 interrupt 路径）：同样必须先原子抢占，
        # 抢占失败说明已被执行过，直接返回 409，避免同一笔写操作被执行两次。
        claimed = await db.claim_pending_action(token)
        if claimed is None:
            log.warning("confirm: token=%s already consumed", token[:12])
            return JSONResponse(
                {"error": "动作已执行或已失效，未重复执行"}, status_code=409
            )
        pending = claimed
        from .. import tools as tools_mod

        impl = tools_mod.TOOL_IMPL.get(pending["tool_name"])
        if impl is None:
            log.error(
                "confirm: unknown tool %r for token=%s",
                pending["tool_name"],
                token[:12],
            )
            return JSONResponse(
                {"error": f"未知工具：{pending['tool_name']}"}, status_code=400
            )
        clean_args, verr = tool_schemas.validate_tool_args(pending["tool_name"], pending["args"])
        if clean_args is None:
            log.warning(
                "confirm: invalid args for %s token=%s: %s",
                pending["tool_name"],
                token[:12],
                verr,
            )
            return JSONResponse({"error": f"参数校验失败，操作未执行：{verr}"}, status_code=400)
        pending = {**pending, "args": clean_args}
        try:
            answer = await impl(pending["args"])
            log.info(
                "confirm EXEC token=%s tool=%s args=%s → ok",
                token[:12],
                pending["tool_name"],
                json.dumps(pending["args"], ensure_ascii=False),
            )
        except Exception as exc:  # noqa: BLE001 — 工具失败给可读回执
            log.exception(
                "confirm EXEC failed token=%s tool=%s", token[:12], pending["tool_name"]
            )
            answer = f"执行失败：{type(exc).__name__}: {exc}"
        _invalidate_after_write()
        return {
            "ok": True,
            "tool": pending["tool_name"],
            "answer": answer,
            "summary": pending["summary"],
        }

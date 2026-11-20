"""问答域路由：SSE 流式问答（ask）+ HITL 确认（confirm）+ 历史/会话管理。

从 main.py 拆出（M1.4）。鉴权由 main.py 的 api_auth 中间件统一覆盖。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import db, service
from ..logging_utils import get_logger as _get_logger
from ..middleware import spawn_background
from .qa_confirm import router as confirm_router
from .qa_department import router as department_router
from .qa_history import router as history_router
from .qa_sse import _LoopSafeEventSourceResponse, agui_stream, sse_stream  # noqa: F401

log = _get_logger(__name__)

router = APIRouter()

# HITL 确认 per-token 并发锁上限：与 agent_graph._HITL_THREADS 共用同一常量，
# 防止单用户/攻击者用大量挂起 token 耗尽内存。






# 兼容别名：原 main.py 内部符号（_sse_stream）




@router.post("/api/ask")
async def ask(payload: dict):
    return await _ask_impl(payload, protocol="internal")


@router.post("/api/ask/agui")
async def ask_agui(payload: dict):
    """AG-UI 协议版问答端点（M2.4）。

    与 /api/ask 共用同一套业务逻辑（同一个 runner），只是事件流形态不同。
    现有前端用 /api/ask；任何 AG-UI 客户端（CopilotKit 等）用这个。
    """
    return await _ask_impl(payload, protocol="agui")


async def _ask_impl(payload: dict, protocol: str = "internal"):
    question = ((payload or {}).get("question") or "").strip()
    if not question:
        return JSONResponse({"error": "question required"}, status_code=400)
    if len(question) > 2000:
        return JSONResponse({"error": "问题过长（最多 2000 字）"}, status_code=400)
    thread_id = ((payload or {}).get("thread_id") or "").strip() or uuid.uuid4().hex
    regenerate = bool((payload or {}).get("regenerate"))
    lang = ((payload or {}).get("lang") or "zh").strip() or "zh"
    # @提及附件：前端把附件 id 传过来，正文前附加其内容供模型理解
    att_ids = (payload or {}).get("attachments") or []
    attached_text = ""
    if att_ids:
        parts: list[str] = []
        for aid in att_ids:
            try:
                att = await db.get_attachment(int(aid))
            except Exception:  # noqa: BLE001
                att = None
            if att and att.get("content"):
                parts.append(
                    f"【附件：{att.get('filename')}】\n{att['content'][:2000]}"
                )
        if parts:
            attached_text = "\n\n".join(parts)

    async def runner(emit) -> None:
        # 重新生成：先移除该会话最后一条问答，再以同一问题重新作答（替换而非追加）
        if regenerate:
            try:
                await db.delete_last_run(thread_id, question)
            except Exception:  # noqa: BLE001 — 删除失败则退化为普通追加
                log.exception("delete_last_run failed")
        # @提及附件：把附件内容附加到问题正文，供 agent/模板理解
        full_question = (
            question + ("\n\n" + attached_text if attached_text else "")
        ).strip()
        result = await service.run_question(
            full_question, emit, thread_id=thread_id, lang=lang
        )
        # 备份口令：只在当次 SSE 展示，落库前脱敏，确保口令不写入历史/日志
        persisted_answer = result["answer"]
        passphrase = result.get("passphrase")
        if passphrase:
            persisted_answer = persisted_answer.replace(
                str(passphrase), "[口令仅当次展示，不落盘]"
            )
        try:
            await db.save_run(
                thread_id=thread_id,
                question=question,
                answer=persisted_answer,
                level=result["level"],
                flags=result["flags"],
                route=result.get("route", ""),
                llm=result.get("llm", ""),
                route_reason=result.get("route_reason", ""),
                tools=result.get("tools") or [],
                actions=result.get("actions") or [],
                tokens=result.get("tokens") or None,
            )
        except Exception:  # noqa: BLE001 — 落库失败不打断交付
            log.exception("save_run failed")
        # 长会话压缩（后台异步）：轮次超阈值时把较早轮次折叠成摘要落库，
        # 不阻塞 SSE 交付；失败静默（ensure_session_summary 内部已兜底）。
        # 通过 spawn_background 持有强引用，防止任务被 GC 静默取消。
        try:
            spawn_background(service.ensure_session_summary(thread_id))
        except Exception:  # noqa: BLE001 — 摘要任务登记失败不影响主流程
            log.warning("ensure_session_summary schedule failed")
        await emit(
            {
                "type": "final",
                "answer": result["answer"],
                "level": result["level"],
                "route": result["route"],
                "route_reason": result["route_reason"],
                "metrics": result["metrics"],
                "flags": result["flags"],
                "llm": result["llm"],
                "tools": result.get("tools") or [],
                "actions": result.get("actions") or [],
                # 待确认写操作：前端拿 token 显示确认卡片，确认后走 /api/confirm 执行
                "pending_token": result.get("pending_token", ""),
                "pending_summary": result.get("pending_summary", ""),
                # harness：本轮 token 用量（模板轮为 {}，前端仪表按需显示）
                "tokens": result.get("tokens") or {},
                # 备份口令：只在当次 final 事件下发一次（不落库、不进历史），
                # 否则用户拿到加密包却没有解密口令，备份等于不可恢复。
                "passphrase": result.get("passphrase", ""),
            }
        )

    if protocol == "agui":
        # start 事件由 service.run_question 发出；AG-UI 映射器会把它转成 CUSTOM(question)，
        # RUN_STARTED 由映射器自己发，所以这里同样不传首帧。
        return await agui_stream({"thread_id": thread_id}, runner)
    # start 事件由 service.run_question 发出（事件契约归 service），此处不再重复发首帧
    return await sse_stream(None, runner)


# ---------------------------------------------------------------------------
# 财务部门模式：SSE 实况看板（M3.6 后端）
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# 部门呈批（M3.5）：老板审批呈批件
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# 待确认写操作（HITL）：token 一次性消费，过期/已消费/已取消 → 409
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# 历史 / 晨报
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# 会话管理（多会话）
# ---------------------------------------------------------------------------












# ---------------------------------------------------------------------------
# harness：上下文用量 / 重新生成 / 会话分叉
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 部门 / HITL / 历史三组子路由：注册顺序与拆分前一致（department → confirm → history）
# ---------------------------------------------------------------------------
router.include_router(department_router)
router.include_router(confirm_router)
router.include_router(history_router)

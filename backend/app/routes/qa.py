"""问答域路由：SSE 流式问答（ask）+ HITL 确认（confirm）+ 历史/会话管理。

从 main.py 拆出（M1.4）。鉴权由 main.py 的 api_auth 中间件统一覆盖。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import OrderedDict
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from .. import db, service, tool_schemas
from ..logging_utils import get_logger as _get_logger
from ..middleware import spawn_background

log = _get_logger(__name__)

router = APIRouter()

# HITL 确认 per-token 并发锁上限：与 agent_graph._HITL_THREADS 共用同一常量，
# 防止单用户/攻击者用大量挂起 token 耗尽内存。
_CONCURRENT_HITS_MAX = 512
_confirm_locks: OrderedDict[str, asyncio.Lock] = OrderedDict()


class _LoopSafeEventSourceResponse(EventSourceResponse):
    """EventSourceResponse 子类：lazy 创建 anyio.Lock 与实例级 exit Event。

    sse-starlette 1.8 有两个跨 event loop 的隐患：
    - __init__ 里创建 `self._send_lock = anyio.Lock()`，绑定到构造时的循环；
    - `listen_for_exit_signal` 把 `anyio.Event()` 缓存在模块级
      `AppStatus.should_exit_event`，第二次及以后的请求在别的循环里 await 它
      会抛 `bound to a different event loop`。

    本服务每次请求都新建 response 并同步 `__call__`（FastAPI 端点内 return 后
    同一 loop 内处理），单 loop 场景行为不变。此子类将 lock 与 exit Event
    都改为实例级、延迟绑定到 `__call__` 所在的 loop，保证任何跨 loop 复用
    （如 pytest-asyncio 每测试一循环）场景下安全，同时保留优雅退出语义。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 覆盖父类在 __init__ 里创建的 lock，占位 None；__call__ 时再绑定
        self._send_lock = None  # type: ignore[assignment]
        self._exit_event = None

    def _ensure_lock(self):
        if self._send_lock is None:
            import anyio

            self._send_lock = anyio.Lock()
        return self._send_lock

    async def listen_for_exit_signal(self):
        """实例级 exit Event（而非模块级缓存），避免跨 loop 绑定报错。"""
        from sse_starlette.sse import AppStatus

        if AppStatus.should_exit:
            return
        if self._exit_event is None:
            import anyio

            self._exit_event = anyio.Event()
        if AppStatus.should_exit:
            return
        await self._exit_event.wait()

    async def __call__(self, scope, receive, send):
        self._ensure_lock()
        return await super().__call__(scope, receive, send)


async def sse_stream(first: dict | None, runner) -> _LoopSafeEventSourceResponse:
    """把 runner(emit) 产生的事件转成 SSE；断连时取消任务，不继续 yield。

    基于 sse-starlette EventSourceResponse：自带 ping 保活（防代理超时断连）、
    标准 retry 语义、client disconnect 检测。
    前端 fetch-event-source 约定为 `data: {json}` 行：yield 纯 JSON 字符串，
    EventSourceResponse 负责补 `data: ` 前缀与帧分隔，ping 以 `:` 注释行下发
    （浏览器与 fetch-event-source 均忽略），帧格式与手写实现保持一致。
    """

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        def data(obj: dict) -> str:
            return json.dumps(obj, ensure_ascii=False)

        async def emit(event: dict) -> None:
            await queue.put({"type": "event", **event})

        async def run() -> None:
            try:
                await runner(emit)
            except Exception as exc:  # noqa: BLE001 — 回吐脱敏文案，内部细节只进日志
                log.exception("SSE runner error: %s", exc)
                await queue.put(
                    {"type": "error", "message": "生成回答时出错，请稍后再试"}
                )
            finally:
                await queue.put(None)

        task = asyncio.create_task(run())
        if first is not None:
            yield data(first)
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=300)
                except asyncio.TimeoutError:
                    log.warning("SSE runner hung for 300s, force-cancelling")
                    yield data({"type": "error", "message": "响应超时，请重试"})
                    break
                if item is None:
                    break
                yield data(item)
            yield data({"type": "done"})
        finally:
            # client disconnect 或正常结束：确保后台 task 不泄漏
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    return _LoopSafeEventSourceResponse(
        event_stream(),
        media_type="text/event-stream",
        ping=15,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# 兼容别名：原 main.py 内部符号（_sse_stream）
_sse_stream = sse_stream


async def agui_stream(first: dict | None, runner) -> _LoopSafeEventSourceResponse:
    """AG-UI 协议版 SSE：把内部事件实时翻译成 AG-UI 事件。

    与 sse_stream 共用同一个 runner（业务逻辑零重复），差别只在事件形态：
    - sse_stream   → 内部契约（start/step/text/final），现有前端消费
    - agui_stream  → AG-UI 标准（RUN_STARTED/TEXT_MESSAGE_*/TOOL_CALL_*），
                     任何 AG-UI 客户端（CopilotKit 等）可直接消费

    翻译是流式的（逐事件 map，不缓冲整轮），所以前端的实时体验不变。
    """
    from .. import agui

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        def data(obj: dict) -> str:
            return json.dumps(obj, ensure_ascii=False)

        mapper = agui.AgUiMapper(thread_id=str((first or {}).get("thread_id") or ""))
        for ev in mapper.start():
            yield data(ev)

        async def emit(event: dict) -> None:
            await queue.put({"type": "event", **event})

        async def run() -> None:
            try:
                await runner(emit)
            except Exception as exc:  # noqa: BLE001
                log.exception("AG-UI runner error: %s", exc)
                await queue.put(
                    {"type": "error", "message": "生成回答时出错，请稍后再试"}
                )
            finally:
                await queue.put(None)

        task = asyncio.create_task(run())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=300)
                except asyncio.TimeoutError:
                    log.warning("AG-UI runner hung for 300s, force-cancelling")
                    for ev in mapper.map({"type": "error", "message": "响应超时，请重试"}):
                        yield data(ev)
                    break
                if item is None:
                    break
                for ev in mapper.map(item):
                    yield data(ev)
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    return _LoopSafeEventSourceResponse(
        event_stream(),
        media_type="text/event-stream",
        ping=15,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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


@router.post("/api/department/stream")
async def department_stream(payload: dict):
    """部门模式实况事件流：工单状态变更实时推送（供前端工位图）。

    与 /api/department/run 的区别：
    - run    返回一次性 JSON（含完整呈批件与全部事件）
    - stream 边执行边推送事件，前端能看到"哪个部门正在跑"

    事件序列：
      dept_start  → 派工完成，带工单清单
      dept        → 某工单状态变更（running/done/failed），带 metrics
      dept_final  → 秘书汇总完成，带结论与冲突
    """
    from .. import department

    question = str((payload or {}).get("question") or "").strip()
    if not question:
        return JSONResponse({"error": "question 必填"}, status_code=400)
    if len(question) > 2000:
        return JSONResponse({"error": "问题过长（最多 2000 字）"}, status_code=400)
    lang = str((payload or {}).get("lang") or "zh").strip() or "zh"

    async def runner(emit) -> None:
        report = await department.run_department_mode(question, emit, lang=lang)
        # 落库后才能跨请求审批（老板离开页面再回来仍可批）
        try:
            report_id = await db.dept_report_save(question, report)
            # 必须带上 status：前端据此决定是否显示审批按钮（pending 才有）。
            # 新落库的记录状态一定是 pending，与 db 层默认值一致。
            report = {**report, "report_id": report_id, "status": "pending"}
        except Exception:  # noqa: BLE001 — 落库失败不阻断交付，但如实标注
            log.exception("dept_report save failed")
            report = {**report, "report_id": ""}
        # 最终呈批件单独发一条，前端不必从 dept_final 事件里拼
        await emit({"type": "dept_report", "report": report})

    return await sse_stream(None, runner)


# ---------------------------------------------------------------------------
# 部门呈批（M3.5）：老板审批呈批件
# ---------------------------------------------------------------------------


@router.get("/api/department/reports")
async def dept_reports(status: str | None = None, limit: int = 20) -> dict:
    """列出呈批件（最新在前）。status=pending 只看待批的。"""
    return {"reports": await db.dept_report_list(status, limit)}


@router.get("/api/department/reports/{report_id}")
async def dept_report_detail(report_id: str) -> Any:
    report = await db.dept_report_get(report_id)
    if report is None:
        return JSONResponse({"error": "呈批件不存在"}, status_code=404)
    return report


@router.post("/api/department/reports/{report_id}/decide")
async def dept_report_decide(report_id: str, payload: dict) -> Any:
    """审批呈批件：approve（批准）/ reject（驳回，可附理由）/ inquire（追问）。

    - approve：结论被采纳，审计链记账
    - reject ：附理由驳回；理由会写进审计与呈批件
    - inquire：把追问内容作为新问题重新跑一轮部门模式，产生**新**呈批件
      （原呈批件保留为历史，审批链不被覆盖）

    并发安全：条件 UPDATE 保证同一份呈批件只能被审批一次，第二个请求返回 409。
    """
    from .. import department, provenance

    decision = str((payload or {}).get("decision") or "").strip()
    note = str((payload or {}).get("note") or "").strip()
    if decision not in db.DEPT_DECISIONS:
        return JSONResponse(
            {"error": f"decision 必须是 {'/'.join(db.DEPT_DECISIONS)} 之一"},
            status_code=400,
        )
    if decision in ("reject", "inquire") and not note:
        return JSONResponse(
            {"error": "驳回与追问都必须说明理由"}, status_code=400
        )

    report = await db.dept_report_get(report_id)
    if report is None:
        return JSONResponse({"error": "呈批件不存在"}, status_code=404)

    updated = await db.dept_report_decide(report_id, decision, note)
    if updated is None:
        return JSONResponse(
            {"error": "该呈批件已被处理", "status": report["status"]},
            status_code=409,
        )

    # 审计链：老板的决策与数字产出在同一条链上（"可复核"的一部分）
    try:
        await provenance.record_provenance(
            action=f"dept_report_{decision}",
            entity_type="dept_report",
            entity_id=report_id,
            before={"status": report["status"]},
            after={"status": updated["status"], "note": note},
            source="api",
        )
    except Exception:  # noqa: BLE001 — 审计失败不影响审批结果
        log.warning("dept_report audit failed: %s", report_id)

    out: dict[str, Any] = {"ok": True, "report": updated}
    if decision == "inquire":
        # 追问 = 带上追问内容重跑一轮，产出新呈批件
        followup_q = f"{report['question']}\n\n（老板追问：{note}）"
        new_report = await department.run_department_mode(followup_q)
        new_id = await db.dept_report_save(followup_q, new_report)
        out["followup_report_id"] = new_id
        # 同样补 status：前端切到追问产生的新件时要能继续审批
        out["followup_report"] = {**new_report, "report_id": new_id, "status": "pending"}
    return out


# ---------------------------------------------------------------------------
# 待确认写操作（HITL）：token 一次性消费，过期/已消费/已取消 → 409
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 历史 / 晨报
# ---------------------------------------------------------------------------


@router.get("/api/history")
async def history(thread_id: str | None = None, limit: int = 50, q: str = "") -> dict:
    limit = max(1, min(limit, 500))
    # 全局历史：跨会话搜索（供「全部历史」跳转定位）；指定线程则返回该会话历史
    if q.strip():
        return {"runs": await db.search_runs(q.strip(), limit)}
    return {"runs": await db.list_runs(thread_id, limit)}


@router.delete("/api/runs/{run_id}")
async def delete_run(run_id: int) -> dict:
    return await db.delete_run(run_id)


@router.post("/api/history/clear")
async def clear_history() -> dict:
    return await db.clear_history()


# ---------------------------------------------------------------------------
# 会话管理（多会话）
# ---------------------------------------------------------------------------


@router.get("/api/sessions")
async def sessions() -> dict:
    return {"sessions": await db.list_sessions()}


@router.post("/api/sessions")
async def create_session(payload: dict | None = None) -> dict:
    title = str((payload or {}).get("title") or "新会话").strip()
    return await db.create_session(title=title)


@router.patch("/api/sessions/{session_id}")
async def rename_session(session_id: int, payload: dict) -> dict:
    title = str(payload.get("title") or "").strip()
    if not title:
        return JSONResponse({"error": "标题不能为空"}, status_code=400)
    return await db.rename_session(session_id, title)


@router.post("/api/sessions/{session_id}/migrate")
async def migrate_session_runs(session_id: int, request: Request) -> dict:
    """把乐观新建窗口内挂在临时线程下的 runs 迁入真实会话。"""
    from_tid = request.query_params.get("from", "").strip()
    if not from_tid:
        return JSONResponse({"error": "from required"}, status_code=400)
    real_tid = await db.session_thread_id(session_id)
    if not real_tid:
        return JSONResponse({"error": "session not found"}, status_code=404)
    moved = await db.move_runs(from_tid, real_tid)
    return {"ok": True, "moved": moved}


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: int) -> dict:
    return await db.delete_session(session_id)

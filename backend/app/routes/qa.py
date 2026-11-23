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


# 只放一个短标记，不把指令正文拼进问题：指令里一旦出现「股价」「茅台」等示例词，
# 会被路由词表当成理财问题（实测「AI 新闻」被答成持仓行情并追加投资免责声明）。
# 详细规则由 agent.run_agent 以 system 消息注入，问题本身保持用户原话。
WEB_SEARCH_MARKER = "［联网搜索］"


def _compose_question(question: str, attached_text: str = "", web_search: bool = False) -> str:
    """把附件正文与联网标记拼进本轮问题；落库仍用原 question。"""
    return (
        question
        + ("\n\n" + attached_text if attached_text else "")
        + ("\n\n" + WEB_SEARCH_MARKER if web_search else "")
    ).strip()


async def _ask_impl(payload: dict, protocol: str = "internal"):
    question = ((payload or {}).get("question") or "").strip()
    if not question:
        return JSONResponse({"error": "question required"}, status_code=400)
    if len(question) > 2000:
        return JSONResponse({"error": "问题过长（最多 2000 字）"}, status_code=400)
    thread_id = ((payload or {}).get("thread_id") or "").strip() or uuid.uuid4().hex
    regenerate = bool((payload or {}).get("regenerate"))
    lang = ((payload or {}).get("lang") or "zh").strip() or "zh"
    # 联网搜索开关：只在用户显式开启时追加指令；不改变原问题落库内容
    web_search = bool((payload or {}).get("web_search"))
    # 深度研究：多轮检索 + 固定报告结构；用户开了它就必须联网，否则没有“研究”的输入
    deep_research = bool((payload or {}).get("deep_research"))
    if deep_research:
        web_search = True
    # 回答长度偏好：只进 system 指令，不改路由，不写进落库问题
    answer_mode = str((payload or {}).get("answer_mode") or "standard").strip().lower()
    if answer_mode not in {"concise", "standard", "detailed"}:
        answer_mode = "standard"
    # 会话项目卡：固定资料、项目指令、项目记忆都只作用于当前 thread
    session_ctx = await db.get_thread_context(thread_id)
    ctx_ids = [int(a.get("id")) for a in (session_ctx.get("attachments") or []) if a.get("id")]
    # @提及附件：前端把附件 id 传过来，正文前附加其内容供模型理解
    raw_att_ids = list((payload or {}).get("attachments") or []) + ctx_ids
    # 前端 payload 里的 attachments 是对象数组（{id,filename,kind}），早期测试/脚本
    # 传的是 id 数组；两种都接受，否则图片会被 int(dict) 静默吞掉。
    att_ids: list[int] = []
    for item in raw_att_ids if isinstance(raw_att_ids, list) else []:
        value = item.get("id") if isinstance(item, dict) else item
        try:
            if value is not None:
                att_ids.append(int(value))
        except (TypeError, ValueError):
            continue
    attached_text = ""
    attachments_meta: list[dict[str, object]] = []
    images: list[dict[str, str]] = []
    image_chars = 0
    if att_ids:
        parts: list[str] = []
        seen_ids: set[int] = set()
        for aid in att_ids[:20]:
            try:
                att = await db.get_attachment(int(aid))
            except Exception:  # noqa: BLE001
                att = None
            if not att:
                continue
            att_id = int(att.get("id") or 0)
            new_att = bool(att_id) and att_id not in seen_ids
            if new_att:
                seen_ids.add(att_id)
                meta: dict[str, object] = {
                    "id": att_id,
                    "filename": str(att.get("filename") or "")[:255],
                    "kind": str(att.get("kind") or "text")[:20],
                }
                if att.get("mime"):
                    meta["mime"] = str(att["mime"])[:80]
                attachments_meta.append(meta)
                # 视觉输入：图片原始字节随本轮消息送模型，最多 4 张 / 20MB base64，
                # 避免一份超大相册把整轮请求拖到超时。
                if str(att.get("kind") or "") == "image" and att.get("data"):
                    data = str(att["data"])
                    if len(images) < 4 and image_chars + len(data) <= 20_000_000:
                        images.append(
                            {
                                "filename": str(att.get("filename") or ""),
                                "mime": str(att.get("mime") or "image/png")[:80],
                                "data": data,
                            }
                        )
                        image_chars += len(data)
                if att.get("content"):
                    parts.append(
                        f"【附件：{att.get('filename')}】\n{att['content'][:2000]}"
                    )
        if parts:
            attached_text = "\n\n".join(parts)

    async def runner(emit) -> None:
        # 重新生成：先移除该会话最后一条问答，再以同一问题重新作答（替换而非追加）
        replaced_attachments: list[dict[str, object]] = []
        if regenerate:
            try:
                removed = await db.delete_last_run(thread_id, question)
                replaced_attachments = removed.get("attachments") or []
            except Exception:  # noqa: BLE001 — 删除失败则退化为普通追加
                log.exception("delete_last_run failed")
        # @提及附件：把附件内容附加到问题正文，供 agent/模板理解
        full_question = _compose_question(question, attached_text, web_search)
        ctx_parts: list[str] = []
        if session_ctx.get("instructions"):
            ctx_parts.append(
                "本会话项目指令（优先遵守；仍不得越过安全边界与工具事实）：\n"
                + str(session_ctx["instructions"])[:2000]
            )
        memories = [str(m.get("text") or "").strip() for m in (session_ctx.get("memories") or [])]
        memories = [m for m in memories if m][:10]
        if memories:
            ctx_parts.append(
                "本会话项目记忆（只在本会话生效，数字以工具结果为准）：\n"
                + "\n".join(f"- {m[:200]}" for m in memories)
            )
        if answer_mode == "concise":
            ctx_parts.append("回答长度：简洁。先给结论，通常不超过 6 句话；不要重复问题，不写客套开场。")
        elif answer_mode == "detailed":
            ctx_parts.append("回答长度：详尽。给出完整推理、口径与边界；能分节就分节，但不要注水。")
        if deep_research:
            ctx_parts.append(
                "深度研究模式：先把问题拆成 3 个不同角度，逐一检索或核对，再成文。"
                "报告必须包含「结论」「依据」「风险与不确定性」「后续观察点」「来源」五节；"
                "来源只列工具实际返回或正文真实出现的链接，不补造。"
            )
        result = await service.run_question(
            full_question,
            emit,
            thread_id=thread_id,
            lang=lang,
            session_context="\n\n".join(ctx_parts),
            deep_research=deep_research,
            llm_options={"answer_mode": answer_mode},
            images=images,
        )
        # 回答依据：知识库命中与正文外链，随回答一起交付/落库，历史可回看
        from ..qa_sources import collect_sources

        sources = await collect_sources(question, result["answer"])
        # 备份口令：只在当次 SSE 展示，落库前脱敏，确保口令不写入历史/日志
        persisted_answer = result["answer"]
        passphrase = result.get("passphrase")
        if passphrase:
            persisted_answer = persisted_answer.replace(
                str(passphrase), "[口令仅当次展示，不落盘]"
            )
        run_row: dict | None = None
        try:
            run_row = await db.save_run(
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
                attachments=attachments_meta or replaced_attachments,
                tokens=result.get("tokens") or None,
                sources=sources,
                steps=result.get("steps") or [],
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
                "sources": sources,
                # 本轮落库后的 run id：让新回答立刻能点赞/点踩，不必刷新历史
                "run_id": int((run_row or {}).get("id") or 0),
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

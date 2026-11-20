"""SSE 传输层：内部事件契约与 AG-UI 协议两种事件流。

sse-starlette 的两个跨事件循环隐患（lazy send_lock / 模块级 exit event）在此统一处理。
"""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from ..logging_utils import get_logger as _get_logger

log = _get_logger(__name__)

router = APIRouter()

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

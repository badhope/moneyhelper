"""AG-UI 映射层（M2.4）：把内部 SSE 事件翻译成 AG-UI 协议事件流。

## 为什么做映射而不是换协议

内部事件契约（`start` / `step` / `agent_step` / `text` / `thinking` / `final`）
是两年迭代出来的、贴合 Moneyhelper 业务语义的形态：`step` 带 `phase`、`agent_step` 带
工具摘要、`final` 带风控 `flags` 与可撤销 `actions`。直接换成 AG-UI 会把业务
语义压扁成通用协议，前端要重新实现一遍卡片渲染逻辑。

映射层让两种消费者共存：
- 现有前端继续用内部事件（零改动）
- 任何 AG-UI 客户端（CopilotKit 等）可以通过 `/api/ask/agui` 拿到标准事件流

## 事件映射表

| 内部事件 | AG-UI 事件 | 说明 |
|---|---|---|
| （流开始） | `RUN_STARTED` | 带 threadId / runId |
| `start` | — | 内部语义（携带问题原文），AG-UI 用 RUN_STARTED 表达 |
| `step` phase=start | `STEP_STARTED` | stepName = label |
| `step` phase=done | `STEP_FINISHED` | |
| `agent_step` | `TOOL_CALL_START` + `TOOL_CALL_ARGS` + `TOOL_CALL_END` | 工具调用三连 |
| `thinking` | `REASONING_MESSAGE_START` + `CONTENT` + `END` | 首帧开、末帧关 |
| `text` | `TEXT_MESSAGE_START` + `CONTENT` + `END` | 同上 |
| `card` | `CUSTOM` | 卡片是应用自定义语义，用 CUSTOM 承载 |
| `plan` | `CUSTOM` | 计划同理 |
| `final` | `RUN_FINISHED` | 携带 answer 与业务元信息 |
| `error` | `RUN_ERROR` | |

## 关键设计约束

1. **消息边界必须显式**：AG-UI 要求 TextMessage 有 start/end，而内部 `text`
   是裸增量。映射器必须自己跟踪"当前是否在一条消息内"，在切换到别的类型
   或流结束时补 END。
2. **runId 每轮唯一**：AG-UI 靠它区分不同 run，用 uuid4。
3. **CUSTOM 事件保留业务字段**：卡片/计划这些 AG-UI 没有对应类型的东西，
   用 `CUSTOM(name=内部type, value=原事件)` 透传，不丢信息。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

# AG-UI 事件类型常量（与规范一致，避免拼写漂移）
RUN_STARTED = "RUN_STARTED"
RUN_FINISHED = "RUN_FINISHED"
RUN_ERROR = "RUN_ERROR"
STEP_STARTED = "STEP_STARTED"
STEP_FINISHED = "STEP_FINISHED"
TEXT_MESSAGE_START = "TEXT_MESSAGE_START"
TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"
TEXT_MESSAGE_END = "TEXT_MESSAGE_END"
TOOL_CALL_START = "TOOL_CALL_START"
TOOL_CALL_ARGS = "TOOL_CALL_ARGS"
TOOL_CALL_END = "TOOL_CALL_END"
REASONING_MESSAGE_START = "REASONING_MESSAGE_START"
REASONING_MESSAGE_CONTENT = "REASONING_MESSAGE_CONTENT"
REASONING_MESSAGE_END = "REASONING_MESSAGE_END"
CUSTOM = "CUSTOM"


class AgUiMapper:
    """把内部事件逐条翻译成 AG-UI 事件。

    有状态：需要跟踪当前开着的文本/思考消息与工具调用，以便正确闭合。
    一个实例对应一次 run，不要跨请求复用。
    """

    def __init__(self, thread_id: str = "") -> None:
        self.thread_id = thread_id
        self.run_id = uuid.uuid4().hex
        self._text_id: str | None = None
        self._reason_id: str | None = None
        self._tool_seq = 0
        self._open_steps: list[str] = []

    # -- 内部辅助 ---------------------------------------------------------

    def _close_text(self) -> list[dict[str, Any]]:
        if self._text_id is None:
            return []
        out = [{"type": TEXT_MESSAGE_END, "messageId": self._text_id}]
        self._text_id = None
        return out

    def _close_reasoning(self) -> list[dict[str, Any]]:
        if self._reason_id is None:
            return []
        out = [{"type": REASONING_MESSAGE_END, "messageId": self._reason_id}]
        self._reason_id = None
        return out

    # -- 入口 -------------------------------------------------------------

    def start(self) -> list[dict[str, Any]]:
        """run 开始：发 RUN_STARTED。"""
        return [{"type": RUN_STARTED, "threadId": self.thread_id, "runId": self.run_id}]

    def map(self, ev: dict[str, Any]) -> list[dict[str, Any]]:
        """把一个内部事件映射成 0..n 个 AG-UI 事件。"""
        kind = str(ev.get("type") or "")
        out: list[dict[str, Any]] = []

        if kind == "start":
            # 内部 start 携带问题原文，AG-UI 侧已在 RUN_STARTED 表达；
            # 但问题文本对客户端有用，用 CUSTOM 保留。
            return [{"type": CUSTOM, "name": "question", "value": ev}]

        if kind == "step":
            phase = str(ev.get("phase") or "")
            name = str(ev.get("label") or ev.get("id") or "")
            if phase == "start":
                out.extend(self._close_text())
                out.extend(self._close_reasoning())
                self._open_steps.append(name)
                out.append({"type": STEP_STARTED, "stepName": name})
            elif phase == "done":
                # 内部契约里存在"单次完成"型 step（如「已入账」「已记住」：
                # 只发 done 不发 start）。AG-UI 要求 STEP_FINISHED 必须配对，
                # 所以这里为未知 step 补一个 START，保证客户端不会收到孤立 FINISHED。
                if name not in self._open_steps:
                    out.append({"type": STEP_STARTED, "stepName": name})
                else:
                    self._open_steps.remove(name)
                out.append({"type": STEP_FINISHED, "stepName": name})
            return out

        if kind == "agent_step":
            out.extend(self._close_text())
            out.extend(self._close_reasoning())
            self._tool_seq += 1
            call_id = f"{self.run_id}-tool-{self._tool_seq}"
            name = str(ev.get("name") or "tool")
            out.append({"type": TOOL_CALL_START, "toolCallId": call_id, "toolCallName": name})
            args = ev.get("args")
            if args is not None:
                import json

                out.append(
                    {
                        "type": TOOL_CALL_ARGS,
                        "toolCallId": call_id,
                        "delta": json.dumps(args, ensure_ascii=False),
                    }
                )
            out.append({"type": TOOL_CALL_END, "toolCallId": call_id})
            if ev.get("summary"):
                out.append({"type": CUSTOM, "name": "tool_summary", "value": ev})
            return out

        if kind == "thinking":
            content = str((ev.get("data") or {}).get("content") or "")
            if not content:
                return []
            if self._reason_id is None:
                out.extend(self._close_text())
                self._reason_id = f"{self.run_id}-reason"
                out.append(
                    {
                        "type": REASONING_MESSAGE_START,
                        "messageId": self._reason_id,
                        "role": "reasoning",
                    }
                )
            out.append(
                {"type": REASONING_MESSAGE_CONTENT, "messageId": self._reason_id, "delta": content}
            )
            return out

        if kind == "text":
            delta = str(ev.get("delta") or "")
            if not delta:
                return []
            if self._text_id is None:
                out.extend(self._close_reasoning())
                self._text_id = f"{self.run_id}-msg"
                out.append(
                    {"type": TEXT_MESSAGE_START, "messageId": self._text_id, "role": "assistant"}
                )
            out.append(
                {"type": TEXT_MESSAGE_CONTENT, "messageId": self._text_id, "delta": delta}
            )
            return out

        if kind == "final":
            out.extend(self._close_text())
            out.extend(self._close_reasoning())
            # 未闭合的 step 补 FINISHED（内部契约不保证成对，AG-UI 要求配对）
            for name in list(self._open_steps):
                out.append({"type": STEP_FINISHED, "stepName": name})
            self._open_steps.clear()
            out.append(
                {
                    "type": RUN_FINISHED,
                    "threadId": self.thread_id,
                    "runId": self.run_id,
                    "result": {
                        "answer": ev.get("answer", ""),
                        "level": ev.get("level", ""),
                        "route": ev.get("route", ""),
                        "route_reason": ev.get("route_reason", ""),
                        "metrics": ev.get("metrics") or {},
                        "flags": ev.get("flags") or [],
                        "llm": ev.get("llm", ""),
                        "tools": ev.get("tools") or [],
                        "actions": ev.get("actions") or [],
                        "pending_token": ev.get("pending_token", ""),
                        "pending_summary": ev.get("pending_summary", ""),
                    },
                }
            )
            return out

        if kind == "error":
            out.extend(self._close_text())
            out.extend(self._close_reasoning())
            out.append(
                {
                    "type": RUN_ERROR,
                    "message": str(ev.get("message") or ev.get("error") or "unknown error"),
                    "code": str(ev.get("code") or ""),
                }
            )
            return out

        # card / plan / 其他业务事件：AG-UI 无对应类型，用 CUSTOM 原样透传
        return [{"type": CUSTOM, "name": kind or "unknown", "value": ev}]


async def translate(
    events: AsyncIterator[dict[str, Any]], thread_id: str = ""
) -> AsyncIterator[dict[str, Any]]:
    """把一个内部事件流整体翻译成 AG-UI 事件流。"""
    mapper = AgUiMapper(thread_id)
    for ev in mapper.start():
        yield ev
    async for ev in events:
        for out in mapper.map(ev):
            yield out

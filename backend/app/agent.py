"""Agent 编排层：LLM function calling 多轮工具循环（真正的垂直 agent）。

与 agent_graph.py 的分工：
  - agent_graph.py 负责「编排」：意图分类、节点顺序、条件分支（LangGraph 状态机）；
  - 本模块负责「成文执行」：finalize 节点在 agent 模式下调用本模块的 run_agent，
    让模型自主决定调用 tools.py 里的工具取数并成文；
  - 模型不可用/工具循环失败 → 抛 AgentUnavailable，由 agent_graph.finalize 图内降级
    确定性模板成文（不是双实现，是编排层与执行层的分工）。

技能包装配（先 Agent、后财务）：
  - 财务分支（finalize）：run_agent 默认走财务技能包（AGENT_SYSTEM + READ_TOOLS，
    读类财务工具 + 长期记忆注入）。
  - 通用分支（service._run_general）：run_agent 走通用技能包（GENERAL_SYSTEM +
    GENERAL_TOOLS = web_search / get_now），领域无关，不注入财务数据。

事件契约（新增）：
  {"type":"agent_step","name":"get_market_view","args":{...},"summary":"总市值 282,540 元…"}

隐私边界与确定性内核保持一致：
  - 工具只读本地数据，结果摘要化后回填（truncate_tool_result）
  - 通用闲聊不带任何财务数据出机（路由仍由 service 层决定）
"""

from __future__ import annotations

import json
import time
from typing import Any

from . import db, llm, mcp_client, tools

# 写类工具已被确定性分支覆盖（记账/记忆/买卖/设置/备份/晨报都有前置 action/record/memory
# 节点拦截），agent 模式只暴露读类 + 自选维护工具，防止模型在追问/分析语境里越权落库。
#
# 判定改为由 tool_policy 统一回答（而不是手写集合）：新增工具时不必记得
# 同步这个集合，未知工具默认 ASK（fail-closed），不会被意外暴露给模型。
from .agent_errors import AgentUnavailable  # noqa: F401 — 对外同名导出
from .agent_prompts import AGENT_SYSTEM, GENERAL_SYSTEM  # noqa: F401 — 对外同名导出
from .agent_stream import Emit, _now_ms, _stream_final_answer  # noqa: F401 — run_agent 使用
from .agent_studio import studio_post_answer, studio_pre_tool  # noqa: F401 — 对外同名导出
from .agent_turn import RepeatGuard, final_answer_result, wrap_up_answer
from .observability import timed
from .tool_schemas import validate_tool_args

# 只按「内置财务工具」过滤，不能把外部 MCP 工具误伤：
# `mcp__search_symbol` 之类的名字不在内置表里，若按「未登记即排除」处理，
# 所有外部只读 MCP 工具都会失效（这曾导致 test_mcp_read_tools_not_blocked 失败）。
# 执行层白名单：只允许模型实际调用「读类 + 自选维护」工具。写工具（记账/记忆/买卖/设置/
# 备份/晨报）由确定性前置分支拦截，绝不暴露给模型执行，防止 prompt 注入/幻觉越权落库。

# 通用技能包：领域无关工具（时间 / 联网搜索），供 general（非财务）分支装配。
# 这是「先 Agent 后财务」的落点：通用 Agent 内核不依赖任何财务能力。

# 通用 Agent 内核说明书（general 分支用）：领域无关的自主 agent 行为规则。


async def run_agent(    question: str,
    emit: Emit,
    history: list[dict[str, str]] | None = None,
    lang: str = "zh",
    *,
    system: str | None = None,
    tools_list: list | None = None,
    impl_map: dict | None = None,
    inject_memories: bool = True,
) -> dict[str, Any]:
    """跑一轮 agent：模型自主调用工具后成文。失败抛 AgentUnavailable。

    默认走财务技能包（AGENT_SYSTEM + READ_TOOLS + 长期记忆注入）；
    general 分支通过 system/tools_list/impl_map/inject_memories 装配通用技能包。
    """
    cfg = await llm._config()  # noqa: SLF001 — 同一包内复用配置读取
    if cfg is None:
        raise AgentUnavailable("未接入模型")

    client = llm._get_client(cfg, timeout=60.0)  # noqa: SLF001 — LiteLLM 后端
    from .agent_context import build_turn_context

    messages, role_temperature, _s = await build_turn_context(
        question,
        lang=lang,
        system=system,
        inject_memories=inject_memories,
        history=history,
        cfg=cfg,
    )
    # 工具轮次上限与失败反思重试（设置中心控制，默认与历史一致）
    turn_cap = max(1, min(int((_s.get("agent_tool_turns") or MAX_TURNS) or MAX_TURNS), 30))
    reflect = (_s.get("agent_reflect") or "on") != "off"

    steps: list[dict[str, Any]] = []
    used_tools: list[str] = []
    tool_counts: dict[str, int] = {}

    # 长会话上下文压缩：messages 超过 8 条时，用 stream_text_short 把早期历史摘要化
    # （对齐 Claude Code 的 progressive disclosure：长会话摘要兜底，防 context window 溢出）
    messages = await _compress_history(messages, cfg)

    from .agent_toolset import build_toolset

    tool_schemas, tool_map, internal_impl, mcp_schemas = await build_toolset(
        tools_list, impl_map
    )
    # 循环检测：模型有时会反复用完全相同的参数调同一个工具（尤其工具持续报错时），
    # 白烧 token 也拿不到新信息。连续 3 次完全相同则中断并如实说明。
    _guard = RepeatGuard(max_repeat=3)

    for _turn in range(turn_cap):
        try:
            with timed("llm.tool_loop", model=cfg.get("model", ""), turn=_turn):
                resp = await client.chat.completions.create(
                    model=cfg["model"] or "gpt-4o-mini",  # model 可留空 → 用默认，与 stream_narrate 一致
                    messages=messages,
                    tools=tool_schemas,
                    tool_choice="auto",
                    temperature=role_temperature,
                    # 单轮输出上限：防止模型陷入超长生成把请求拖到超时
                    max_tokens=2048,
                    # 429/5xx 由 LiteLLM 自动重试（与流式路径一致）
                    num_retries=2,
                    timeout=60,
                )
        except Exception as exc:  # noqa: BLE001 — 端点失败/不支持 tools → 降级
            raise AgentUnavailable(f"模型调用失败：{type(exc).__name__}") from exc

        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)

        if not tool_calls:
            # 最终回答：流式输出（逐 token 推送到前端 markdown 渲染）
            # 先尝试流式；失败时退回非流式兜底
            return await final_answer_result(
                client,
                cfg,
                messages,
                tool_schemas,
                emit,
                steps=steps,
                used_tools=used_tools,
                tool_counts=tool_counts,
            )

        # 模型要求调用工具：先原样回填 assistant 消息，再执行工具并回填结果。
        # 若模型在调用工具的同时给出说明（如"我来查一下"），作为 thinking 过程展示。
        if (msg.content or "").strip():
            await emit({
                "type": "thinking",
                "data": {"content": (msg.content or "").strip()},
                "node": "finalize",
            })
        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ],
            }
        )
        for tc in tool_calls:
            name = tc.function.name
            # P2 MCP：外部 MCP 工具（server 名一致时才走 MCP 调用）
            mcp_hit = mcp_client.resolve_mcp_tool(name) if mcp_schemas else None
            # MCP 工具同样受写操作禁令约束：外部服务器可能暴露与本地写工具同义的能力
            # （记账/下单/改设置）。mcp__ 前缀是唯一入口，这里按去掉前缀后的名字比对，
            # 命中 WRITE_EXCLUDED 一律拒绝——否则模型可借 MCP 绕过确定性写分支。
            if mcp_hit is not None:
                # 只读边界：MCP 规范没有统一的"工具名 = 语义"约定，必须看服务器
                # 声明的 annotations.readOnlyHint。未声明/未发现的一律拒绝，
                # 防止外部服务器用任意名字暴露转账、写入等副作用。
                if not mcp_client.is_tool_exposed(name):
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": (
                                "该外部工具未声明为只读（readOnlyHint），已按安全策略拒绝。"
                                "如确需使用，请在服务端显式设置 "
                                "MONEYHELPER_MCP_EXTERNAL_TOOLS=all 并自行承担风险。"
                            ),
                        }
                    )
                    continue
                bare = name.removeprefix("mcp__")
                if bare in WRITE_EXCLUDED or name in WRITE_EXCLUDED:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": "该工具为写操作，只能由用户显式指令触发，模型不可调用。",
                        }
                    )
                    continue
            impl = tool_map.get(name) or internal_impl.get(name)
            if impl is None and mcp_hit is None:
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": f"工具不可用：{name}"}
                )
                continue
            try:
                args = json.loads(tc.function.arguments or "{}")
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                args = {}
            # Studio pre_tool Hook：拦截 / 告警（默认拦截 shell、文件写入类外部工具）
            try:
                hook_result = await studio_pre_tool(name, args)
                if hook_result.get("blocked"):
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": f"Hook 已拦截：{hook_result.get('reason') or '该工具被安全策略禁止'}",
                        }
                    )
                    await emit(
                        {
                            "type": "agent_step",
                            "name": name,
                            "args": args,
                            "summary": f"Hook 拦截：{hook_result.get('reason') or '安全策略'}",
                        }
                    )
                    continue
            except Exception:  # noqa: BLE001 — Hook 故障不阻断正常工具
                pass
            # 执行前校验入参（extra="forbid" 落地点）：非法参数不进 impl，
            # 错误文案回填给模型，下一轮 self-correct。
            if name in internal_impl:
                clean_args = args
                verr = None
            else:
                clean_args, verr = validate_tool_args(name, args)
            if clean_args is None:
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": verr}
                )
                continue
            args = clean_args
            tool_counts[name] = tool_counts.get(name, 0) + 1
            used_tools.append(name)
            # 同工具 + 同参数连续重复检测（在真正执行前判定，避免第三次无效调用）
            _repeat_count = _guard.hit(name, args)
            if _guard.exhausted(_repeat_count):
                await emit({
                    "type": "thinking",
                    "data": {"content": f"检测到重复调用 {name}，已停止以避免空转。"},
                    "node": "finalize",
                })
                messages.append({
                    "role": "system",
                    "content": (
                        f"你已连续 {_repeat_count} 次用相同参数调用 {name}，结果不会变化。"
                        "请直接基于已有信息作答，或换一种方式。"
                    ),
                })
                break
            # 工具生命周期：running → 结果
            await emit({
                "type": "tool",
                "data": {
                    "id": tc.id, "name": name, "args": args,
                    "status": "running", "node": "finalize", "ts": _now_ms(),
                },
            })
            started = time.monotonic()
            try:
                if mcp_hit is not None:
                    # MCP 工具调用（外部服务器）
                    with timed(f"mcp.{mcp_hit[1]}", tool=name):
                        result = await mcp_client.call_mcp_tool(mcp_hit[0], mcp_hit[1], args)
                else:
                    with timed(f"tool.{name}", tool=name):
                        result = tools.truncate_tool_result(await impl(args))
                status = "done"
            except Exception as exc:  # noqa: BLE001 — 工具失败回填错误，不让循环崩
                result = f"工具执行失败：{type(exc).__name__}: {exc}"
                status = "error"
                # P1 经验库：把失败「踩坑点」记入 reflections，供下次反思参考（异步不阻塞）
                try:
                    await db.add_reflection(
                        name,
                        args,
                        str(exc)[:200],
                        f"工具 {name} 失败：{type(exc).__name__}。检查参数与调用方式后重试。",
                    )
                except Exception:  # noqa: BLE001 — 记录失败不影响主流程
                    pass
            duration_ms = int((time.monotonic() - started) * 1000)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            # 反思重试（可配置）：工具失败时明确提示模型修正参数/换思路，下一轮自纠（防反复撞同一个错）
            if status == "error" and reflect:
                # 参考经验库里的历史踩坑点，避免重复同一个错误
                lessons = await db.list_reflections(limit=5)
                lesson_txt = ""
                if lessons:
                    lesson_txt = "过往同类踩坑记录：\n" + "\n".join(
                        f"- {ls['tool']}: {ls['lesson']}" for ls in lessons if ls["tool"] == name
                    )
                messages.append({
                    "role": "system",
                    "content": (
                        "上一次工具调用失败了。请反思原因（参数、关键词、流程），修正后重试，"
                        "不要重复同样的错误；若确实无法完成，如实告诉用户。"
                        + (lesson_txt or "")
                    ),
                })
            summary = _tool_summary(name, result)
            steps.append({"name": name, "args": args, "summary": summary})
            await emit({
                "type": "tool",
                "node": "finalize",
                "data": {
                    "id": tc.id, "name": name, "status": status,
                    "summary": summary, "duration_ms": duration_ms, "ts": _now_ms(),
                },
            })
            # 兼容旧契约：agent_step 仍发（summary 聚合）
            await emit({"type": "agent_step", "name": name, "args": args, "summary": summary})

    # 轮次用尽：不要让整次问答作废，交给收尾请求兜底成文（失败抛降级）。
    return await wrap_up_answer(
        client, cfg, messages, emit, steps=steps, max_turns=MAX_TURNS
    )

from .agent_history import _compress_history  # noqa: F401,E402 — run_agent 使用
from .agent_tooling import (  # noqa: F401,E402 — 对外同名导出
    ALLOWED_IMPL,
    GENERAL_IMPL,
    GENERAL_TOOLS,
    MAX_TURNS,
    READ_TOOLS,
    WRITE_EXCLUDED,
    _tool_summary,
)


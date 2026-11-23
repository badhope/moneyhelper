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
from .agent_tool_rank import rank_tools
from .agent_turn import RepeatGuard, final_answer_result, wrap_up_answer
from .llm_client import llm_tool_limit
from .logging_utils import get_logger
from .observability import timed
from .tool_schemas import validate_tool_args

_log = get_logger("agent")

_STALL_MARKERS = ("稍等", "请稍等", "等我", "我先取数", "我再核", "正在分析", "马上给")

def _looks_like_stall(text: str) -> bool:
    """模型把「过程承诺」当终答：没有 tool_calls，却只回一句「我先取数，稍等」。
    这种回答看似礼貌，实际用户拿不到任何结论；应当强制它基于已有工具结果成文。"""
    body = (text or "").strip()
    if not body or len(body) > 600:
        return False
    return any(marker in body for marker in _STALL_MARKERS)


def _drop_image_parts(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """视觉模型不可用时的降级：把多模态 user 消息还原成纯文本，不丢问题。"""
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        texts = [
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        message["content"] = (
            "\n".join(t for t in texts if t).strip()
            + "\n\n（图片未能送入当前模型：请按文字问题回答，并明确说明无法读取图片内容。）"
        )
    return messages

# 只按「内置财务工具」过滤，不能把外部 MCP 工具误伤：
# `mcp__search_symbol` 之类的名字不在内置表里，若按「未登记即排除」处理，
# 所有外部只读 MCP 工具都会失效（这曾导致 test_mcp_read_tools_not_blocked 失败）。
# 执行层白名单：只允许模型实际调用「读类 + 自选维护」工具。写工具（记账/记忆/买卖/设置/
# 备份/晨报）由确定性前置分支拦截，绝不暴露给模型执行，防止 prompt 注入/幻觉越权落库。

# 通用技能包：领域无关工具（时间 / 联网搜索），供 general（非财务）分支装配。
# 这是「先 Agent 后财务」的落点：通用 Agent 内核不依赖任何财务能力。

# 通用 Agent 内核说明书（general 分支用）：领域无关的自主 agent 行为规则。


# 联网搜索开启时追加到 system 的规则（不拼进用户问题，避免污染意图路由）。
WEB_SEARCH_INSTRUCTION = (
    "用户已开启联网搜索：涉及事实、价格、政策或新闻时，先调用 web_search 核实；"
    "检索词用简短中文关键词，不要先猜公司名或型号；普通问答最多检索 1–2 次，"
    "拿到结果就直接作答，并在回答中用来源链接标注；"
    "查不到就说明查不到，不要凭记忆编造。"
)

DEEP_RESEARCH_INSTRUCTION = (
    "深度研究模式：先用 3 个不同角度各检索一次（例如政策/基本面、市场数据、风险与反方证据），"
    "再按需补充至多 3 次；最多共 6 次检索、10 轮工具调用。"
    "每次检索后先判断信息是否足够，不要只换同义词重复搜同一个问题。"
    "成文必须包含「结论」「依据」「风险与不确定性」「后续观察点」「来源」五节；"
    "来源只列工具实际返回或正文真实出现的链接，并标注发布日期（若工具结果有）。"
    "数据不足时写明缺什么，不得用常识补造数字或来源。"
)


def select_task_model(
    question: str,
    route: str | None,
    deep_research: bool,
    answer_mode: str,
    settings: dict[str, Any],
) -> str:
    """按任务难度选模型名；空字符串表示沿用主模型。

    纯函数，便于单测。只在同一端点内换模型名，不改变 base_url/key。
    """
    wants_deep = deep_research or answer_mode == "detailed" or len(question) > 500
    wants_economy = (
        not wants_deep
        and (answer_mode == "concise" or (route in ("market", "ledger") and len(question) <= 200))
    )
    key = "model_route_deep" if wants_deep else ("model_route_economy" if wants_economy else "")
    return str(settings.get(key) or "").strip() if key else ""


async def run_agent(    question: str,
    emit: Emit,
    history: list[dict[str, str]] | None = None,
    lang: str = "zh",
    *,
    system: str | None = None,
    tools_list: list | None = None,
    impl_map: dict | None = None,
    inject_memories: bool = True,
    session_context: str = "",
    deep_research: bool = False,
    llm_options: dict[str, Any] | None = None,
    images: list[dict[str, Any]] | None = None,
    route: str | None = None,
) -> dict[str, Any]:
    """跑一轮 agent：模型自主调用工具后成文。失败抛 AgentUnavailable。

    默认走财务技能包（AGENT_SYSTEM + READ_TOOLS + 长期记忆注入）；
    general 分支通过 system/tools_list/impl_map/inject_memories 装配通用技能包。
    """
    cfg = await llm._config()  # noqa: SLF001 — 同一包内复用配置读取
    if cfg is None:
        raise AgentUnavailable("未接入模型")

    web_on = "联网搜索已开启" in question
    if web_on:
        question = question.replace("\n\n［联网搜索］", "").replace("［联网搜索］", "").strip()

    # 超时走 LLM_TIMEOUT（默认 60s）：本地 CPU 模型 prefill 7k token 就要几分钟，
    # 写死 60s 会把"模型在算"误判成"模型不可用"。
    client = llm._get_client(cfg)  # noqa: SLF001 — LiteLLM 后端
    from .agent_context import build_turn_context

    messages, role_temperature, _s = await build_turn_context(
        question,
        lang=lang,
        system=system,
        inject_memories=inject_memories,
        history=history,
        cfg=cfg,
        session_context=session_context,
        images=images,
    )
    # 任务级模型路由：不是伪造 provider 参数，而是在同一端点内真的换模型名。
    # 简单问答走轻量模型，深研/长文走深度模型；留空则保持主模型。
    answer_mode = str((llm_options or {}).get("answer_mode") or "standard")
    routed_model = select_task_model(question, route, deep_research, answer_mode, _s)
    if routed_model and routed_model != str(cfg.get("model") or ""):
        cfg = dict(cfg)
        cfg["model"] = routed_model
        cfg["litellm_model"] = llm._to_litellm_model(  # noqa: SLF001 — 同包内复用 provider 前缀规则
            routed_model, str(cfg.get("provider") or ""), str(cfg.get("base") or "")
        )
    if web_on:
        messages.append({"role": "system", "content": WEB_SEARCH_INSTRUCTION})
        if deep_research:
            messages.append({"role": "system", "content": DEEP_RESEARCH_INSTRUCTION})
    # 工具轮次上限与失败反思重试（设置中心控制，默认与历史一致）
    turn_cap = max(1, min(int((_s.get("agent_tool_turns") or MAX_TURNS) or MAX_TURNS), 30))
    if deep_research:
        # 深研要给拆题、多角度检索与成文留足轮次；检索次数另有硬上限。
        turn_cap = max(turn_cap, 10)
    search_cap = 6 if deep_research else 2
    reflect = (_s.get("agent_reflect") or "on") != "off"
    # 上下文预算：按 token 而不是消息条数判断。工具结果（持仓 JSON/K 线）通常
    # 一条就上千 token，用条数判断会等到模型已经超窗才压缩。
    try:
        context_budget = int((_s.get("agent_context_tokens") or 12000) or 12000)
    except (TypeError, ValueError):
        context_budget = 12000
    context_budget = max(2000, min(context_budget, 128000))

    steps: list[dict[str, Any]] = []
    used_tools: list[str] = []
    tool_counts: dict[str, int] = {}

    # 进入循环前先按真实 token 预算压一次（历史注入可能已经很长）
    messages = await _compress_history(messages, cfg, max_tokens=context_budget)

    # 明确「本轮不给工具」：通用闲聊直接一次流式成文，跳掉工具决策轮
    #（这一轮非流式调用要等模型完整输出 tool_calls 判定，是首字延迟的主要来源）。
    # 但带图片时不走快捷路径：视觉端点报错需要经过工具循环里的「去图重试」降级。
    if tools_list is not None and len(tools_list) == 0 and not images:
        return await final_answer_result(
            client, cfg, messages, [], emit,
            steps=[], used_tools=[], tool_counts={},
        )

    from .agent_toolset import build_toolset

    tool_schemas, tool_map, internal_impl, mcp_schemas = await build_toolset(
        tools_list, impl_map, route=route
    )
    # 用户显式开启「联网搜索」：无论财务还是通用分支，都给工具面补上 web_search
    if web_on:
        names = {str((t.get("function") or {}).get("name")) for t in tool_schemas}
        if "web_search" not in names:
            from .agent_tooling import GENERAL_IMPL as _GENERAL_IMPL
            from .agent_tooling import GENERAL_TOOLS as _GENERAL_TOOLS

            web_schema = next(
                (t for t in _GENERAL_TOOLS if (t.get("function") or {}).get("name") == "web_search"),
                None,
            )
            if web_schema is not None:
                tool_schemas = tool_schemas + [web_schema]
                internal_impl["web_search"] = _GENERAL_IMPL["web_search"]
    # 小模型工具面裁剪（默认关闭）：LLM_TOOL_LIMIT>0 时按问题相关度只保留前 N 个。
    # 实测 2B 级模型在 40 个工具的 schema 下一个工具都不调，压到个位数才稳定命中。
    limit = llm_tool_limit()
    if limit and len(tool_schemas) > limit:
        kept = rank_tools(question, tool_schemas, limit)
        names = [str((s.get("function") or {}).get("name")) for s in kept]
        tool_schemas = kept
        tool_map = {k: v for k, v in tool_map.items() if k in names}
        _log.info("agent.tool_rank kept=%s of %s", names, len(tool_map))
    # 循环检测：模型有时会反复用完全相同的参数调同一个工具（尤其工具持续报错时），
    # 白烧 token 也拿不到新信息。连续 3 次完全相同则中断并如实说明。
    _guard = RepeatGuard(max_repeat=3)
    web_calls = 0
    vision_fallback = False

    for _turn in range(turn_cap):
        # 联网检索硬上限：普通问答 2 次（避免小模型反复搜拖慢首字），深研 6 次
        # （3 个角度起步，允许补搜反方证据）。到上限就从工具面摘掉 web_search，
        # 逼它用已有结果成文。
        if web_calls >= search_cap:
            before = len(tool_schemas)
            tool_schemas = [
                t
                for t in tool_schemas
                if (t.get("function") or {}).get("name") != "web_search"
            ]
            if len(tool_schemas) != before:
                _log.info("agent.web_search capped at %s calls", web_calls)
        # 首轮带图请求单独限时：不支持视觉的端点有时不报错而是长时间挂住，
        # 不设短超时会把整轮问答卡死。45 秒内没结果就按「不支持视觉」回退文字。
        vision_probe = bool(images) and _turn == 0 and not vision_fallback
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
                    # 429/5xx 由 LiteLLM 自动重试（与流式路径一致）；带图探测不重试
                    num_retries=0 if vision_probe else 2,
                    timeout=45 if vision_probe else llm.llm_timeout(),
                )
        except Exception as exc:  # noqa: BLE001 — 端点失败/不支持 tools → 降级
            if images and _turn == 0 and not vision_fallback:
                # 模型端点不接受 image_url：去掉图片重试一次，并在过程里说明，
                # 避免把「模型不支持视觉」误报成整轮问答失败。
                vision_fallback = True
                messages = _drop_image_parts(messages)
                await emit(
                    {
                        "type": "thinking",
                        "data": {
                            "content": "当前模型端点不接受图片输入，已改按文字问题回答；"
                            "如需读图，请在设置里换用支持视觉的模型。"
                        },
                        "node": "finalize",
                    }
                )
                try:
                    with timed("llm.tool_loop", model=cfg.get("model", ""), turn=_turn):
                        resp = await client.chat.completions.create(
                            model=cfg["model"] or "gpt-4o-mini",
                            messages=messages,
                            tools=tool_schemas,
                            tool_choice="auto",
                            temperature=role_temperature,
                            max_tokens=2048,
                            num_retries=2,
                            timeout=llm.llm_timeout(),
                        )
                except Exception as retry_exc:  # noqa: BLE001
                    raise AgentUnavailable(
                        f"模型调用失败：{type(retry_exc).__name__}"
                    ) from retry_exc
            else:
                raise AgentUnavailable(f"模型调用失败：{type(exc).__name__}") from exc

        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)

        if not tool_calls:
            # 有的模型会把「我先取数，稍等」当作终答：没有 tool_calls，也不再继续。
            # 若直接流式展示，用户等了半分钟只拿到一句过程承诺。检测到这种停摆，
            # 改为「禁止工具 + 直接给结论」的收尾请求，逼它把已有结果写成答案。
            if _looks_like_stall(msg.content or ""):
                _log.info("agent.stall_detected turn=%s content=%r", _turn, (msg.content or "")[:80])
                return await wrap_up_answer(
                    client, cfg, messages, emit,
                    steps=steps, max_turns=turn_cap,
                )
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
            if name == "web_search":
                # 工具面在 cap 后已摘掉 web_search，但模型可能仍按惯性调用；
                # 执行层再守一次，避免「schema 已移除、实际还在搜」。
                if web_calls >= search_cap:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": (
                                f"本轮联网检索已达上限（{search_cap} 次）。"
                                "请基于已拿到的结果成文，不要继续检索。"
                            ),
                        }
                    )
                    continue
                web_calls += 1
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
            steps.append({
                "name": name, "args": args, "summary": summary,
                "status": status, "duration_ms": duration_ms,
            })
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

        # 每轮工具结果回填后按 token 预算压缩：真正会让上下文膨胀的是 tool 结果，
        # 而不是循环开始前那一条 user 问题。压缩只动旧轮次/超长工具头部，
        # 不拆 assistant(tool_calls)→tool 配对，避免压缩后请求被端点判 400。
        messages = await _compress_history(messages, cfg, max_tokens=context_budget)

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


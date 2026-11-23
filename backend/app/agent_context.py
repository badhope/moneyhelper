"""一轮问答的上下文装配：角色温度、知识库、自定义提示词、历史、记忆与技能。

从 agent.py 的 run_agent 中抽出（原 187-281 行）。这里只做「读配置 + 拼 messages」，
不发模型请求、不执行工具，便于单独测试装配结果。
"""

from __future__ import annotations

import json
from typing import Any

from . import agent_config, db
from .logging_utils import get_logger

log = get_logger(__name__)


async def build_turn_context(
    question: str,
    *,
    lang: str,
    system: str | None,
    inject_memories: bool,
    history: list[dict[str, str]] | None,
    cfg: dict[str, Any],
    session_context: str = "",
) -> tuple[list[dict[str, Any]], float, dict[str, Any]]:
    """返回 (messages, role_temperature, settings)。"""
    from .agent import AGENT_SYSTEM  # 延迟导入：agent 模块末尾再导入本模块

    # 主角色温度：设置页「角色」里的 temperature 之前只存不用，模型永远 0.2。
    role_temperature = 0.2
    try:
        from .studio import store as studio_store

        role = (await studio_store.primary_role()).get("role") or {}
        role_temperature = float(role.get("temperature", 0.2))
        role_temperature = max(0.0, min(1.5, role_temperature))
    except Exception:  # noqa: BLE001 — 角色配置异常时回退默认温度
        role_temperature = 0.2
    # Agent 行为可配置化：工具轮次上限与失败反思重试由设置中心控制（默认与历史一致）。
    _s = await db.get_settings()
    # 知识库检索：从已入库的附件里找与问题最相关的片段，作为参考资料注入。
    # 与长期记忆分开：知识库是长文档切片，记忆是用户主动记住的短句。
    kb_context = ""
    if (_s.get("knowledge_enabled") or "on") != "off":
        try:
            from . import knowledge

            docs = await db.list_indexed_attachments()
            if docs:
                chunks: list[dict[str, Any]] = []
                for d in docs:
                    for piece in knowledge.chunk_text(str(d.get("content") or "")):
                        chunks.append({"id": d.get("id"), "filename": d.get("filename"), "content": piece})
                hits = knowledge.rank_chunks(question, chunks)
                kb_context = knowledge.build_context(hits)
        except Exception:  # noqa: BLE001 — 检索失败不影响回答
            kb_context = ""

    # 自定义提示词：设置里填了就用它覆盖内置 instructions.md（留空则用文件默认值）。
    # 只允许追加/替换「财务分支」的系统提示；通用闲聊分支不受影响。
    # Studio 提示词 / 约束 / pre_prompt Hook / 主角色指令在此叠加（scope 区分财务与科研）。
    custom_prompt = str(_s.get("custom_system_prompt") or "").strip()
    if system is not None:
        base_prompt = system
    elif custom_prompt:
        base_prompt = custom_prompt
    else:
        base_prompt = AGENT_SYSTEM
    try:
        from .studio import store as studio_store

        if inject_memories:
            system_prompt = await studio_store.build_system_prompt(base_prompt, scope="finance")
        else:
            system_prompt = base_prompt
    except Exception:  # noqa: BLE001 — Studio 配置异常不得拖垮问答
        system_prompt = base_prompt
    lang_rule = "请用简体中文回答用户的问题。" if lang == "zh" else "Answer the user in English."
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": lang_rule},
    ]
    if session_context:
        messages.append(
            {
                "role": "system",
                "content": "本会话项目卡（只作用于当前会话；不得越过安全边界）：\n"
                + str(session_context)[:2600],
            }
        )
    if kb_context:
        messages.append(
            {
                "role": "system",
                "content": (
                    "以下是从用户知识库检索到的资料片段，回答时可用作参考；"
                    "若与工具查询到的实时数据冲突，以工具结果为准。\n\n" + kb_context
                ),
            }
        )

    if history:
        messages.append(
            {
                "role": "system",
                "content": "同一会话历史（仅作上下文参考，数字一律以工具结果为准）："
                + json.dumps(history, ensure_ascii=False)[:2000],
            }
        )
    # 长期记忆预注入（用户主动要求记住的）：模型无需先调工具即可参考用户背景。
    # 仅财务分支注入（inject_memories=True）；通用 agent 分支不注入，隐私边界不变。
    # 「设置 → Agent」关闭长期记忆技能后同样不注入（技能开关真正生效）。
    long_mem_on = await agent_config.is_skill_enabled("long_memory")
    memories = await db.list_memory() if (inject_memories and long_mem_on) else []
    if memories:
        mem_text = "\n".join(f"- {m['content']}" for m in memories[:5])
        messages.append(
            {
                "role": "system",
                "content": "用户长期记忆（用户主动要求记住的，作上下文参考，需要精确数字仍以工具结果为准）：\n"
                + mem_text[:400],
            }
        )
    # 自定义技能（设置页 AI 生成并启用）：注入个性化指令，仅财务分支（通用分支保持领域无关）
    if inject_memories:
        skill_text = await agent_config.custom_skill_prompt()
        if skill_text:
            messages.append({"role": "system", "content": skill_text[:800]})
    messages.append({"role": "user", "content": question})

    return messages, role_temperature, _s

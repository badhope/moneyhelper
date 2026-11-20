"""技能定时动作执行：到点跑一遍问答管线并按技能归档。"""

from __future__ import annotations

from typing import Any

from . import db
from .logging_utils import get_logger
from .provenance import record_provenance

log = get_logger(__name__)

async def run_skill_action(skill_id: str) -> dict[str, Any]:
    """执行一次技能动作：走标准问答管线 → 归档到 thread=skill:<id>（不进会话列表）。

    供「立即触发」端点与定时任务共用；失败抛 ValueError（调用方转 400 / 记 last_error）。
    """
    from . import agent_config
    from . import service as service_mod

    cfg = await agent_config.get_config()
    skill = (cfg.get("skills") or {}).get(skill_id)
    if not isinstance(skill, dict):
        raise ValueError("技能不存在")
    if not skill.get("enabled", True):
        raise ValueError("技能已停用")
    action = agent_config.normalize_skill_action(skill.get("action"))
    if not action:
        raise ValueError("该技能没有可执行的定时动作")

    prompt = action["prompt"]
    thread_id = f"skill:{skill_id}"

    async def emit(_ev: dict[str, Any]) -> None:
        pass

    result = await service_mod.run_question(prompt, emit, thread_id=thread_id)
    await db.save_run(
        thread_id=thread_id,
        question=prompt,
        answer=result["answer"],
        level=result["level"],
        flags=result["flags"],
        route=result.get("route", ""),
        llm=result.get("llm", ""),
        route_reason=result.get("route_reason", ""),
        # 系统归档不进会话列表（与晨报一致）；历史按 thread_id 读
        skip_session=True,
    )
    # 审计链：技能触发属于"自动产生的金额相关产出"，可溯源
    try:
        await record_provenance(
            action="skill_action_fired",
            entity_type="skill",
            entity_id=skill_id,
            before=None,
            after={"thread_id": thread_id, "time": action["time"]},
            source="scheduler",
            username="system",
        )
    except Exception as exc:  # noqa: BLE001 — 审计失败不影响触发结果
        log.warning("skill action audit failed: %s", exc)
    return {
        "ok": True,
        "skill_id": skill_id,
        "thread_id": thread_id,
        "answer": result["answer"],
        "level": result["level"],
    }

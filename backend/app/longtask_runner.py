"""执行器：顺序跑未完成阶段，单段失败重试一次，全程有硬上限。

4.16.48 起阶段不是“模型回什么都算完成”：落盘前按契约校验，不合格重写一次；
成功产物写检查点；重跑上游后下游标过期，可选择只跑本段、级联重算或重算过期段。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from typing import Any

from .logging_utils import get_logger
from .longtask_checkpoints import create_checkpoint, restore_checkpoint
from .longtask_contract import (
    contract_errors_text,
    describe_contract,
    normalize_contract,
    validate_artifact,
)
from .longtask_store import _artifact_dir, _read, _write
from .longtask_tasks import _context
from .timeutil import now_str as _now

log = get_logger(__name__)


MAX_STAGE_CHARS = 12000
MAX_TOTAL_SECONDS = 3600

# 进程内后台任务登记：取消必须真正 cancel 掉正在跑的协程，而不是只改一个
# JSON 状态。否则用户点了「取消」，模型还在继续生成并消耗额度，跑完又把
# cancelled 覆盖成 done——按钮看起来存在，实际没有任何作用。
_JOBS: dict[str, asyncio.Task[Any]] = {}

TOOL_STAGE_SYSTEM = (
    "你是长任务里的阶段执行者。只能调用只读工具核实数据，绝不调用写操作；"
    "工具结果必须落进正文，数字要有出处，查不到就写查不到。"
    "只交付当前阶段成果，不要复述前文，不要寒暄，不要输出工具调用说明。"
)


def _stage_elapsed_ms(stage: dict[str, Any]) -> int:
    """按阶段开始时间算已耗时；解析失败返回 0，宁可不显示也不编造耗时。"""
    started = str(stage.get("started_at") or "")
    if not started:
        return 0
    try:
        return max(0, int((time.time() - time.mktime(time.strptime(started, "%Y-%m-%dT%H:%M:%S"))) * 1000))
    except ValueError:
        return 0


def _validate_stage_index(task: dict[str, Any], stage_index: int) -> None:
    stages = task.get("stages") or []
    if stage_index < 0 or stage_index >= len(stages):
        raise ValueError("阶段不存在")
    if stages[stage_index].get("status") == "running":
        raise ValueError("该阶段正在执行")


def _mark_active_stages_cancelled(task: dict[str, Any], message: str) -> None:
    """取消时把正在跑的阶段也落成 cancelled。

    只改任务顶层状态会让界面出现「任务已取消 / 阶段执行中」的自相矛盾状态，
    用户无法判断后台是否真的停了。
    """
    for stage in task.get("stages") or []:
        if stage.get("status") == "running":
            stage["status"] = "cancelled"
            stage["error"] = message
            stage["duration_ms"] = _stage_elapsed_ms(stage)
            stage["finished_at"] = _now()


def _mark_downstream_stale(task: dict[str, Any], from_index: int, reason: str) -> int:
    """上游产物变了：把下游已完成阶段标过期，保留旧产物供对比。"""
    marked = 0
    for stage in (task.get("stages") or [])[from_index + 1 :]:
        if stage.get("status") != "done":
            continue
        if not stage.get("stale"):
            marked += 1
        stage["stale"] = True
        stage["stale_reason"] = reason[:160]
        stage["stale_at"] = _now()
    return marked


def _clear_stale(stage: dict[str, Any]) -> None:
    stage["stale"] = False
    stage["stale_reason"] = ""
    stage["stale_at"] = ""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _artifact_digest(task: dict[str, Any], stage: dict[str, Any]) -> str:
    """取阶段当前已落盘产物的摘要；没有产物返回空串。"""
    saved = str(stage.get("artifact_sha256") or "")
    if saved:
        return saved
    name = str(stage.get("file") or "")
    if not name:
        return ""
    path = _artifact_dir(str(task["id"])) / name
    if not path.exists():
        return ""
    return _sha256_text(path.read_text(encoding="utf-8"))


def _stale_count(task: dict[str, Any]) -> int:
    return sum(1 for s in task.get("stages") or [] if s.get("stale"))


def _final_status(task: dict[str, Any]) -> str:
    stages = task.get("stages") or []
    if any(s.get("status") == "failed" for s in stages):
        return "failed"
    if any(s.get("status") in ("pending", "running") or s.get("stale") for s in stages):
        return "pending"
    return "done"


def _safe_stage_file(stage: dict[str, Any]) -> str:
    # 文件名保留中文阶段名（便于用户直接看懂产物）；只替换文件系统非法字符。
    # 注意不能用 r'[^A-Za-z0-9\\u4e00-\\u9fff]' 这种写法：正则里 \\u 是字面量，
    # 中文会被整段替换掉，产物名变成 "01--.md"（实测缺陷）。
    safe_name = re.sub(r'[\\/:*?"<>|\s]+', "-", str(stage.get("name") or "stage")).strip("-")[:40] or "stage"
    return f"{int(stage.get('index') or 0):02d}-{safe_name}.md"


def _compact_steps(steps: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for step in (steps or [])[:20]:
        args = step.get("args")
        out.append(
            {
                "name": str(step.get("name") or ""),
                "args": args if isinstance(args, dict) else {},
                "summary": str(step.get("summary") or "")[:200],
                "status": str(step.get("status") or ""),
                "duration_ms": int(step.get("duration_ms") or 0),
            }
        )
    return out


async def _run_tool_stage(
    prompt: str,
    contract: dict[str, Any],
    on_tool: Any = None,
) -> tuple[str, list[str], list[dict[str, Any]]]:
    """阶段级只读工具循环：复用主 Agent 的 function calling 内核。

    工具面由 build_toolset 按 route 收窄，且只包含 READ 档；写操作不会进入
    无人值守长任务。返回成文、工具名与真实步骤，便于界面和检查点审计。
    on_tool 在每次工具完成后被调用，用于把运行中进度落盘；回调失败不能打断
    主循环，否则一次写盘抖动会让整个阶段白跑。
    """
    from . import agent

    async def _emit(event: dict[str, Any]) -> None:
        if on_tool is None or not isinstance(event, dict):
            return
        if str(event.get("type") or "") != "tool":
            return
        try:
            await on_tool(event)
        except Exception as exc:  # noqa: BLE001 — 进度只观测，不影响执行
            log.warning("longtask.progress_failed %s", exc)

    result = await asyncio.wait_for(
        agent.run_agent(
            prompt,
            _emit,
            lang="zh",
            system=TOOL_STAGE_SYSTEM,
            inject_memories=False,
            route=contract.get("route") or None,
        ),
        timeout=600.0,
    )
    answer = str(result.get("answer") or "")
    steps = result.get("steps") if isinstance(result.get("steps"), list) else []
    used = result.get("tools_used") if isinstance(result.get("tools_used"), list) else []
    return answer, [str(x) for x in used][:20], _compact_steps(steps)


def _prompt_for_attempt(
    task: dict[str, Any],
    stage: dict[str, Any],
    contract: dict[str, Any],
    attempt: int,
    contract_errors: list[str],
    timed_out: bool,
) -> tuple[str, int]:
    limit_chars = max(100, min(int(contract["max_chars"]), MAX_STAGE_CHARS))
    if attempt == 0:
        suffix = (
            f"只输出本阶段成果，不要复述前文，不要寒暄。交付契约：{describe_contract(contract)}。"
        )
    elif contract_errors:
        suffix = (
            "上一次交付未通过契约："
            + contract_errors_text(contract_errors)
            + "。请重写完整阶段成果，不是补一段；保留正确内容并补齐缺失部分。"
            f"交付契约：{describe_contract(contract)}。"
        )
    elif timed_out:
        limit_chars = min(MAX_STAGE_CHARS // 3, max(500, contract["min_chars"]))
        suffix = (
            "上一次生成超时。请大幅压缩：只保留最核心的内容，控制在 "
            f"{limit_chars} 字以内，但必须满足：{describe_contract(contract)}。"
        )
    else:
        suffix = (
            "上一次没有产出可用内容。请直接交付完整阶段成果，不要解释过程。"
            f"交付契约：{describe_contract(contract)}。"
        )
    criteria = str(task.get("success_criteria") or "").strip()
    prompt = (
        f"任务：{task['title']}\n目标：{task['brief']}\n"
        + (f"验收标准：{criteria}\n" if criteria else "")
        + f"\n{_context(task, stage['index'])}\n\n"
        f"当前阶段：{stage['name']}\n要求：{stage['instruction']}\n\n{suffix}"
    )
    return prompt, limit_chars


async def _execute_stage(
    task: dict[str, Any],
    stage: dict[str, Any],
    contract: dict[str, Any],
    *,
    stage_started: float,
) -> tuple[str, str, list[str], list[dict[str, Any]], dict[str, Any], str]:
    """跑一个阶段，返回 (text, error, tools, steps, validation, prompt)。

    text 非空且 error 为空才算成功；失败时 text 不落盘，避免把不合格内容
    当成正式产物。
    """
    from . import llm

    text = ""
    error = ""
    tools_used: list[str] = []
    steps: list[dict[str, Any]] = []
    validation: dict[str, Any] = {"ok": False, "errors": [], "checked_at": ""}
    prompt = ""
    contract_errors: list[str] = []
    timed_out = False

    async def _on_tool(event: dict[str, Any]) -> None:
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        name = str(data.get("name") or "").strip()[:40]
        if not name:
            return
        prev = stage.get("progress") if isinstance(stage.get("progress"), dict) else {}
        n = int(prev.get("steps") or 0) + 1
        stage["progress"] = {
            "phase": "tool",
            "steps": n,
            "last_tool": name,
            "label": f"已调用 {name}（第 {n} 步）",
            "updated_at": _now(),
        }
        task["updated_at"] = _now()
        _write(task)

    # 最多两次：第二次带上一次具体违反项，要求重写完整版本；超时才压短。
    for attempt in range(2):
        stage["attempts"] = attempt + 1
        stage["progress"] = {
            "phase": "tool" if contract["use_tools"] else "generate",
            "steps": 0,
            "last_tool": "",
            "label": (
                f"工具核实中（第 {attempt + 1} 次）"
                if contract["use_tools"]
                else f"模型生成中（第 {attempt + 1} 次）"
            ),
            "updated_at": _now(),
        }
        # 尝试次数必须在调用前落盘：取消读取的是磁盘上的任务快照，
        # 只改内存会让界面在取消后显示“重试 0 次”。
        _write(task)
        prompt, limit_chars = _prompt_for_attempt(
            task, stage, contract, attempt, contract_errors, timed_out
        )
        try:
            if contract["use_tools"]:
                reply, used, tool_steps = await _run_tool_stage(prompt, contract, _on_tool)
                if used:
                    tools_used = used
                if tool_steps:
                    steps = tool_steps
            else:
                reply = await asyncio.wait_for(
                    llm.litellm_chat(
                        [
                            {
                                "role": "system",
                                "content": "你是严谨的内容生产者。只交付当前阶段成果，不编造数据与引用。",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.4,
                        timeout=540.0,
                    ),
                    # 推理型模型（reasoning tokens 可上千）单阶段实测最长 6 分钟；
                    # 420s 仍会误杀（分卷大纲阶段连续超时）。给到 9 分钟，
                    # 与任务总时长上限 1 小时配合，不会无限挂。
                    timeout=600.0,
                )
            timed_out = False
        except asyncio.TimeoutError:
            reply = None
            timed_out = True
            error = "阶段执行超时（600s）"
        except Exception as exc:  # noqa: BLE001 — 单阶段失败记录后重试
            reply = None
            timed_out = False
            error = f"{type(exc).__name__}: {exc}".strip()[:300]

        if not reply:
            contract_errors = []
            if not error:
                error = "模型返回空"
            continue

        candidate = str(reply).strip()[:limit_chars]
        errors = validate_artifact(candidate, contract)
        if errors:
            contract_errors = errors
            error = "产物未通过契约：" + contract_errors_text(errors)
            continue
        text = candidate
        error = ""
        contract_errors = []
        validation = {"ok": True, "errors": [], "checked_at": _now()}
        break

    if not text:
        validation = {"ok": False, "errors": contract_errors, "checked_at": _now()}
    return text, error, tools_used, steps, validation, prompt


async def _run_task_inner(
    task_id: str,
    *,
    max_stages: int | None = None,
    stage_index: int | None = None,
    cascade: bool = False,
    stale_only: bool = False,
) -> dict[str, Any]:
    """执行主体；由 run_task 包一层取消语义。"""
    from . import llm

    task = _read(task_id)
    if stage_index is not None:
        _validate_stage_index(task, stage_index)
    if task.get("status") == "running":
        # 能走到这里说明当前协程持有 _JOBS 执行权（run_task 已做并发守卫）。
        # 磁盘上的 running 只可能是上次进程中断留下的僵死状态；无条件把
        # running 阶段重置为 pending，不再用“10 分钟”猜是否还活着。
        for stage in task.get("stages") or []:
            if stage.get("status") == "running":
                stage["status"] = "pending"
                stage["error"] = "上次执行中断，已重置待重跑"
    if not await llm.llm_available():
        raise ValueError("尚未配置模型，无法执行长任务")

    target = task["stages"][stage_index] if stage_index is not None else None
    if stale_only:
        stages_to_run = [s for s in task["stages"] if s.get("stale")]
        if not stages_to_run:
            raise ValueError("没有过期阶段")
    elif target is not None:
        stages_to_run = task["stages"][stage_index:] if cascade else [target]
    else:
        limit = len(task["stages"]) if max_stages is None else min(max_stages, len(task["stages"]))
        stages_to_run = [
            s for s in task["stages"][:limit] if s.get("status") != "done" or s.get("stale")
        ]

    task["status"] = "running"
    task["updated_at"] = _now()
    _write(task)

    started = time.time()
    for stage in stages_to_run:
        if stale_only and not stage.get("stale"):
            continue
        if time.time() - started > MAX_TOTAL_SECONDS:
            stage["status"] = "skipped"
            stage["error"] = "超过任务总时长上限，已跳过"
            stage["progress"] = {}
            continue
        previous_status = str(stage.get("status") or "")
        previous_digest = _artifact_digest(task, stage)
        _clear_stale(stage)
        stage["status"] = "running"
        stage["started_at"] = _now()
        stage["finished_at"] = ""
        stage["error"] = ""
        stage["attempts"] = 0
        stage["duration_ms"] = 0
        stage["tools_used"] = []
        stage["tool_steps"] = []
        stage["validation"] = {}
        stage["progress"] = {}
        _write(task)
        stage_started = time.time()
        contract = normalize_contract(stage.get("contract"))
        text, error, tools_used, steps, validation, prompt = await _execute_stage(
            task, stage, contract, stage_started=stage_started
        )
        duration_ms = int((time.time() - stage_started) * 1000)
        if not text:
            stage["status"] = "failed"
            stage["error"] = (error or "模型返回空")[:300]
            stage["validation"] = validation
            stage["duration_ms"] = duration_ms
            stage["finished_at"] = _now()
            stage["progress"] = {}
            task["updated_at"] = _now()
            _write(task)
            # 阶段是顺序依赖：上游失败就停，不能拿残缺上下文继续产出下游“完成品”。
            _mark_downstream_stale(
                task, int(stage["index"]), "上一阶段执行失败，后续产物不可信，已过期"
            )
            break

        name = str(stage.get("file") or "") or _safe_stage_file(stage)
        (_artifact_dir(task_id) / name).write_text(text, encoding="utf-8")
        new_digest = _sha256_text(text)
        content_changed = bool(
            previous_status == "done"
            and new_digest
            and (not previous_digest or previous_digest != new_digest)
        )
        stage["file"] = name
        stage["chars"] = len(text)
        stage["artifact_sha256"] = new_digest
        stage["status"] = "done"
        stage["stale"] = False
        stage["stale_reason"] = ""
        stage["stale_at"] = ""
        stage["duration_ms"] = duration_ms
        stage["finished_at"] = _now()
        stage["validation"] = validation
        stage["tools_used"] = tools_used
        stage["tool_steps"] = steps
        stage["progress"] = {}
        checkpoint = create_checkpoint(
            task,
            stage,
            text,
            prompt=prompt,
            attempt=int(stage.get("attempts") or 0),
            duration_ms=duration_ms,
            tools_used=tools_used,
            steps=steps,
            source="run",
            contract_ok=True,
        )
        stage["checkpoint_id"] = str(checkpoint.get("id") or "")
        task["updated_at"] = _now()
        _write(task)
        if content_changed:
            _mark_downstream_stale(
                task,
                int(stage["index"]),
                f"上游「{stage['name']}」已重算，本段基于旧产物，需重算确认",
            )
            task["updated_at"] = _now()
            _write(task)
        elif previous_status == "done" and previous_digest:
            log.info(
                "longtask.stage_unchanged id=%s stage=%s digest=%s",
                task_id,
                stage["index"],
                new_digest[:8],
            )

    task["status"] = _final_status(task)
    task["updated_at"] = _now()
    _write(task)
    log.info("longtask.done id=%s status=%s stale=%s", task_id, task["status"], _stale_count(task))
    return task


async def start_task(
    task_id: str,
    *,
    max_stages: int | None = None,
    stage_index: int | None = None,
    cascade: bool = False,
    stale_only: bool = False,
) -> dict[str, Any]:
    """启动后台执行并立即返回当前快照，前端轮询进度。"""
    existing = _JOBS.get(task_id)
    if existing is not None and not existing.done():
        raise ValueError("任务正在执行")
    task = _read(task_id)
    if task.get("status") == "done" and stage_index is None and not stale_only:
        raise ValueError("任务已完成")
    if stage_index is not None:
        _validate_stage_index(task, stage_index)
    if stale_only and not any(s.get("stale") for s in task.get("stages") or []):
        raise ValueError("没有过期阶段")
    # 后台启动必须在这里做前置校验：否则接口返回 200，错误只出现在后台日志，
    # 任务停在 pending/running，前端永远等不到失败原因。
    from . import llm
    if not await llm.llm_available():
        raise ValueError("尚未配置模型，无法执行长任务")
    job = asyncio.create_task(
        run_task(
            task_id,
            max_stages=max_stages,
            stage_index=stage_index,
            cascade=cascade,
            stale_only=stale_only,
        )
    )
    _JOBS[task_id] = job

    def _cleanup(done: asyncio.Task[Any]) -> None:
        if _JOBS.get(task_id) is done:
            _JOBS.pop(task_id, None)
        # 后台异常必须落到日志，不能因为没人 await 就无声消失
        if not done.cancelled() and done.exception() is not None:
            err = done.exception()
            log.error("longtask.background failed id=%s err=%s", task_id, err)
            latest = _read(task_id)
            if latest.get("status") not in ("done", "cancelled"):
                latest["status"] = "failed"
                latest["error"] = str(err)[:300]
                latest["updated_at"] = _now()
                _write(latest)

    job.add_done_callback(_cleanup)
    return _read(task_id)


async def run_task(
    task_id: str,
    *,
    max_stages: int | None = None,
    stage_index: int | None = None,
    cascade: bool = False,
    stale_only: bool = False,
) -> dict[str, Any]:
    """顺序执行未完成阶段；任一段失败即停，下游保持待执行或已过期。"""
    current = asyncio.current_task()
    existing = _JOBS.get(task_id)
    if existing is not None and not existing.done() and existing is not current:
        raise ValueError("任务正在执行")
    if cascade and stale_only:
        raise ValueError("cascade 与 stale_only 不能同时使用")
    if current is not None:
        _JOBS[task_id] = current
    try:
        return await _run_task_inner(
            task_id,
            max_stages=max_stages,
            stage_index=stage_index,
            cascade=cascade,
            stale_only=stale_only,
        )
    except asyncio.CancelledError:
        latest = _read(task_id)
        if latest.get("status") != "done":
            latest["status"] = "cancelled"
            _mark_active_stages_cancelled(latest, "用户取消，当前阶段已中断")
            latest["updated_at"] = _now()
            _write(latest)
        raise
    finally:
        if _JOBS.get(task_id) is current:
            _JOBS.pop(task_id, None)


def is_active(task_id: str) -> bool:
    """该任务当前是否有后台协程在跑；供 API 区分“状态机 running”与“真在跑”。"""
    job = _JOBS.get(task_id)
    return job is not None and not job.done()


def rollback_task(task_id: str, stage_index: int, checkpoint_id: str) -> dict[str, Any]:
    """把阶段恢复到指定检查点，下游标过期；回滚前当前版本也留检查点。"""
    if is_active(task_id):
        raise ValueError("任务正在执行，不能回滚")
    task = _read(task_id)
    _validate_stage_index(task, stage_index)
    stage = task["stages"][stage_index]
    current_digest = _artifact_digest(task, stage)
    # 回滚是覆盖写：先把当前版本留一份，避免“回滚完才发现想反悔”。
    current_file = str(stage.get("file") or "")
    if stage.get("status") == "done" and current_file:
        path = _artifact_dir(task_id) / current_file
        if path.exists():
            current_text = path.read_text(encoding="utf-8")
            create_checkpoint(
                task,
                stage,
                current_text,
                prompt="回滚前自动备份",
                attempt=int(stage.get("attempts") or 0),
                duration_ms=int(stage.get("duration_ms") or 0),
                tools_used=stage.get("tools_used") if isinstance(stage.get("tools_used"), list) else [],
                steps=stage.get("tool_steps") if isinstance(stage.get("tool_steps"), list) else [],
                source="pre-rollback",
                contract_ok=bool((stage.get("validation") or {}).get("ok")),
            )
    meta, name = restore_checkpoint(task_id, stage_index, checkpoint_id)
    restored_path = _artifact_dir(task_id) / name
    restored_digest = (
        _sha256_text(restored_path.read_text(encoding="utf-8"))
        if restored_path.exists()
        else ""
    )
    stage["file"] = name
    stage["chars"] = int(meta.get("chars") or 0)
    stage["artifact_sha256"] = restored_digest
    stage["status"] = "done"
    stage["error"] = ""
    stage["stale"] = False
    stage["stale_reason"] = ""
    stage["stale_at"] = ""
    stage["progress"] = {}
    stage["attempts"] = int(meta.get("attempt") or 0)
    stage["duration_ms"] = int(meta.get("duration_ms") or 0)
    stage["finished_at"] = str(meta.get("created_at") or _now())
    stage["checkpoint_id"] = checkpoint_id
    stage["tools_used"] = meta.get("tools_used") if isinstance(meta.get("tools_used"), list) else []
    stage["tool_steps"] = meta.get("steps") if isinstance(meta.get("steps"), list) else []
    stage["validation"] = {
        "ok": True,
        "errors": [],
        "checked_at": _now(),
        "restored_from": checkpoint_id,
    }
    if current_digest != restored_digest:
        _mark_downstream_stale(
            task, stage_index, f"已回滚到检查点 {checkpoint_id}，下游需重算确认"
        )
    task["status"] = _final_status(task)
    task["updated_at"] = _now()
    _write(task)
    return task


def cancel_task(task_id: str) -> dict[str, Any]:
    task = _read(task_id)
    if task.get("status") == "done":
        raise ValueError("已完成的任务不能取消")
    task["status"] = "cancelled"
    _mark_active_stages_cancelled(task, "用户取消，当前阶段已中断")
    task["updated_at"] = _now()
    _write(task)
    job = _JOBS.get(task_id)
    if job is not None and not job.done():
        job.cancel()
    return task

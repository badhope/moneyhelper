"""执行器：顺序跑未完成阶段，单段失败重试一次，全程有硬上限。"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from .logging_utils import get_logger
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


async def start_task(
    task_id: str,
    *,
    max_stages: int | None = None,
    stage_index: int | None = None,
) -> dict[str, Any]:
    """启动后台执行并立即返回当前快照，前端轮询进度。"""
    existing = _JOBS.get(task_id)
    if existing is not None and not existing.done():
        raise ValueError("任务正在执行")
    task = _read(task_id)
    if task.get("status") == "done" and stage_index is None:
        raise ValueError("任务已完成")
    if stage_index is not None:
        _validate_stage_index(task, stage_index)
    # 后台启动必须在这里做前置校验：否则接口返回 200，错误只出现在后台日志，
    # 任务停在 pending/running，前端永远等不到失败原因。
    from . import llm
    if not await llm.llm_available():
        raise ValueError("尚未配置模型，无法执行长任务")
    job = asyncio.create_task(
        run_task(task_id, max_stages=max_stages, stage_index=stage_index)
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
    task_id: str, *, max_stages: int | None = None, stage_index: int | None = None
) -> dict[str, Any]:
    """顺序执行未完成阶段。单阶段失败不中断后续（标记 failed 并继续）。"""
    current = asyncio.current_task()
    existing = _JOBS.get(task_id)
    if existing is not None and not existing.done() and existing is not current:
        raise ValueError("任务正在执行")
    if current is not None:
        _JOBS[task_id] = current
    try:
        return await _run_task_inner(
            task_id, max_stages=max_stages, stage_index=stage_index
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


async def _run_task_inner(
    task_id: str, *, max_stages: int | None = None, stage_index: int | None = None
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

    task["status"] = "running"
    task["updated_at"] = _now()
    _write(task)

    started = time.time()
    if stage_index is not None:
        # 单阶段重跑只动目标阶段，前面已完成的产物仍作为上下文；后续阶段不重算。
        stages_to_run = [task["stages"][stage_index]]
    else:
        limit = (
            len(task["stages"])
            if max_stages is None
            else min(max_stages, len(task["stages"]))
        )
        stages_to_run = task["stages"][:limit]
    for stage in stages_to_run:
        if stage_index is None and stage["status"] == "done":
            continue
        if time.time() - started > MAX_TOTAL_SECONDS:
            stage["status"] = "skipped"
            stage["error"] = "超过任务总时长上限，已跳过"
            continue
        stage["status"] = "running"
        stage["started_at"] = _now()
        stage["finished_at"] = ""
        stage["error"] = ""
        stage["attempts"] = 0
        stage["duration_ms"] = 0
        _write(task)
        stage_error = ""
        reply: str | None = None
        stage_started = time.time()
        # 最多两次：第二次把字数上限压到 1/3。推理型模型在"写满 12000 字"的
        # 代码阶段经常超过 10 分钟（实测），压短提示词能显著提高完成率，
        # 比无限放大超时更可靠——用户宁可要一份短而完整的产出。
        for attempt in range(2):
            stage["attempts"] = attempt + 1
            # 尝试次数必须在调用前落盘：取消读取的是磁盘上的任务快照，
            # 只改内存会让界面在取消后显示“重试 0 次”。
            _write(task)
            limit_chars = MAX_STAGE_CHARS if attempt == 0 else MAX_STAGE_CHARS // 3
            suffix = (
                f"只输出本阶段成果，不要复述前文，不要寒暄。控制在 {limit_chars} 字以内。"
                if attempt == 0
                else "上一次生成超时。请大幅压缩：只保留最核心的内容，控制在 "
                f"{limit_chars} 字以内，宁可短而完整，不要长而残缺。"
            )
            criteria = str(task.get("success_criteria") or "").strip()
            prompt = (
                f"任务：{task['title']}\n目标：{task['brief']}\n"
                + (f"验收标准：{criteria}\n" if criteria else "")
                + f"\n{_context(task, stage['index'])}\n\n"
                f"当前阶段：{stage['name']}\n要求：{stage['instruction']}\n\n{suffix}"
            )
            try:
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
                if reply:
                    break
            except Exception as exc:  # noqa: BLE001 — 单阶段失败记录后重试
                reply = None
                stage_error = f"{type(exc).__name__}: {exc}".strip()
        if not reply:
            stage["status"] = "failed"
            stage["error"] = (stage_error or "模型返回空")[:300]
            stage["duration_ms"] = int((time.time() - stage_started) * 1000)
            stage["finished_at"] = _now()
            task["updated_at"] = _now()
            _write(task)
            continue
        text = reply[:MAX_STAGE_CHARS]
        # 文件名保留中文阶段名（便于用户直接看懂产物）；只替换文件系统非法字符。
        # 注意不能用 r'[^A-Za-z0-9\\u4e00-\\u9fff]' 这种写法：正则里 \\u 是字面量，
        # 中文会被整段替换掉，产物名变成 "01--.md"（实测缺陷）。
        safe_name = re.sub(r'[\\/:*?"<>|\s]+', "-", stage["name"]).strip("-")[:40] or "stage"
        name = f"{stage['index']:02d}-{safe_name}.md"
        (_artifact_dir(task_id) / name).write_text(text, encoding="utf-8")
        stage["file"] = name
        stage["chars"] = len(text)
        stage["status"] = "done"
        stage["duration_ms"] = int((time.time() - stage_started) * 1000)
        stage["finished_at"] = _now()
        task["updated_at"] = _now()
        _write(task)

    remaining = [s for s in task["stages"] if s["status"] in ("pending", "failed", "running")]
    if any(s["status"] == "failed" for s in task["stages"]):
        task["status"] = "failed"
    elif remaining:
        # 执行器已经退出，不能再显示 running：否则前端以为后台还在跑，
        # 会无限轮询；max_stages / 单阶段重跑后正确状态是 pending（待继续）。
        task["status"] = "pending"
    else:
        task["status"] = "done"
    task["updated_at"] = _now()
    _write(task)
    log.info("longtask.done id=%s status=%s", task_id, task["status"])
    return task


def is_active(task_id: str) -> bool:
    """该任务当前是否有后台协程在跑；供 API 区分“状态机 running”与“真在跑”。"""
    job = _JOBS.get(task_id)
    return job is not None and not job.done()


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

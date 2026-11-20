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


async def run_task(task_id: str, *, max_stages: int | None = None) -> dict[str, Any]:
    """顺序执行未完成阶段。单阶段失败不中断后续（标记 failed 并继续）。"""
    from . import llm

    task = _read(task_id)
    if task.get("status") == "running":
        # 进程中断会留下 running 但无进展的任务；超过 10 分钟未更新视为僵死，
        # 允许续跑（把卡住的阶段重置为 pending），否则任务永远无法恢复。
        updated = str(task.get("updated_at") or "")
        try:
            stale = (
                time.mktime(time.strptime(updated, "%Y-%m-%dT%H:%M:%S"))
                < time.time() - 600
            )
        except ValueError:
            stale = True
        if not stale:
            raise ValueError("任务正在执行")
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
    limit = len(task["stages"]) if max_stages is None else min(max_stages, len(task["stages"]))
    for stage in task["stages"][:limit]:
        if stage["status"] == "done":
            continue
        if time.time() - started > MAX_TOTAL_SECONDS:
            stage["status"] = "skipped"
            stage["error"] = "超过任务总时长上限，已跳过"
            continue
        stage["status"] = "running"
        stage["started_at"] = _now()
        _write(task)
        stage_error = ""
        reply: str | None = None
        # 最多两次：第二次把字数上限压到 1/3。推理型模型在"写满 12000 字"的
        # 代码阶段经常超过 10 分钟（实测），压短提示词能显著提高完成率，
        # 比无限放大超时更可靠——用户宁可要一份短而完整的产出。
        for attempt in range(2):
            limit_chars = MAX_STAGE_CHARS if attempt == 0 else MAX_STAGE_CHARS // 3
            suffix = (
                f"只输出本阶段成果，不要复述前文，不要寒暄。控制在 {limit_chars} 字以内。"
                if attempt == 0
                else "上一次生成超时。请大幅压缩：只保留最核心的内容，控制在 "
                f"{limit_chars} 字以内，宁可短而完整，不要长而残缺。"
            )
            prompt = (
                f"任务：{task['title']}\n目标：{task['brief']}\n\n"
                f"{_context(task, stage['index'])}\n\n"
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
        stage["finished_at"] = _now()
        task["updated_at"] = _now()
        _write(task)

    remaining = [s for s in task["stages"] if s["status"] in ("pending", "failed", "running")]
    task["status"] = "failed" if any(s["status"] == "failed" for s in task["stages"]) else (
        "running" if remaining else "done"
    )
    if not remaining:
        task["status"] = "done"
    task["updated_at"] = _now()
    _write(task)
    log.info("longtask.done id=%s status=%s", task_id, task["status"])
    return task


def cancel_task(task_id: str) -> dict[str, Any]:
    task = _read(task_id)
    if task.get("status") == "done":
        raise ValueError("已完成的任务不能取消")
    task["status"] = "cancelled"
    task["updated_at"] = _now()
    _write(task)
    return task

"""长任务执行器（切片 10）：把一次大任务拆成多个阶段，逐段执行并落盘产物。

为什么需要：
- 现有问答是「一问一答」，模型只写一段话，长文档/长程序没有地方承载；
- 用户要的是「百万字小说、完整网页、Word、论文、程序」这类多阶段产出，
  必须有：任务定义、阶段拆分、逐段执行、断点续跑、产物落盘、进度可查。

设计（最小但真实，不做假的"长任务"壳子）：
- 任务存在 data/longtasks/<id>/，含 task.json（定义+状态）与 artifacts/（产物）；
- 每个阶段调用一次模型，输入是「任务目标 + 已有产物摘要 + 本阶段要求」；
- 阶段产物写文件，失败保留已完成阶段，可重试单阶段；
- 进度按已完成阶段数实时计算，前端可轮询；
- 不自动无限跑：阶段数与单阶段字数都有上限，避免烧钱失控。

这里不做多 agent 编排——那是 agent_graph 的职责；长任务的本质是
**持久化 + 分段 + 可续跑**，用最少的代码把这三件事做对。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from .db._core import data_dir
from .logging_utils import get_logger

log = get_logger(__name__)

# 单个任务最多阶段数（防止模型生成超长阶段列表导致失控成本）
MAX_STAGES = 40
# 单阶段最多让模型写多少字（按字符计，不是 token）
MAX_STAGE_CHARS = 12000
# 任务总时长上限（秒）；超过后后续阶段标记为 skipped。
# 五个任务实测约 6 分钟/任务，单任务 1 小时上限足够且能防跑飞。
MAX_TOTAL_SECONDS = 3600


def _root() -> Path:
    path = data_dir() / "longtasks"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _task_dir(task_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{12}", task_id or ""):
        raise ValueError("任务 id 不合法")
    return _root() / task_id


def _read(task_id: str) -> dict[str, Any]:
    path = _task_dir(task_id) / "task.json"
    if not path.exists():
        raise ValueError("任务不存在")
    return json.loads(path.read_text(encoding="utf-8"))


def _write(task: dict[str, Any]) -> None:
    path = _task_dir(task["id"]) / "task.json"
    # 目录可能被外部清理（运维/测试重置）后再落盘：先补建，避免 FileNotFoundError
    # 把整个执行线程打断（实测：任务目录被删后 run_task 直接 500）。
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _artifact_dir(task_id: str) -> Path:
    path = _task_dir(task_id) / "artifacts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------------------
# 任务模板：把"用户想要的东西"翻译成可执行阶段
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, dict[str, Any]] = {
    "novel": {
        "label": "长篇小说",
        "stages": [
            ("世界观与人物", "写出故事的世界观设定、主要人物小传（每人 150 字内）、核心冲突。"),
            ("分卷大纲", "把故事拆成 5 卷，每卷写清开端、转折、高潮、结尾与字数配比。"),
            ("第一章", "按大纲写第一章正文，2500 字以上，有场景、对话与钩子。"),
            ("第二章", "承接第一章写第二章正文，2500 字以上，推进主线冲突。"),
            ("第三章", "写第三章正文，2500 字以上，制造一次反转。"),
            ("连续性检查", "检查前三章的人物、时间线、设定一致性，列出冲突并给出修订建议。"),
        ],
    },
    "webapp": {
        "label": "网页程序",
        "stages": [
            ("需求与信息架构", "写清目标用户、核心任务、页面清单与导航结构。"),
            ("数据模型与接口", "定义数据表/字段、API 契约（方法、路径、请求、响应、错误码）。"),
            ("页面骨架", "给出每个页面的 HTML 结构与关键组件拆分（可直接落地）。"),
            ("核心逻辑", "实现核心业务逻辑代码（含输入校验、错误处理），说明运行方式。"),
            ("样式与响应式", "给出 CSS（含移动端断点）与可访问性要点。"),
            ("自测清单", "列出可执行的验收步骤与边界用例，标注未实现项。"),
        ],
    },
    "docx": {
        "label": "Word 文档",
        "stages": [
            ("文档大纲", "给出标题、章节层级、每节要点与目标读者。"),
            ("正文初稿", "按大纲写完整正文，段落清晰，术语一致。"),
            ("表格与附件", "设计需要插入的表格（列名、示例行）与附录清单。"),
            ("修订说明", "列出需要人工确认的事实、数据与引用。"),
        ],
    },
    "paper": {
        "label": "学术论文",
        "stages": [
            ("研究问题与贡献", "界定研究问题、研究缺口、本文贡献（不超过 3 条）。"),
            ("文献综述", "按主题组织相关研究，指出分歧与缺口；不得编造文献。"),
            ("研究方法", "写清样本、变量、模型/实验设计、可复现步骤。"),
            ("结果", "给出结果呈现结构（表格/图）与解读要点；无数据时明确标注为待填。"),
            ("讨论与结论", "讨论结果含义、局限与未来研究方向。"),
            ("摘要与投稿检查", "写 250 字摘要与关键词，并给出格式/引用自查清单。"),
        ],
    },
    "program": {
        "label": "程序开发",
        "stages": [
            ("需求与边界", "写清功能、非功能需求、不做什么、验收标准。"),
            ("设计与接口", "模块划分、关键数据结构、对外接口与错误语义。"),
            ("核心实现", "写出可运行的核心代码，含输入校验与错误处理。"),
            ("测试", "给出单元测试与边界用例，说明如何运行。"),
            ("交付说明", "写 README：安装、运行、配置、已知限制。"),
        ],
    },
}


def list_templates() -> list[dict[str, Any]]:
    return [
        {"id": key, "label": value["label"], "stages": [s[0] for s in value["stages"]]}
        for key, value in TEMPLATES.items()
    ]


async def create_task(
    kind: str,
    title: str,
    brief: str,
    *,
    stages: list[str] | None = None,
) -> dict[str, Any]:
    """建立任务。stages 为空时按模板生成；自定义阶段最多 MAX_STAGES 个。"""
    template = TEMPLATES.get(kind)
    if template is None and not stages:
        raise ValueError(f"未知任务类型：{kind}（可选 {'/'.join(TEMPLATES)}）")
    clean_title = str(title or "").strip()[:120]
    if not clean_title:
        raise ValueError("任务标题不能为空")
    clean_brief = str(brief or "").strip()[:4000]
    if not clean_brief:
        raise ValueError("任务目标不能为空")

    if stages:
        stage_defs = [(str(s).strip()[:60], str(s).strip()[:2000]) for s in stages if str(s).strip()]
    else:
        assert template is not None
        stage_defs = list(template["stages"])
    if not stage_defs:
        raise ValueError("至少需要一个阶段")
    if len(stage_defs) > MAX_STAGES:
        raise ValueError(f"阶段数不能超过 {MAX_STAGES}")

    task_id = uuid.uuid4().hex[:12]
    task = {
        "id": task_id,
        "kind": kind,
        "title": clean_title,
        "brief": clean_brief,
        "status": "pending",  # pending/running/done/failed/cancelled
        "created_at": _now(),
        "updated_at": _now(),
        "stages": [
            {
                "index": i,
                "name": name,
                "instruction": instruction,
                "status": "pending",  # pending/running/done/failed/skipped
                "chars": 0,
                "file": "",
                "error": "",
                "started_at": "",
                "finished_at": "",
            }
            for i, (name, instruction) in enumerate(stage_defs)
        ],
    }
    _task_dir(task_id).mkdir(parents=True, exist_ok=True)
    _write(task)
    return task


def get_task(task_id: str) -> dict[str, Any]:
    return _read(task_id)


def list_tasks(limit: int = 50) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(_root().glob("*/task.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            task = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — 坏文件跳过，不影响列表
            continue
        done = sum(1 for s in task.get("stages") or [] if s.get("status") == "done")
        total = len(task.get("stages") or [])
        rows.append(
            {
                "id": task.get("id"),
                "kind": task.get("kind"),
                "title": task.get("title"),
                "status": task.get("status"),
                "done": done,
                "total": total,
                "created_at": task.get("created_at"),
                "updated_at": task.get("updated_at"),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def read_artifact(task_id: str, stage_index: int) -> str:
    task = _read(task_id)
    stages = task.get("stages") or []
    if stage_index < 0 or stage_index >= len(stages):
        raise ValueError("阶段不存在")
    name = str(stages[stage_index].get("file") or "")
    if not name:
        return ""
    path = _artifact_dir(task_id) / name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _context(task: dict[str, Any], upto: int) -> str:
    """把已完成阶段的产物压缩成上下文：只取每段前 1200 字，避免无限膨胀。"""
    parts: list[str] = []
    for stage in (task.get("stages") or [])[:upto]:
        if stage.get("status") != "done" or not stage.get("file"):
            continue
        path = _artifact_dir(task["id"]) / str(stage["file"])
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        parts.append(f"## 已完成：{stage['name']}\n{text[:1200]}")
    return "\n\n".join(parts)[-8000:]


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

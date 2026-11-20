"""任务定义与查询：建单、读单、列表、产物读取、阶段上下文。"""

from __future__ import annotations

import json
import uuid
from typing import Any

from .logging_utils import get_logger
from .longtask_store import _artifact_dir, _read, _root, _task_dir, _write
from .longtask_templates import TEMPLATES
from .timeutil import now_str as _now

log = get_logger(__name__)


MAX_STAGES = 40


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

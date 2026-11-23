"""任务定义与查询：建单、读单、列表、产物读取、阶段上下文。"""

from __future__ import annotations

import uuid
from typing import Any

from .logging_utils import get_logger
from .longtask_contract import normalize_contract
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
    stages: list[Any] | None = None,
    success_criteria: str = "",
) -> dict[str, Any]:
    """建立任务。stages 为空时按模板生成；自定义阶段最多 MAX_STAGES 个。

    自定义阶段可以是字符串，也可以是 {name, instruction, contract} 对象；
    UI 目前只传阶段名，契约走模板默认值。
    """
    template = TEMPLATES.get(kind)
    if template is None and not stages:
        raise ValueError(f"未知任务类型：{kind}（可选 {'/'.join(TEMPLATES)}）")
    clean_title = str(title or "").strip()[:120]
    if not clean_title:
        raise ValueError("任务标题不能为空")
    clean_brief = str(brief or "").strip()[:4000]
    if not clean_brief:
        raise ValueError("任务目标不能为空")
    clean_criteria = str(success_criteria or "").strip()[:1000]

    stage_defs: list[tuple[str, str, dict[str, Any]]] = []
    if stages:
        for item in stages:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()[:60]
                instruction = str(item.get("instruction") or name).strip()[:2000]
                contract = normalize_contract(item.get("contract"))
            else:
                name = str(item).strip()[:60]
                instruction = str(item).strip()[:2000]
                contract = normalize_contract(None)
            if name:
                stage_defs.append((name, instruction, contract))
    else:
        assert template is not None
        for spec in template["stages"]:
            name = str(spec[0]).strip()[:60]
            instruction = str(spec[1]).strip()[:2000]
            contract = normalize_contract(spec[2] if len(spec) > 2 else None)
            stage_defs.append((name, instruction, contract))
    if not stage_defs:
        raise ValueError("至少需要一个阶段")
    if len(stage_defs) > MAX_STAGES:
        raise ValueError(f"阶段数不能超过 {MAX_STAGES}")

    task_id = uuid.uuid4().hex[:12]
    task = {
        "id": task_id,
        "schema_version": 2,
        "kind": kind,
        "title": clean_title,
        "brief": clean_brief,
        "success_criteria": clean_criteria,
        "status": "pending",  # pending/running/done/failed/cancelled
        "created_at": _now(),
        "updated_at": _now(),
        "stages": [
            {
                "index": i,
                "name": name,
                "instruction": instruction,
                "contract": contract,
                "status": "pending",  # pending/running/done/failed/skipped
                "chars": 0,
                "file": "",
                "error": "",
                "stale": False,
                "stale_reason": "",
                "stale_at": "",
                "checkpoint_id": "",
                "tools_used": [],
                "tool_steps": [],
                "validation": {},
                "started_at": "",
                "finished_at": "",
            }
            for i, (name, instruction, contract) in enumerate(stage_defs)
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
            task = _read(path.parent.name)
        except Exception:  # noqa: BLE001 — 坏文件/坏 id 跳过，不影响列表
            continue
        done = sum(1 for s in task.get("stages") or [] if s.get("status") == "done")
        stale = sum(1 for s in task.get("stages") or [] if s.get("stale"))
        total = len(task.get("stages") or [])
        rows.append(
            {
                "id": task.get("id"),
                "kind": task.get("kind"),
                "title": task.get("title"),
                "status": task.get("status"),
                "done": done,
                "stale": stale,
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
        mark = "（此产物已过期，正在等待重算）" if stage.get("stale") else ""
        parts.append(f"## 已完成：{stage['name']}{mark}\n{text[:1200]}")
    return "\n\n".join(parts)[-8000:]

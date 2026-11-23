"""任务落盘：data/longtasks/<id>/ 的 task.json 与 artifacts 读写。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .db._core import data_dir
from .logging_utils import get_logger

log = get_logger(__name__)

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
    task = json.loads(path.read_text(encoding="utf-8"))
    _normalize_task(task)
    return task


def _normalize_task(task: dict[str, Any]) -> dict[str, Any]:
    """补齐 4.16.48/4.16.49 字段；旧任务不按新模板契约重新判失败。"""
    from .longtask_contract import normalize_contract

    task.setdefault("schema_version", 2)
    for stage in task.get("stages") or []:
        stage["contract"] = normalize_contract(stage.get("contract"))
        stage.setdefault("stale", False)
        stage.setdefault("stale_reason", "")
        stage.setdefault("stale_at", "")
        stage.setdefault("checkpoint_id", "")
        stage.setdefault("artifact_sha256", "")
        stage.setdefault("progress", {})
        stage.setdefault("tools_used", [])
        stage.setdefault("tool_steps", [])
        stage.setdefault("validation", {})
    return task



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

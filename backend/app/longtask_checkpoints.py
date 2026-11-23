"""长任务检查点：每次成功产物留一份可回滚版本。

只做 append + 限量保留，不引入数据库。检查点由两件东西组成：
  - `<id>.json`：本次执行的提示词、契约、字数、耗时、工具调用摘要；
  - `<id>.md`：当时的完整产物。

为什么产物单独存：回滚要恢复原文，而不是让模型“再写一遍”。JSON 里也存
prompt，是为了事后能判断当时到底给了模型什么上下文，而不是只看结果猜。
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .longtask_store import _artifact_dir, _task_dir

CHECKPOINT_KEEP = 6
_ID_RE = re.compile(r"[A-Za-z0-9_-]{8,40}")


def _checkpoint_root(task_id: str) -> Path:
    path = _task_dir(task_id) / "checkpoints"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _stage_dir(task_id: str, stage_index: int) -> Path:
    path = _checkpoint_root(task_id) / f"{int(stage_index):02d}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _new_id() -> str:
    # 同一秒内可能连续重跑多次；只用秒级时间会让检查点顺序不确定，
    # 回滚“最新/最旧”就可能选错。ID 带微秒，列表按 ID 排序即可稳定。
    return datetime.now().strftime("%Y%m%dT%H%M%S%f") + "-" + uuid.uuid4().hex[:4]


def create_checkpoint(
    task: dict[str, Any],
    stage: dict[str, Any],
    text: str,
    *,
    prompt: str,
    attempt: int,
    duration_ms: int,
    tools_used: list[str] | None = None,
    steps: list[dict[str, Any]] | None = None,
    source: str = "run",
    contract_ok: bool = True,
) -> dict[str, Any]:
    """写入一个成功产物检查点，返回元数据。"""
    task_id = str(task["id"])
    stage_index = int(stage["index"])
    stage_dir = _stage_dir(task_id, stage_index)
    cid = _new_id()
    artifact_name = str(stage.get("file") or f"{stage_index:02d}-stage.md")
    (stage_dir / f"{cid}.md").write_text(text, encoding="utf-8")
    meta = {
        "id": cid,
        "stage_index": stage_index,
        "stage_name": str(stage.get("name") or ""),
        "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "chars": len(text),
        "attempt": int(attempt),
        "duration_ms": int(duration_ms),
        "file": artifact_name,
        "source": source,
        "contract_ok": bool(contract_ok),
        "tools_used": [str(x) for x in (tools_used or [])][:20],
        "steps": [
            {
                "name": str(s.get("name") or ""),
                "args": s.get("args") if isinstance(s.get("args"), dict) else {},
                "summary": str(s.get("summary") or "")[:200],
                "status": str(s.get("status") or ""),
                "duration_ms": int(s.get("duration_ms") or 0),
            }
            for s in (steps or [])[:20]
        ],
        "prompt": str(prompt or "")[:12000],
    }
    (stage_dir / f"{cid}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _prune(stage_dir)
    return meta


def _prune(stage_dir: Path) -> None:
    metas = sorted(stage_dir.glob("*.json"), key=lambda p: p.name, reverse=True)
    for path in metas[CHECKPOINT_KEEP:]:
        cid = path.stem
        path.unlink(missing_ok=True)
        (stage_dir / f"{cid}.md").unlink(missing_ok=True)


def list_checkpoints(task_id: str, stage_index: int | None = None) -> list[dict[str, Any]]:
    """列检查点（新的在前）；不返回完整 prompt，避免列表接口过大。"""
    root = _checkpoint_root(task_id)
    dirs = [_stage_dir(task_id, stage_index)] if stage_index is not None else sorted(root.glob("*"))
    rows: list[dict[str, Any]] = []
    for stage_dir in dirs:
        if not stage_dir.is_dir():
            continue
        for path in sorted(stage_dir.glob("*.json"), key=lambda p: p.name, reverse=True):
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — 坏检查点不拖垮列表
                continue
            meta.pop("prompt", None)
            meta.pop("steps", None)
            rows.append(meta)
    rows.sort(key=lambda m: str(m.get("id") or ""), reverse=True)
    return rows[:50]


def read_checkpoint(task_id: str, stage_index: int, checkpoint_id: str) -> tuple[dict[str, Any], str]:
    if not _ID_RE.fullmatch(checkpoint_id or ""):
        raise ValueError("检查点不存在")
    stage_dir = _stage_dir(task_id, int(stage_index))
    meta_path = stage_dir / f"{checkpoint_id}.json"
    text_path = stage_dir / f"{checkpoint_id}.md"
    if not meta_path.exists() or not text_path.exists():
        raise ValueError("检查点不存在")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return meta, text_path.read_text(encoding="utf-8")


def restore_checkpoint(task_id: str, stage_index: int, checkpoint_id: str) -> tuple[dict[str, Any], str]:
    """把检查点产物写回当前阶段产物文件；调用方负责更新 task 状态。"""
    meta, text = read_checkpoint(task_id, stage_index, checkpoint_id)
    name = str(meta.get("file") or "").strip()
    if not re.fullmatch(r"[0-9]{2}-[^\x00/\\]{1,120}\.md", name):
        raise ValueError("检查点产物名不合法")
    path = _artifact_dir(task_id) / name
    path.write_text(text, encoding="utf-8")
    return meta, name

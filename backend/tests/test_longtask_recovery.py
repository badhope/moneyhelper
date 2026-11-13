"""长任务中断恢复：running 僵死任务可续跑，非僵死任务拒绝并发。"""

from __future__ import annotations

import json
import time

import pytest
from app import longtask


async def test_stale_running_task_is_resumable(temp_db) -> None:
    task = await longtask.create_task("program", "恢复", "x", stages=["a"])
    path = longtask._task_dir(task["id"]) / "task.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = "running"
    data["updated_at"] = "2020-01-01T00:00:00"
    data["stages"][0]["status"] = "running"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    from app import llm

    async def ok() -> bool:
        return True

    async def chat(messages, *, model=None, temperature=0.3, timeout=60.0):
        return "恢复后产物"

    original_avail, original_chat = llm.llm_available, llm.litellm_chat
    llm.llm_available, llm.litellm_chat = ok, chat
    try:
        out = await longtask.run_task(task["id"])
    finally:
        llm.llm_available, llm.litellm_chat = original_avail, original_chat
    assert out["stages"][0]["status"] == "done"


async def test_fresh_running_task_rejects_second_run(temp_db) -> None:
    task = await longtask.create_task("program", "并发", "x", stages=["a"])
    path = longtask._task_dir(task["id"]) / "task.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = "running"
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="正在执行"):
        await longtask.run_task(task["id"])

"""长任务中断恢复：磁盘 running 无协程可续跑，真正并发由 _JOBS 拒绝。"""

from __future__ import annotations

import json

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


async def test_fresh_running_without_job_is_recovered(temp_db, monkeypatch) -> None:
    """磁盘刚写 running 但没有协程：应恢复执行，而不是误报“正在执行”。"""
    from app import llm

    task = await longtask.create_task("program", "并发", "x", stages=["a"])
    path = longtask._task_dir(task["id"]) / "task.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = "running"
    data["stages"][0]["status"] = "running"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    async def ok() -> bool:
        return True

    async def chat(messages, *, model=None, temperature=0.3, timeout=60.0):
        return "恢复成功"

    monkeypatch.setattr(llm, "llm_available", ok)
    monkeypatch.setattr(llm, "litellm_chat", chat)
    out = await longtask.run_task(task["id"])
    assert out["status"] == "done"
    assert out["stages"][0]["status"] == "done"

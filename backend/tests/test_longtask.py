"""长任务执行器（切片 10）：分段执行、断点续跑、产物落盘。

判据全部是可观测结果：产物文件存在、字数达标、阶段状态正确、失败可续跑。
不 mock 文件系统，落盘到临时数据目录。
"""

from __future__ import annotations

import pytest
from app import longtask


@pytest.fixture(autouse=True)
async def _data_dir(temp_db):
    """temp_db 已把 DB_PATH 指到 tmp；长任务目录跟随 data_dir()。"""
    yield


def test_templates_cover_five_task_types() -> None:
    ids = {t["id"] for t in longtask.list_templates()}
    assert {"novel", "webapp", "docx", "paper", "program"} <= ids
    for tpl in longtask.list_templates():
        assert tpl["stages"], "每个模板都要有阶段"


async def test_create_task_generates_stages() -> None:
    task = await longtask.create_task("novel", "测试小说", "写一个关于时间循环的故事")
    assert task["status"] == "pending"
    assert len(task["stages"]) >= 5
    assert task["stages"][0]["status"] == "pending"
    # 落盘可读回
    again = longtask.get_task(task["id"])
    assert again["title"] == "测试小说"


async def test_create_task_rejects_empty_fields() -> None:
    with pytest.raises(ValueError):
        await longtask.create_task("novel", "", "x")
    with pytest.raises(ValueError):
        await longtask.create_task("novel", "标题", "")
    with pytest.raises(ValueError):
        await longtask.create_task("不存在的类型", "标题", "目标")


async def test_custom_stages_and_limit() -> None:
    task = await longtask.create_task(
        "program", "自定义", "做一个 CLI", stages=["设计", "实现", "测试"]
    )
    assert [s["name"] for s in task["stages"]] == ["设计", "实现", "测试"]

    with pytest.raises(ValueError):
        await longtask.create_task(
            "program", "太多", "x", stages=[f"s{i}" for i in range(longtask.MAX_STAGES + 1)]
        )


async def test_run_task_writes_artifacts(monkeypatch) -> None:
    """模型按阶段返回内容时，每阶段落盘一个文件且计入字数。"""
    from app import llm

    async def fake_available() -> bool:
        return True

    calls: list[str] = []

    async def fake_chat(messages, *, model=None, temperature=0.3, timeout=60.0):
        prompt = messages[-1]["content"]
        calls.append(prompt)
        return "阶段成果：" + prompt.split("当前阶段：")[-1][:20]

    monkeypatch.setattr(llm, "llm_available", fake_available)
    monkeypatch.setattr(llm, "litellm_chat", fake_chat)

    task = await longtask.create_task(
        "program", "跑通", "做一个计数器", stages=["设计", "实现"]
    )
    done = await longtask.run_task(task["id"])
    assert done["status"] == "done"
    assert all(s["status"] == "done" for s in done["stages"])
    assert len(calls) == 2
    for i, stage in enumerate(done["stages"]):
        content = longtask.read_artifact(task["id"], i)
        assert content.startswith("阶段成果：")
        assert stage["chars"] == len(content)
        assert stage["file"].startswith(f"{i:02d}-")


async def test_stage_failure_is_recorded_and_resumable(monkeypatch) -> None:
    """单阶段失败标记 failed，其余继续；再跑一次只补失败阶段。"""
    from app import llm

    async def fake_available() -> bool:
        return True

    state = {"n": 0}

    async def flaky_chat(messages, *, model=None, temperature=0.3, timeout=60.0):
        state["n"] += 1
        if state["n"] <= 2:
            # 阶段内最多重试一次：两次都失败才算阶段失败
            return None
        return "补跑成功"

    monkeypatch.setattr(llm, "llm_available", fake_available)
    monkeypatch.setattr(llm, "litellm_chat", flaky_chat)

    task = await longtask.create_task(
        "program", "续跑", "x", stages=["第一阶段", "第二阶段"]
    )
    first = await longtask.run_task(task["id"])
    assert first["stages"][0]["status"] == "failed"
    assert first["stages"][1]["status"] == "done"
    assert first["status"] == "failed"

    second = await longtask.run_task(task["id"])
    assert second["stages"][0]["status"] == "done"
    assert second["status"] == "done"


async def test_run_requires_model(monkeypatch) -> None:
    from app import llm

    async def no_model() -> bool:
        return False

    monkeypatch.setattr(llm, "llm_available", no_model)
    task = await longtask.create_task("program", "无模型", "x", stages=["a"])
    with pytest.raises(ValueError, match="尚未配置模型"):
        await longtask.run_task(task["id"])


async def test_max_stages_limits_one_run(monkeypatch) -> None:
    """max_stages 只跑前 N 个阶段，其余保持 pending（用于控制单次成本）。"""
    from app import llm

    async def fake_available() -> bool:
        return True

    async def fake_chat(messages, *, model=None, temperature=0.3, timeout=60.0):
        return "ok"

    monkeypatch.setattr(llm, "llm_available", fake_available)
    monkeypatch.setattr(llm, "litellm_chat", fake_chat)
    task = await longtask.create_task(
        "program", "限流", "x", stages=["a", "b", "c"]
    )
    out = await longtask.run_task(task["id"], max_stages=1)
    assert out["stages"][0]["status"] == "done"
    assert out["stages"][1]["status"] == "pending"
    assert out["status"] == "running"


async def test_cancel_task() -> None:
    task = await longtask.create_task("program", "取消", "x", stages=["a"])
    out = longtask.cancel_task(task["id"])
    assert out["status"] == "cancelled"


async def test_list_tasks_reports_progress() -> None:
    await longtask.create_task("program", "列表一", "x", stages=["a", "b"])
    rows = longtask.list_tasks()
    assert rows
    assert rows[0]["total"] == 2
    assert "done" in rows[0]

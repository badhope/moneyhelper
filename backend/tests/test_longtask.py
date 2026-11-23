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
        assert stage["attempts"] == 1
        assert stage["duration_ms"] >= 0


async def test_stage_failure_is_recorded_and_resumable(monkeypatch) -> None:
    """单阶段失败标记 failed，下游不再带病执行；补跑成功后继续。"""
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
    assert first["stages"][0]["attempts"] == 2
    assert first["stages"][0]["duration_ms"] >= 0
    assert first["stages"][1]["status"] == "pending"
    assert first["status"] == "failed"

    second = await longtask.run_task(task["id"])
    assert second["stages"][0]["status"] == "done"
    # 第二阶段从未在失败上下文里跑过；补跑时按顺序一起完成。
    assert second["stages"][1]["status"] == "done"
    assert second["status"] == "done"
    assert state["n"] == 4


async def test_run_requires_model(monkeypatch) -> None:
    from app import llm

    async def no_model() -> bool:
        return False

    monkeypatch.setattr(llm, "llm_available", no_model)
    task = await longtask.create_task("program", "无模型", "x", stages=["a"])
    with pytest.raises(ValueError, match="尚未配置模型"):
        await longtask.run_task(task["id"])


async def test_rerun_single_stage_keeps_other_artifacts(monkeypatch) -> None:
    """单阶段重跑只重算目标阶段，其他已完成阶段与其产物保持不动。"""
    from app import llm

    async def fake_available() -> bool:
        return True

    state = {"n": 0}

    async def fake_chat(messages, *, model=None, temperature=0.3, timeout=60.0):
        state["n"] += 1
        return f"第 {state['n']} 次生成"

    monkeypatch.setattr(llm, "llm_available", fake_available)
    monkeypatch.setattr(llm, "litellm_chat", fake_chat)
    task = await longtask.create_task(
        "program", "单阶段重跑", "x", stages=["甲", "乙"]
    )
    first = await longtask.run_task(task["id"])
    assert first["status"] == "done"
    old_second = longtask.read_artifact(task["id"], 1)

    rerun = await longtask.run_task(task["id"], stage_index=0)
    assert state["n"] == 3, "只应新增一次模型调用"
    assert rerun["stages"][0]["chars"] == len("第 3 次生成")
    assert longtask.read_artifact(task["id"], 1) == old_second
    # 产物还在，但下游已过期，任务不能显示全绿。
    assert rerun["stages"][1]["stale"] is True
    assert rerun["status"] == "pending"
    with pytest.raises(ValueError, match="阶段不存在"):
        await longtask.run_task(task["id"], stage_index=9)


async def test_stale_running_is_reported_pending_without_job() -> None:
    """进程重启后磁盘残留 running、但没有后台协程：API 必须归一为 pending。"""
    from app.routes.longtask import _decorate_task

    task = await longtask.create_task("program", "僵死状态", "x", stages=["a"])
    task["status"] = "running"
    task["stages"][0]["status"] = "running"
    longtask._write(task)
    decorated = _decorate_task(longtask.get_task(task["id"]))
    assert decorated["active"] is False
    assert decorated["status"] == "pending"


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
    assert out["status"] == "pending", "执行器结束后不应继续显示 running"


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


async def test_contract_retry_and_reject(monkeypatch) -> None:
    """产物不合格先带违反项重写；两次都不合格落 failed，不把短稿标 done。"""
    from app import llm

    async def fake_available() -> bool:
        return True

    long_body = (
        "世界观：一个被海水包围的城邦。\n"
        + "人物：主角是普通大学生，靠修理旧机器换口粮。\n"
        + "核心冲突：城邦的潮汐规则正在失效。\n"
        + ("补充设定与冲突细节。" * 40)
    )
    state = {"n": 0}

    async def fake_chat(messages, *, model=None, temperature=0.3, timeout=60.0):
        state["n"] += 1
        # 第一段任务第一次返回过短；第二次补全。第二段任务永远返回过短。
        if state["n"] in (1, 3, 4):
            return "太短"
        return long_body

    monkeypatch.setattr(llm, "llm_available", fake_available)
    monkeypatch.setattr(llm, "litellm_chat", fake_chat)

    task = await longtask.create_task("novel", "契约重试", "x")
    out = await longtask.run_task(task["id"], max_stages=1)
    assert out["stages"][0]["status"] == "done"
    assert out["stages"][0]["attempts"] == 2
    assert out["stages"][0]["validation"]["ok"] is True
    assert out["status"] == "pending"

    bad = await longtask.create_task("novel", "契约拒绝", "x")
    bad_out = await longtask.run_task(bad["id"], max_stages=1)
    assert bad_out["stages"][0]["status"] == "failed"
    assert "字数不足" in bad_out["stages"][0]["error"]
    assert bad_out["stages"][0]["file"] == ""
    assert bad_out["status"] == "failed"


async def test_checkpoint_rollback_restores_artifact_and_marks_downstream(monkeypatch) -> None:
    from app import llm

    async def fake_available() -> bool:
        return True

    state = {"n": 0}

    async def fake_chat(messages, *, model=None, temperature=0.3, timeout=60.0):
        state["n"] += 1
        return f"第 {state['n']} 次生成"

    monkeypatch.setattr(llm, "llm_available", fake_available)
    monkeypatch.setattr(llm, "litellm_chat", fake_chat)
    task = await longtask.create_task("program", "回滚", "x", stages=["甲", "乙"])
    await longtask.run_task(task["id"])
    assert len(longtask.list_checkpoints(task["id"], 0)) == 1

    await longtask.run_task(task["id"], stage_index=0)
    cps = longtask.list_checkpoints(task["id"], 0)
    assert len(cps) == 2
    oldest = cps[-1]
    rolled = longtask.rollback_task(task["id"], 0, oldest["id"])
    assert longtask.read_artifact(task["id"], 0) == "第 1 次生成"
    assert rolled["stages"][0]["checkpoint_id"] == oldest["id"]
    assert rolled["stages"][1]["stale"] is True
    assert rolled["status"] == "pending"
    # 回滚前当前版本被自动备份，避免“回滚完才发现想反悔”。
    assert len(longtask.list_checkpoints(task["id"], 0)) == 3


async def test_cascade_reruns_downstream(monkeypatch) -> None:
    from app import llm

    async def fake_available() -> bool:
        return True

    state = {"n": 0}

    async def fake_chat(messages, *, model=None, temperature=0.3, timeout=60.0):
        state["n"] += 1
        return f"版本{state['n']}"

    monkeypatch.setattr(llm, "llm_available", fake_available)
    monkeypatch.setattr(llm, "litellm_chat", fake_chat)
    task = await longtask.create_task("program", "级联", "x", stages=["a", "b", "c"])
    await longtask.run_task(task["id"])
    out = await longtask.run_task(task["id"], stage_index=0, cascade=True)
    assert state["n"] == 6, "首轮 3 段 + 级联 3 段"
    assert out["status"] == "done"
    assert all(s["stale"] is False for s in out["stages"])
    assert [longtask.read_artifact(task["id"], i) for i in range(3)] == ["版本4", "版本5", "版本6"]


async def test_tool_stage_records_real_tool_steps(monkeypatch) -> None:
    """投研阶段走只读工具循环；工具名和步骤来自真实回包，不是写死的 UI 文案。"""
    from app import agent, llm

    async def fake_available() -> bool:
        return True

    async def fake_run_agent(question, emit, **kwargs):
        return {
            "answer": (
                "数据：净资产与月度收支来自本地账本。\n"
                "口径：金额为人民币，时间为最近一个完整月份。\n"
                + ("风险与边界说明。" * 60)
            ),
            "steps": [
                {
                    "name": "get_ledger_view",
                    "args": {"month": "2026-10"},
                    "summary": "收入 1,000、支出 800",
                    "status": "done",
                    "duration_ms": 120,
                }
            ],
            "tools_used": ["get_ledger_view"],
        }

    monkeypatch.setattr(llm, "llm_available", fake_available)
    monkeypatch.setattr(agent, "run_agent", fake_run_agent)
    task = await longtask.create_task("research", "工具阶段", "x")
    out = await longtask.run_task(task["id"], max_stages=1)
    stage = out["stages"][0]
    assert stage["status"] == "done"
    assert stage["tools_used"] == ["get_ledger_view"]
    assert stage["tool_steps"][0]["name"] == "get_ledger_view"
    assert stage["tool_steps"][0]["status"] == "done"

"""财务目标 / 长期记忆 / 财务体检：API 集成 + 工具执行体 + 纯函数。

覆盖：goals CRUD（含校验）、goal_progress 建议月存、memory 去重/删除/清空、
health-check 五维报告、agent 新工具（get_goals / save_user_memory / get_user_memory / get_health_check）。
"""

from __future__ import annotations

from typing import Any

import pytest
from app import analysis, db, tools
from app import quotes as quotes_mod


@pytest.fixture(autouse=True)
async def _auto_temp_db(temp_db):
    """保持原文件的 autouse 语义：本文件每个用例都跑在临时库上。

    `_temp_db` 转发版已收敛到 conftest；此处只保留「自动生效」这一行为差异。
    """
    yield


@pytest.fixture
async def client(_temp_db, monkeypatch):
    from app import main

    async def _snap(positions):
        return {p["symbol"]: float(p["last"]) for p in positions}

    monkeypatch.setattr(quotes_mod, "live_quotes", _snap)
    import httpx

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1:8787"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# 目标 CRUD + 进度
# ---------------------------------------------------------------------------


async def test_goal_crud(client) -> None:
    r = await client.post(
        "/api/goals",
        json={"name": "买房首付", "target": 200000, "saved": 50000, "deadline": "2027-06"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r = await client.get("/api/goals")
    goals = r.json()["goals"]
    assert len(goals) == 1
    g = goals[0]
    assert g["name"] == "买房首付"
    assert g["pct"] == 25.0
    assert g["monthly_suggest"] > 0, "应按剩余月数给出建议月存"

    r = await client.put("/api/goals/买房首付", json={"saved": 100000})
    assert r.status_code == 200
    g = (await client.get("/api/goals")).json()["goals"][0]
    assert g["pct"] == 50.0

    r = await client.delete("/api/goals/买房首付")
    assert r.json()["deleted"] == 1
    assert (await client.get("/api/goals")).json()["goals"] == []


async def test_goal_validation(client) -> None:
    r = await client.post("/api/goals", json={"name": "坏目标", "target": -1})
    assert r.status_code == 400
    r = await client.post("/api/goals", json={"name": "", "target": 100})
    assert r.status_code == 400
    r = await client.put("/api/goals/不存在", json={"saved": 1})
    assert r.status_code == 400


def test_goal_progress_monthly_suggest() -> None:
    now_goals = [{"name": "存款", "target": 12000, "saved": 0, "deadline": "2026-12"}]
    out = analysis.goal_progress(now_goals)
    assert out[0]["done"] is False
    assert out[0]["monthly_suggest"] > 0
    done = [{"name": "达成", "target": 100, "saved": 100, "deadline": ""}]
    assert analysis.goal_progress(done)[0]["done"] is True


# ---------------------------------------------------------------------------
# 长期记忆 CRUD + 去重
# ---------------------------------------------------------------------------


async def test_memory_crud_and_dedup(client) -> None:
    r = await client.post("/api/memory", json={"content": "明年计划买房"})
    assert r.status_code == 200
    mem_id = r.json()["id"]
    # 相同内容 → 去重（不新增）
    r2 = await client.post("/api/memory", json={"content": "明年计划买房"})
    assert r2.json()["deduped"] is True
    assert r2.json()["id"] == mem_id

    lst = (await client.get("/api/memory")).json()["memory"]
    assert len(lst) == 1 and lst[0]["content"] == "明年计划买房"

    r = await client.delete(f"/api/memory/{mem_id}")
    assert r.json()["deleted"] == 1
    assert (await client.get("/api/memory")).json()["memory"] == []


async def test_memory_clear(client) -> None:
    await client.post("/api/memory", json={"content": "有一条记忆"})
    r = await client.post("/api/memory/clear")
    assert r.json()["deleted"] == 1
    assert (await client.get("/api/memory")).json()["memory"] == []


# ---------------------------------------------------------------------------
# 财务体检
# ---------------------------------------------------------------------------


async def test_health_check_endpoint(client) -> None:
    r = await client.get("/api/health-check")
    assert r.status_code == 200
    d = r.json()
    assert "score" in d and "dimensions" in d and "summary" in d
    keys = {x["key"] for x in d["dimensions"]}
    # 示例数据包含持仓/流水/负债/目标 → 至少覆盖配置与现金流两个维度
    assert {"portfolio", "cashflow"} <= keys
    for dim in d["dimensions"]:
        assert dim["status"] in ("good", "warn", "bad")
        assert dim["title"] and dim["detail"]


# ---------------------------------------------------------------------------
# agent 工具执行体
# ---------------------------------------------------------------------------


async def test_tool_get_goals(_temp_db) -> None:
    await db.add_goal({"name": "买车", "target": 50000, "saved": 10000})
    out = await tools.tool_get_goals({})
    assert '"买车"' in out and '"pct": 20.0' in out
    assert "empty" not in out


async def test_tool_memory_save_and_get(_temp_db) -> None:
    out = await tools.tool_save_user_memory({"content": "每月收入 2 万"})
    assert '"ok": true' in out and '"deduped": false' in out
    out2 = await tools.tool_save_user_memory({"content": "每月收入 2 万"})
    assert '"deduped": true' in out2
    got = await tools.tool_get_user_memory({})
    assert "每月收入 2 万" in got
    bad = await tools.tool_save_user_memory({})
    assert "缺少 content" in bad


async def test_tool_health_check(_temp_db, monkeypatch) -> None:
    async def _snap(positions):
        return {p["symbol"]: float(p["last"]) for p in positions}

    monkeypatch.setattr(quotes_mod, "live_quotes", _snap)
    out = await tools.tool_get_health_check({})
    assert '"score"' in out and '"dimensions"' in out


# ---------------------------------------------------------------------------
# 查漏补缺：路由新词 / 记忆指令 / 体检确定性输出 / 备份恢复覆盖 / 工具摘要
# ---------------------------------------------------------------------------


async def test_route_goal_words() -> None:
    """目标/体检关键词路由到 goal（全量财务）；宽泛「目标」不误伤，非财务仍 general。"""
    from app import service

    for q in ("帮我体检一下", "我存够了吗", "攒钱买房", "还差多少能买房", "给点建议月存"):
        r, _ = service.route_question(q)
        assert r == "goal", f"{q} → {r}"
    r, _ = service.route_question("人生目标是什么")
    assert r == "general"
    r, _ = service.route_question("帮我写个周报")
    assert r == "general"


async def test_route_ledger_colloquialisms() -> None:
    """口语化的收支说法必须路由到账本（而非被判成普通闲聊）。

    回归：此前 LEDGER_WORDS 只收「支出」，「这个月的开销怎么样」被判 general，
    回答变成"未接入模型"的兜底文案，用户看起来像功能坏了。
    """
    from app import service

    for q in (
        "这个月的开销怎么样",
        "本月开支多少",
        "最近花费大吗",
        "我这个月花了多少",
        "每月消费多少",
    ):
        r, _ = service.route_question(q)
        assert r == "ledger", f"{q} → {r}"


async def test_route_reason_follows_language() -> None:
    """route_reason（推理轨迹展示文本）按 lang 本地化：en 界面不再出现中文路由描述。"""
    from app import service

    zh_examples = ("帮我体检一下", "我的持仓怎么样了", "我这个月花了多少", "卖出 600519", "随便聊聊")
    for q in zh_examples:
        zh_route, zh_reason = service.route_question(q, "zh")
        en_route, en_reason = service.route_question(q, "en")
        assert zh_route == en_route, f"route 不应随语言变化: {q}"
        assert zh_reason != en_reason, f"zh/en reason 应不同: {q}"
        assert any("\u4e00" <= ch <= "\u9fff" for ch in zh_reason), f"zh reason 应为中文: {q}"
        assert not any("\u4e00" <= ch <= "\u9fff" for ch in en_reason), f"en reason 不应含中文: {q}"


async def test_memory_answer_follows_language(_temp_db, monkeypatch) -> None:
    """记忆回执 answer 与 route_reason 按 lang 本地化；en 界面不得出现中文回执。"""
    from app import service

    async def _no_llm() -> bool:
        return False

    monkeypatch.setattr(service.llm, "llm_available", _no_llm)

    async def emit(_ev: dict[str, Any]) -> None:
        return None

    out = await service._try_save_memory("记住我明年计划买房", emit, "en")
    assert out is not None
    assert out["route_reason"] == "Recognized as a memory instruction — saved directly to long-term memory"
    assert "I've remembered" in out["answer"]
    assert "以后" not in out["answer"]


async def _run_graph_collect(run: Any, question: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    events: list[dict[str, Any]] = []

    async def emit(ev: dict[str, Any]) -> None:
        events.append(ev)

    result = await run(question, emit)
    return events, result


async def test_memory_instruction_via_graph(_temp_db, monkeypatch) -> None:
    """「记住…」指令走记忆 agent 支路：确定性存库 + 回执（无需模型）。"""
    from app import service

    async def _no_llm() -> bool:
        return False

    monkeypatch.setattr(service.llm, "llm_available", _no_llm)
    events, result = await _run_graph_collect(service.run_question, "记住我明年计划买房")
    assert result["route"] == "memory"
    assert result["llm"] == "template"
    assert "记住了" in result["answer"]
    mem = await db.list_memory()
    assert len(mem) == 1 and "明年计划买房" in mem[0]["content"]
    steps = [e for e in events if e["type"] == "step" and e["phase"] == "done"]
    assert any(s["id"] == "memory" for s in steps)
    # 重复指令 → 去重不新增
    await _run_graph_collect(service.run_question, "记住我明年计划买房")
    assert len(await db.list_memory()) == 1


async def test_memory_question_not_recorded(_temp_db, monkeypatch) -> None:
    """疑问句（「你还记得吗」）不当记忆指令，走通用支路。"""
    from app import service

    async def _no_llm() -> bool:
        return False

    monkeypatch.setattr(service.llm, "llm_available", _no_llm)
    _, result = await _run_graph_collect(service.run_question, "你还记得我的生日吗")
    assert result["route"] == "general"
    assert await db.list_memory() == []


async def test_health_check_deterministic_output(_temp_db, monkeypatch) -> None:
    """无模型时「帮我体检」也输出五维报告（确定性内核）。"""
    from app import service

    async def _no_llm() -> bool:
        return False

    monkeypatch.setattr(service.llm, "llm_available", _no_llm)
    events, result = await _run_graph_collect(service.run_question, "帮我体检一下")
    assert result["llm"] == "template"
    assert result["route"] == "goal"
    assert "综合评分" in result["answer"]
    assert "资产配置" in result["answer"]
    steps = [e for e in events if e["type"] == "step" and e["phase"] == "done"]
    assert next(s["id"] for s in steps) == "supervisor"
    assert "market" in [s["id"] for s in steps] and "ledger" in [s["id"] for s in steps]


async def test_backup_roundtrip_covers_goals_memory(client) -> None:
    """备份导出/恢复覆盖目标与长期记忆两表。"""
    await client.post("/api/goals", json={"name": "应急金", "target": 100000, "saved": 20000})
    await client.post("/api/memory", json={"content": "明年计划买房"})
    backup = (await client.get("/api/export")).json()
    assert len(backup["goals"]) == 1 and len(backup["memory"]) == 1

    # 清空两表后恢复
    await db.execute("DELETE FROM goals")
    await db.execute("DELETE FROM user_memory")
    r = await client.post("/api/import/backup", json=backup)
    assert r.status_code == 200
    assert (await client.get("/api/goals")).json()["goals"][0]["pct"] == 20.0
    mem = (await client.get("/api/memory")).json()["memory"]
    assert len(mem) == 1 and mem[0]["content"] == "明年计划买房"


async def test_tool_summary_new_tools(_temp_db) -> None:
    """新工具的前端摘要：目标进度 / 记忆 / 体检可读。"""
    from app import agent as agent_mod

    await db.add_goal({"name": "买车", "target": 50000, "saved": 10000})
    s = agent_mod._tool_summary("get_goals", await tools.tool_get_goals({}))
    assert "买车" in s and "20.0%" in s
    s = agent_mod._tool_summary("get_user_memory", '{"empty": true}')
    assert "暂无长期记忆" in s
    s = agent_mod._tool_summary("save_user_memory", '{"ok": true}')
    assert "已记住" in s
    s = agent_mod._tool_summary("get_health_check", '{"score": 80, "summary": "整体健康"}')
    assert "80" in s and "整体健康" in s


async def test_health_check_empty_data_score(_temp_db, monkeypatch) -> None:
    """空库体检不得报「整体健康 100 分」：图走记账引导，纯函数 score 0 + 数据不足提示。"""
    from app import service

    async def _no_llm() -> bool:
        return False

    monkeypatch.setattr(service.llm, "llm_available", _no_llm)
    # 清空全部业务数据（持仓/流水/负债/订阅/目标）
    for t in ("positions", "transactions", "debts", "subscriptions", "goals"):
        await db.execute(f"DELETE FROM {t}")
    _events, result = await _run_graph_collect(service.run_question, "帮我体检一下")
    assert "综合评分" not in result["answer"], "空库不应给出分数体检报告"
    report = analysis.health_check(None, None, [], [])
    assert report["score"] == 0 and "数据不足" in report["summary"]

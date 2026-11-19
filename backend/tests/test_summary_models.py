"""P0：长会话摘要压缩 + 模型点亮。

覆盖：
- 会话轮次超阈值时触发压缩、落库、增量续写、未超阈值不写；
- 无模型时启发式摘要兜底，且 _build_history 注入摘要 + 保留最近轮次；
- 模型目录与 enabled_models 的读写校验（put_settings / bootstrap）。
"""

from __future__ import annotations

import pytest
from app import db, llm, main, service, tools
from app.routes.settings import put_settings


@pytest.fixture(autouse=True)
async def _auto_temp_db(temp_db):
    """保持原文件的 autouse 语义：本文件每个用例都跑在临时库上。"""
    yield



async def _seed_runs(thread: str, n: int) -> None:
    for i in range(n):
        await db.save_run(
            thread,
            f"问题{i}：本月花了多少",
            f"回答{i}：本月支出 5000 元，结余 20000 元",
            "L1 洞察",
            route="ledger",
            skip_session=False,
        )


@pytest.fixture
async def client(_temp_db, monkeypatch):
    """模拟 quotes 快照 + 借出 ASGI client（供中间件审计测试）。"""
    from app import main
    from app import quotes as quotes_mod

    async def _snap(positions):
        return {p["symbol"]: float(p["last"]) for p in positions}

    monkeypatch.setattr(quotes_mod, "live_quotes", _snap)
    import httpx

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac


async def _no_llm() -> bool:
    return False


# ---------------------------------------------------------------------------
# 长会话摘要压缩（无模型 → 启发式）
# ---------------------------------------------------------------------------


async def test_no_summary_below_threshold(_temp_db, monkeypatch) -> None:
    """轮次未超阈值：不触发压缩，也无摘要。"""
    monkeypatch.setattr(service.llm, "llm_available", _no_llm)
    await _seed_runs("t1", 5)  # 5 轮 < 8
    assert await service.ensure_session_summary("t1") is None
    assert await db.get_conversation_summary("t1") is None


async def test_heuristic_summary_above_threshold(_temp_db, monkeypatch) -> None:
    """轮次超阈值：无模型时生成启发式摘要并落库；摘要覆盖旧轮、保留最近轮。"""
    monkeypatch.setattr(service.llm, "llm_available", _no_llm)
    await _seed_runs("t1", 10)
    out = await service.ensure_session_summary("t1")
    assert out is not None and out["source"] == "heuristic" and out["covered_to"] > 0
    summary = await db.get_conversation_summary("t1")
    assert summary and summary["summary"]
    assert "5000" in summary["summary"]  # 早期数字被纳入摘要


async def test_summary_reused_not_recomputed(_temp_db, monkeypatch) -> None:
    """已有摘要且无新轮次加入摘要范围：复用，不重算。"""
    monkeypatch.setattr(service.llm, "llm_available", _no_llm)
    await _seed_runs("t1", 10)
    await service.ensure_session_summary("t1")
    prev = await db.get_conversation_summary("t1")
    out = await service.ensure_session_summary("t1")
    assert out is not None and out.get("reused") is True
    after = await db.get_conversation_summary("t1")
    assert after["summary"] == prev["summary"]


async def test_build_history_injects_summary(_temp_db, monkeypatch) -> None:
    """长会话时 _build_history 注入摘要 system 消息，并保留最近轮次完整。"""
    async def _yes_llm() -> bool:
        return True

    monkeypatch.setattr(service.llm, "llm_available", _yes_llm)
    await _seed_runs("t1", 10)
    await service.ensure_session_summary("t1")
    history = await service._build_history("t1")
    # 有摘要注入（system）且至少包含最近 1 轮完整问答
    assert any(m["role"] == "system" for m in history)
    assert any(m["content"].startswith("问题9") for m in history)


async def test_summary_cleared_with_session(_temp_db, monkeypatch) -> None:
    """删除会话时摘要一并清除。"""
    monkeypatch.setattr(service.llm, "llm_available", _no_llm)
    await _seed_runs("t1", 10)
    await service.ensure_session_summary("t1")
    assert await db.get_conversation_summary("t1") is not None
    sid = (await db.fetch_all("SELECT id FROM sessions WHERE thread_id='t1'"))[0]["id"]
    await db.delete_session(sid)
    assert await db.get_conversation_summary("t1") is None


# ---------------------------------------------------------------------------
# 模型点亮：目录 + enabled_models 校验 + bootstrap
# ---------------------------------------------------------------------------


async def test_model_catalog_and_defaults() -> None:
    """目录非空且默认点亮清单是目录子集。"""
    catalog = llm.model_catalog()
    assert len(catalog) >= 3
    for m in catalog:
        assert m["model"] and m["base"].startswith("http")
    defaults = llm.default_enabled_models()
    assert defaults and set(defaults) <= {m["model"] for m in catalog}


async def test_enabled_models_validation(_temp_db) -> None:
    """put_settings 只收目录内合法模型；非法项报错不写入。"""
    r = await put_settings({"settings": {"enabled_models": "deepseek-chat,gpt-4o-mini"}})
    assert not r["errors"], r["errors"]
    assert r["applied"]["enabled_models"] == "deepseek-chat,gpt-4o-mini"

    r2 = await put_settings({"settings": {"enabled_models": "not-a-model"}})
    assert any("没有可用的模型" in e for e in r2["errors"])
    assert "enabled_models" not in r2["applied"]


async def test_bootstrap_exposes_catalog(_temp_db) -> None:
    """bootstrap 返回 model_catalog 与 enabled_models。"""
    from app import llm as llm_mod

    llm_mod.invalidate()
    data = await main.bootstrap()
    assert data["model_catalog"] and data["model_catalog"][0]["model"]
    assert isinstance(data["enabled_models"], list)


# ---------------------------------------------------------------------------
# P1：经验库（反思）+ 主动遗忘 + 记忆分层
# ---------------------------------------------------------------------------


async def test_reflection_crud_and_dedup(_temp_db) -> None:
    """经验库：记录/去重/列出/解决/清空。"""
    r = await db.add_reflection("get_quote", {"symbol": "xxx"}, "bad symbol", "工具 get_quote 失败：检查代码")
    assert r["ok"] is True and r["deduped"] is False
    # 同工具同教训 → 去重
    r2 = await db.add_reflection("get_quote", {"symbol": "xxx2"}, "bad symbol", "工具 get_quote 失败：检查代码")
    assert r2["deduped"] is True and r2["id"] == r["id"]

    rows = await db.list_reflections()
    assert len(rows) == 1 and rows[0]["tool"] == "get_quote"

    await db.resolve_reflection(r["id"])
    assert await db.list_reflections() == []  # 已解决不再列出
    await db.add_reflection("a", {}, "e", "教训A")
    c = await db.clear_reflections()
    assert c["deleted"] >= 1


async def test_reflection_endpoints(_temp_db) -> None:
    """REST：/api/reflections 增查清。"""
    r = await main.create_reflection({"tool": "get_quote", "args": {"symbol": "1"}, "error": "e", "lesson": "教训X"})
    assert r["ok"] is True
    out = await main.reflections()
    assert out["reflections"][0]["lesson"] == "教训X"
    await main.clear_reflections()
    assert await main.reflections() == {"reflections": []}


async def test_tool_get_lessons(_temp_db) -> None:
    """get_lessons 工具返回经验库内容。"""
    await db.add_reflection("get_quote", {}, "err", "教训Y")
    out = await tools.tool_get_lessons({})
    assert '"教训Y"' in out and '"get_quote"' in out


async def test_memory_forget(_temp_db) -> None:
    """主动遗忘：仅删超过阈值的记忆；空 last_used 的保留。"""
    await db.add_memory("一直使用的记忆")
    out = await db.forget_memory(30)
    assert out["deleted"] == 0  # 未设置 last_used 的不删
    rows = await db.list_memory()
    assert rows and rows[0]["id"]
    # 主动标记某条很久未用 → 应被遗忘
    await db.touch_memory(rows[0]["id"])
    # 手动把 last_used 改到很久以前
    import datetime as _dt
    old = (_dt.datetime.now().astimezone() - _dt.timedelta(days=400)).isoformat(timespec="seconds")
    await db.execute("UPDATE user_memory SET last_used=?", (old,))
    out = await db.forget_memory(180)
    assert out["deleted"] == 1


async def test_tool_get_user_memory_kind_filter(_temp_db) -> None:
    """get_user_memory 支持按 kind 过滤且刷新 last_used。"""
    await db.add_memory("家庭偏好", "preference")
    await db.add_memory("买房计划", "goal_related")
    out = await tools.tool_get_user_memory({"kind": "preference"})
    assert '"家庭偏好"' in out and "买房计划" not in out
    out2 = await tools.tool_get_user_memory({})
    assert '"家庭偏好"' in out2 and "买房计划" in out2
    # 读取刷新 last_used
    rows = await db.list_memory()
    assert all(r["last_used"] for r in rows)


# ---------------------------------------------------------------------------
# P1 收尾：BM25 语义检索降级
# ---------------------------------------------------------------------------


async def test_memory_bm25_retrieve(_temp_db) -> None:
    """BM25 关键词检索：命中相关记忆并排序，空查询返回空。"""
    await db.add_memory("明年计划买杭州的房子", "goal_related")
    await db.add_memory("喜欢养猫，有两只", "preference")
    rows = await db.list_memory()
    hit = db.memory_retrieve("买房 首付", rows, top_k=3)
    assert hit and "房子" in hit[0]["content"], "应命中买房相关记忆"
    miss = db.memory_retrieve("", rows)
    assert miss == []


async def test_tool_get_user_memory_query(_temp_db) -> None:
    """get_user_memory 带 query 走 BM25 检索。"""
    await db.add_memory("每月还房贷 5000")
    await db.add_memory("喜欢喝咖啡")
    out = await tools.tool_get_user_memory({"query": "房贷"})
    assert "房贷" in out and "咖啡" not in out


# ---------------------------------------------------------------------------
# P2：审计日志
# ---------------------------------------------------------------------------


async def test_audit_crud(_temp_db) -> None:
    """审计日志：写入/列出/清空。"""
    await db.add_audit_log("WRITE", "POST", "/api/transactions", 200, "127.0.0.1", "入账", 5)
    await db.add_audit_log("READ_SENSITIVE", "GET", "/api/export", 200, "127.0.0.1", "导出", 3)
    logs = await db.list_audit_logs()
    assert len(logs) == 2 and logs[0]["action"] == "READ_SENSITIVE"
    w = await db.list_audit_logs(action="WRITE")
    assert len(w) == 1 and w[0]["path"] == "/api/transactions"
    c = await db.clear_audit_logs()
    assert c["deleted"] == 2
    assert await db.list_audit_logs() == []


async def test_audit_middleware_logs_writes(client) -> None:
    """中间件：写操作自动落审计日志。"""
    # 触发一次写（记忆）与一次敏感读（导出）
    await client.post("/api/memory", json={"content": "审计测试"})
    await client.get("/api/export")
    logs = await db.list_audit_logs()
    actions = {log_entry["action"] for log_entry in logs}
    assert "WRITE" in actions and "READ_SENSITIVE" in actions


# ---------------------------------------------------------------------------
# P2：附件上传 / 审计中间件 / 附件注入
# ---------------------------------------------------------------------------


async def test_attachment_crud(_temp_db) -> None:
    """附件：新增 / 列表 / 读取 / 删除。"""
    r = await db.add_attachment("note.txt", "text", 12, "这是备注内容")
    assert r["ok"] is True
    att = await db.get_attachment(r["id"])
    assert att and att["filename"] == "note.txt" and "备注" in att["content"]
    lst = await db.list_attachments()
    assert len(lst) == 1
    d = await db.delete_attachment(r["id"])
    assert d["deleted"] == 1
    assert await db.list_attachments() == []
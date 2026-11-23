"""4.16.44：会话项目卡、只读分享、深研/长度参数的后端契约。

覆盖三件容易“看起来做了、其实没生效”的事：
1. 项目资料严格按 user+thread 隔离，固定附件只认当前用户自己的；
2. 分享是创建时固化的快照，token 不可猜、可撤销、可过期，公网页转义用户内容；
3. 深研与回答长度真的进了 run_question / 问题正文，而不只是前端开关。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import httpx
import pytest
from app import db, main, service
from app.db._core import _conn
from app.db.tenant import use_user


@pytest.fixture
async def client(_temp_db):
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac


async def _upload(client: httpx.AsyncClient, name: str, text: str) -> int:
    r = await client.post(
        "/api/attachments",
        files={"file": (name, text.encode("utf-8"), "text/markdown")},
    )
    assert r.status_code == 200, r.text
    return int(r.json()["id"])


async def _final_of_ask(client: httpx.AsyncClient, payload: dict) -> dict:
    async with client.stream("POST", "/api/ask", json=payload) as resp:
        body = (await resp.aread()).decode("utf-8")
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                continue
    return next(e for e in events if e.get("type") == "final")


async def test_thread_context_roundtrip_limits_and_user_isolation(client) -> None:
    aid = await _upload(client, "投资方向备忘.md", "# 投资方向\n只做 ETF，不做个股。")
    r = await client.put(
        "/api/threads/t-alpha/context",
        json={
            "instructions": "只讨论 ETF 与资产配置。" * 200,
            "attachment_ids": [aid],
            "memories": [f"记忆 {i}" for i in range(15)],
        },
    )
    assert r.status_code == 200, r.text
    ctx = r.json()
    assert len(ctx["instructions"]) == 2000
    assert ctx["attachments"][0]["filename"] == "投资方向备忘.md"
    assert len(ctx["memories"]) == 10

    empty = (await client.get("/api/threads/t-beta/context")).json()
    assert empty["instructions"] == "" and empty["attachments"] == [] and empty["memories"] == []

    # 另一个用户读不到这条项目卡；也不能把 user 0 的附件固定进自己的项目
    with use_user(101):
        other = await db.get_thread_context("t-alpha")
        assert other["instructions"] == "" and other["attachments"] == []
        saved = await db.save_thread_context("t-alpha", instructions="x", attachment_ids=[aid], memories=[])
        assert saved["attachments"] == []


async def test_ask_merges_fixed_files_and_generation_options(client, monkeypatch) -> None:
    aid_a = await _upload(client, "项目底稿.md", "固定资料 A：每月 10 日定投 510880。")
    aid_b = await _upload(client, "本轮附件.csv", "date,amount\n2026-11-01,300")
    await client.put(
        "/api/threads/t-run/context",
        json={"instructions": "回答只谈 ETF。", "attachment_ids": [aid_a], "memories": ["定投日是每月 10 日"]},
    )

    captured: dict = {}

    async def fake_run_question(question: str, emit, **kwargs):
        captured["question"] = question
        captured.update(kwargs)
        return {
            "answer": "结论：按项目资料回答。",
            "level": "ok",
            "flags": [],
            "route": "general",
            "route_reason": "probe",
            "metrics": {},
            "llm": "stub",
            "tools": [],
            "actions": [],
        }

    monkeypatch.setattr(service, "run_question", fake_run_question)
    final = await _final_of_ask(
        client,
        {
            "question": "我该怎么定投？",
            "thread_id": "t-run",
            "attachments": [aid_b],
            "deep_research": True,
            "answer_mode": "concise",
            "web_search": False,
        },
    )
    assert final["answer"].startswith("结论")

    q = captured["question"]
    # 固定文件与本轮附件都在正文里，且顺序是先本轮、后项目固定
    assert "固定资料 A" in q and "本轮附件" in q
    assert "［联网搜索］" in q  # 深研强制联网，即便前端传了 false
    assert captured["deep_research"] is True
    assert captured["llm_options"] == {"answer_mode": "concise"}
    sc = captured["session_context"]
    assert "回答只谈 ETF" in sc and "定投日是每月 10 日" in sc
    assert "回答长度：简洁" in sc and "深度研究模式" in sc and "风险与不确定性" in sc


async def test_ask_persists_tool_steps_for_history_replay(client, monkeypatch) -> None:
    """回答落库必须保存工具轨迹，刷新后历史不能只剩一段答案。"""
    async def fake_run_question(question: str, emit, **kwargs):
        return {
            "answer": "已读取总市值。",
            "level": "ok",
            "flags": [],
            "route": "general",
            "route_reason": "steps",
            "metrics": {},
            "llm": "stub",
            "tools": ["get_market_view"],
            "actions": [],
            "steps": [
                {"name": "get_market_view", "args": {}, "summary": "总市值 100,000 元"},
            ],
        }

    monkeypatch.setattr(service, "run_question", fake_run_question)
    await _final_of_ask(client, {"question": "我的总市值多少", "thread_id": "t-steps"})
    runs = await db.list_runs("t-steps")
    assert runs
    assert runs[0]["steps"][0]["name"] == "get_market_view"
    assert runs[0]["steps"][0]["summary"] == "总市值 100,000 元"


async def test_share_snapshot_public_escape_expiry_and_revoke(client) -> None:
    await _final_of_ask(client, {"question": "分享测试问题", "thread_id": "t-share"})
    r = await client.post("/api/shares", json={"thread_id": "t-share", "expire_days": 7})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert len(token) >= 32 and "/" not in token

    pub = await client.get(f"/s/{token}")
    assert pub.status_code == 200
    assert pub.headers["cache-control"] == "no-store"
    assert "noindex" in pub.headers["x-robots-tag"]
    assert "分享测试问题" in pub.text
    assert "token" not in pub.text.lower()

    # 公网页即使快照里带脚本/伪协议，也只输出转义文本与 http(s) 链接
    payload = {
        "runs": [
            {
                "question": "<script>alert(1)</script>",
                "answer": "答案 <img src=x onerror=alert(2)>",
                "sources": [{"title": "<b>x</b>", "url": "javascript:alert(3)"}, {"title": "官网", "url": "https://example.com/a?x=1&y=2"}],
            }
        ]
    }
    evil = await db.create_share("t-evil", "<会话标题>", payload, expire_days=1)
    page = await client.get(f"/s/{evil['token']}")
    assert page.status_code == 200
    assert "<script>alert(1)</script>" not in page.text
    assert "&lt;script&gt;" in page.text
    assert "javascript:alert" not in page.text
    assert 'href="https://example.com/a?x=1&amp;y=2"' in page.text
    assert 'rel="noopener noreferrer nofollow"' in page.text

    # 撤销只对创建者有效，撤销后公网 404
    with use_user(101):
        assert await db.revoke_share(token) is False
    assert (await client.delete(f"/api/shares/{token}")).status_code == 200
    assert (await client.get(f"/s/{token}")).status_code == 404


async def test_share_expired_returns_404(client, _temp_db) -> None:
    created = await db.create_share("t-expire", "过期会话", {"runs": []}, expire_days=1)
    conn = await _conn()
    past = (datetime.now().astimezone() - timedelta(days=2)).isoformat(timespec="seconds")
    await conn.execute("UPDATE shares SET expires_at=? WHERE token=?", (past, created["token"]))
    await conn.commit()
    assert (await client.get(f"/s/{created['token']}")).status_code == 404


async def test_cross_session_project_library(client) -> None:
    aid = await _upload(client, "项目底稿.md", "固定资料：只谈 ETF。")
    created = await client.post(
        "/api/chat-projects",
        json={
            "name": "ETF 研究",
            "instructions": "所有会话都只谈 ETF。",
            "attachment_ids": [aid],
            "memories": ["每月 10 日定投"],
        },
    )
    assert created.status_code == 200, created.text
    pid = created.json()["id"]

    for tid in ("t-proj-a", "t-proj-b"):
        r = await client.put(
            f"/api/threads/{tid}/context",
            json={"project_id": pid, "instructions": "所有会话都只谈 ETF。"},
        )
        assert r.status_code == 200, r.text
        ctx = r.json()
        assert ctx["project_id"] == pid and ctx["project_name"] == "ETF 研究"
        assert "只谈 ETF" in ctx["instructions"]
        assert ctx["attachments"][0]["filename"] == "项目底稿.md"

    # 改项目一次，两个会话都读到最新内容，而不是各自快照
    upd = await client.put(
        f"/api/chat-projects/{pid}",
        json={
            "name": "ETF 研究 v2",
            "instructions": "只谈 ETF 与资产配置。",
            "attachment_ids": [aid],
            "memories": ["每月 10 日定投"],
        },
    )
    assert upd.status_code == 200, upd.text
    for tid in ("t-proj-a", "t-proj-b"):
        ctx = (await client.get(f"/api/threads/{tid}/context")).json()
        assert ctx["project_name"] == "ETF 研究 v2"
        assert "资产配置" in ctx["instructions"]

    # 显式取消绑定后回到仅本会话，不删除项目本身
    unlink = await client.put(
        "/api/threads/t-proj-a/context",
        json={"project_id": None, "instructions": "仅本会话", "attachment_ids": [], "memories": []},
    )
    assert unlink.status_code == 200, unlink.text
    assert unlink.json()["project_id"] is None
    assert (await client.get("/api/chat-projects")).json()["projects"][0]["id"] == pid

    # 删除项目后，原会话退回 thread 里保留的副本，不再 500
    deleted = await client.delete(f"/api/chat-projects/{pid}")
    assert deleted.status_code == 200, deleted.text
    ctx_b = (await client.get("/api/threads/t-proj-b/context")).json()
    assert ctx_b["project_id"] is None
    assert "资产配置" in ctx_b["instructions"]

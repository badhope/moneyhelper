"""API 集成测试：走真实 FastAPI 应用（内存临时库，行情走快照，全程无网络）。"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime

import httpx
import pytest
from app import analysis, db, main, service
from app import quotes as quotes_mod


@pytest.fixture(autouse=True)
async def _temp_db(temp_db):
    """转发 conftest 的临时库 fixture（test_api 依赖 autouse 事务隔离 + seed，且额外通过 client fixture 提供快照）。"""
    yield


@pytest.fixture
async def client(_temp_db, monkeypatch):
    # 测试环境行情一律走快照，避免网络请求
    async def _snap(positions):
        return {p["symbol"]: float(p["last"]) for p in positions}

    monkeypatch.setattr(quotes_mod, "live_quotes", _snap)

    transport = httpx.ASGITransport(app=main.app)
    # Host 用回环地址：无口令模式下中间件只放行本机/内网 Host
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1:8787"
    ) as ac:
        yield ac


async def test_health(client) -> None:
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


async def test_metrics_exposed(client) -> None:
    """/api/metrics 输出 Prometheus 文本：含请求计数、错误、运行时长。"""
    r = await client.get("/api/metrics")
    assert r.status_code == 200
    text = r.text
    assert "moneyhelper_requests_total" in text
    assert "moneyhelper_errors_total" in text
    assert "moneyhelper_uptime_seconds" in text
    assert text.startswith("# TYPE moneyhelper_")


async def test_dashboard_shape(client) -> None:
    r = await client.get("/api/dashboard")
    assert r.status_code == 200
    d = r.json()
    assert d["positions"]
    assert "totals" in d and "total_market_value" in d["totals"]
    assert "flags" in d
    assert d["source"]["seeded"] is True


async def test_dashboard_flags_follow_language(client) -> None:
    """/api/dashboard?lang=en 时，风险 flags 与来源标签输出英文（seed 含集中度风险）。"""
    r_en = await client.get("/api/dashboard?lang=en")
    assert r_en.status_code == 200
    en = r_en.json()
    zh = (await client.get("/api/dashboard")).json()
    # seed 有单一持仓 100% → 必有集中度告警
    assert en["flags"] and zh["flags"]
    # 英文模板关键词（flags 文案已英文化；「贵州茅台/白酒」等名称是数据，不作文案断言）
    assert any("above the" in f["text"] for f in en["flags"])
    assert any("high-interest" in f["text"] for f in en["flags"])
    assert any("Savings rate" in f["text"] for f in en["flags"])
    assert not any("超过" in f["text"] for f in en["flags"])
    cjk = re.compile(r"[\u4e00-\u9fa5]")
    assert any(cjk.search(f["text"]) for f in zh["flags"])
    conc_en = [f for f in en["flags"] if f["code"] == "CONCENTRATION"]
    assert conc_en, "缺少 CONCENTRATION 告警"
    # 来源标签跟随语言
    assert "Local portfolio" in en["source"]["portfolio"]


async def test_add_and_delete_transaction(client) -> None:
    r = await client.post(
        "/api/transactions",
        json={
            "date": "2026-09-25",
            "item": "测试支出",
            "category": "餐饮",
            "amount": -66.0,
        },
    )
    assert r.status_code == 200
    tx_id = r.json()["id"]
    d = (await client.get("/api/dashboard")).json()
    assert any(t["id"] == tx_id for t in d["transactions"])
    assert d["source"]["seeded"] is False  # 用户数据标记

    r = await client.delete(f"/api/transactions/{tx_id}")
    assert r.json()["deleted"] == 1


async def test_bad_transaction_400(client) -> None:
    r = await client.post(
        "/api/transactions", json={"date": "", "item": "", "amount": 0}
    )
    assert r.status_code == 400


async def test_add_and_delete_position(client) -> None:
    r = await client.post(
        "/api/positions",
        json={
            "symbol": "000001",
            "name": "平安银行",
            "kind": "股票",
            "industry": "银行",
            "shares": 100,
            "cost": 10.0,
            "last": 11.5,
        },
    )
    assert r.status_code == 200
    d = (await client.get("/api/dashboard")).json()
    assert any(p["symbol"] == "000001" for p in d["positions"])
    await client.delete("/api/positions/000001")


async def test_settings_validation(client) -> None:
    r = await client.put(
        "/api/settings",
        json={
            "settings": {
                "report_time": "25:99",
                "quote_source_mode": "badmode",
                "monthly_income": "abc",
            }
        },
    )
    body = r.json()
    assert len(body["errors"]) == 3


async def test_settings_apply(client) -> None:
    r = await client.put(
        "/api/settings", json={"settings": {"monthly_income": "30000"}}
    )
    assert r.status_code == 200
    assert r.json()["errors"] == []
    st = (await client.get("/api/settings")).json()["settings"]
    assert st["monthly_income"] == "30000"


async def _sse_events(resp) -> list[dict]:
    body = (await resp.aread()).decode()
    out = []
    for line in body.splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[6:]))
    return out


async def _clear_all_data(client) -> None:
    """清空持仓与流水（仅在 _temp_db 临时库内执行），用于验证空数据路径。"""
    d = (await client.get("/api/dashboard")).json()
    for p in d["positions"]:
        await client.delete(f"/api/positions/{p['symbol']}")
    for t in d["transactions"]:
        await client.delete(f"/api/transactions/{t['id']}")


async def _ask(client, question: str, thread_id: str = "probe") -> dict:
    async with client.stream(
        "POST", "/api/ask", json={"question": question, "thread_id": thread_id}
    ) as resp:
        events = await _sse_events(resp)
    return next(e for e in events if e["type"] == "final")


# —— general 路由：非财务问题不再被强行财务分析 ——
async def test_general_route_for_non_financial_question(client) -> None:
    final = await _ask(client, "帮我写一段周末计划")
    assert final["route"] == "general"
    assert analysis.DISCLAIMER not in final["answer"]
    assert "总市值" not in final["answer"]
    assert final["metrics"] == {}
    assert final["flags"] == []


async def test_general_route_does_not_send_financial_data(client, monkeypatch) -> None:
    """general 路由不向模型外发财务数据（隐私边界）。无模型模板路径下验证。"""
    async def _no_llm() -> bool:
        return False

    monkeypatch.setattr(service.llm, "llm_available", _no_llm)
    captured: dict[str, str] = {}

    async def fake_stream(system: str, user: str, fallback: str):
        captured["system"] = system
        captured["user"] = user
        yield "好的，这是周末计划。", "llm"

    monkeypatch.setattr(service.llm, "stream_narrate", fake_stream)
    final = await _ask(client, "帮我写一段周末计划")
    assert final["llm"] == "llm"
    assert "总市值" not in captured["user"]
    assert "ledger" not in captured["user"]
    payload = json.loads(captured["user"])
    assert "market" not in payload and "flags" not in payload
    assert payload["question"] == "帮我写一段周末计划"


async def test_general_with_llm_uses_general_agent(client, monkeypatch) -> None:
    """已接入模型时，general 分支走「通用 Agent 内核」：用通用技能包、不注入财务记忆（隐私边界）。"""
    from app import agent as agent_mod

    captured: dict = {}

    async def fake_run_agent(question, emit, history=None, lang="zh", **kw):
        captured["system"] = kw.get("system")
        captured["tools_list"] = kw.get("tools_list")
        captured["inject_memories"] = kw.get("inject_memories")
        return {"answer": "通用回复", "llm": "llm", "tools_used": ["web_search"]}

    async def fake_available() -> bool:
        return True

    monkeypatch.setattr(agent_mod, "run_agent", fake_run_agent)
    monkeypatch.setattr(service.llm, "llm_available", fake_available)
    final = await _ask(client, "帮我写段代码")
    assert final["route"] == "general"
    assert final["answer"] == "通用回复"
    assert captured["system"] == agent_mod.GENERAL_SYSTEM
    assert captured["tools_list"] is agent_mod.GENERAL_TOOLS
    assert captured["inject_memories"] is False


async def test_general_model_failure_shows_honest_fallback(client, monkeypatch) -> None:
    """模型已接入但工具循环失败 → 应提示「服务暂不可用」，而非冒充「未接入模型」。"""
    from app import agent as agent_mod

    async def _unavail(*a, **k):
        raise agent_mod.AgentUnavailable()

    async def _avail() -> bool:
        return True

    monkeypatch.setattr(agent_mod, "run_agent", _unavail)
    monkeypatch.setattr(service.llm, "llm_available", _avail)
    final = await _ask(client, "帮我联网查天气")
    assert final["route"] == "general"
    assert "暂时不可用" in final["answer"]
    assert "没有接入模型" not in final["answer"]


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("我的持仓怎么样", "market"),
        ("这个月花了多少钱", "ledger"),
        ("持仓和支出都要看", "both"),
    ],
)
async def test_financial_words_still_route_financial(client, monkeypatch, question, expected) -> None:
    async def _no_llm() -> bool:
        return False

    async def _fake_stream(system: str, user: str, fallback: str):
        yield fallback, "template"

    monkeypatch.setattr(service.llm, "llm_available", _no_llm)
    monkeypatch.setattr(service.llm, "stream_narrate", _fake_stream)
    final = await _ask(client, question)
    assert final["route"] == expected


# —— 空数据：不误报、不给零值报告、不生成晨报 ——
async def test_empty_data_has_no_savings_rate_flag(client) -> None:
    await _clear_all_data(client)
    d = (await client.get("/api/dashboard")).json()
    assert d["positions"] == [] and d["transactions"] == []
    assert all(f["code"] != "SAVINGS_RATE" for f in d["flags"])


async def test_empty_data_answer_no_guides_instead_of_zero_report(client, monkeypatch) -> None:
    """空库时问「总资产」应引导录入而非报「总市值 0 元」（新用户劝退组合）。"""
    from app import analysis

    async def _no_llm() -> bool:
        return False

    async def _fake_stream(system: str, user: str, fallback: str):
        # 模拟无模型模板路径：直接给空库引导文案
        yield analysis.no_data_answer("zh"), "template"

    monkeypatch.setattr(service.llm, "llm_available", _no_llm)
    monkeypatch.setattr(service.llm, "stream_narrate", _fake_stream)
    await _clear_all_data(client)
    final = await _ask(client, "总资产是多少")
    assert "还没有录入" in final["answer"]
    assert "总市值 0" not in final["answer"]


async def test_report_skipped_when_no_data(client) -> None:
    await _clear_all_data(client)
    before = (await client.get("/api/reports")).json()["reports"]
    r = await client.post("/api/reports/generate")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body.get("skipped") is True
    after = (await client.get("/api/reports")).json()["reports"]
    assert len(after) == len(before)


async def test_report_still_generates_with_data(client) -> None:
    r = await client.post("/api/reports/generate")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert not body.get("skipped")
    assert (await client.get("/api/reports")).json()["reports"]


# —— 多轮上下文（c2）——
def _capture_llm(monkeypatch) -> list[dict]:
    """替换 stream_narrate 为记录调用参数的 fake，并模拟「已接入模型」。

    财务分支在 agent 模式下走 run_agent 而非 stream_narrate；为了让「历史经 stream
    回传」这段可被捕获，这里让 run_agent 抛 AgentUnavailable → 图内降级确定性成文
    走 stream_narrate。由此能验证「已接入模型但工具循环失败 → 历史仍正确传递」。
    """
    from app import agent as agent_mod
    from app import service as svc

    calls: list[dict] = []

    async def fake_stream(system: str, user: str, fallback: str, history=None):
        calls.append({"system": system, "user": user, "history": history or []})
        yield "回答", "llm"

    async def fake_available() -> bool:
        return True

    async def fake_run_agent(*a, **kw):
        raise agent_mod.AgentUnavailable("mock 降级")

    monkeypatch.setattr(svc.llm, "stream_narrate", fake_stream)
    monkeypatch.setattr(svc.llm, "llm_available", fake_available)
    monkeypatch.setattr(agent_mod, "run_agent", fake_run_agent)
    return calls


def _capture_general_agent(monkeypatch) -> list[dict]:
    """替换 agent.run_agent，只记录 general 分支（GENERAL_SYSTEM）的调用与历史。

    general 分支现在走通用 Agent 循环（run_agent）而非 stream_narrate；
    财务分支的 run_agent（默认 AGENT_SYSTEM）不记录，以保住「财务历史不出机」的判定。
    """
    from app import agent as agent_mod

    calls: list[dict] = []

    async def fake_run_agent(question, emit, history=None, lang="zh", **kw):
        if kw.get("system") is agent_mod.GENERAL_SYSTEM:
            calls.append({"question": question, "history": history or []})
        return {"answer": "通用回复", "llm": "llm", "tools_used": []}

    async def fake_available() -> bool:
        return True

    monkeypatch.setattr(agent_mod, "run_agent", fake_run_agent)
    monkeypatch.setattr(service.llm, "llm_available", fake_available)
    return calls


def _payload(call: dict) -> dict:
    return json.loads(call["user"])


async def test_ask_multi_turn_passes_history(client, monkeypatch) -> None:
    calls = _capture_llm(monkeypatch)
    tid = "multi-turn"
    await _ask(client, "我这个月的钱都花到哪了？", thread_id=tid)
    final = await _ask(client, "那上个月呢？", thread_id=tid)
    assert final["route"] == "both", "省略式追问应承接上一轮财务提问"
    assert len(calls) == 2
    second = _payload(calls[1])
    hist = second.get("history") or []
    assert len(hist) == 2, "第二问应带上第一轮的用户问 + 助手答"
    assert "花到哪了" in hist[0]["content"] and hist[0]["role"] == "user"
    assert hist[1]["role"] == "assistant"
    assert second["question"] == "那上个月呢？", "当前问题必须在 payload 里"
    assert "历史" in calls[1]["system"], "system prompt 应说明如何使用历史"


async def test_followup_without_model_stays_general(client, monkeypatch) -> None:
    """未接入模型时不改判：确定性内核只算本月，回答「上个月」属误导。"""
    async def _no_llm() -> bool:
        return False

    monkeypatch.setattr(service.llm, "llm_available", _no_llm)
    tid = "followup-nomodel"
    await _ask(client, "我这个月的钱都花到哪了？", thread_id=tid)
    final = await _ask(client, "那上个月呢？", thread_id=tid)
    assert final["route"] == "general"


async def test_general_route_never_sends_history(client, monkeypatch) -> None:
    """隐私边界：general 路由不外发财务历史。"""
    calls = _capture_general_agent(monkeypatch)
    tid = "privacy"
    await _ask(client, "我这个月的钱都花到哪了？", thread_id=tid)
    await _ask(client, "帮我写一段周末计划", thread_id=tid)
    assert len(calls) == 1
    assert (calls[0]["history"] or []) == [], "general 路由不得携带财务历史"


async def test_history_is_capped(client, monkeypatch) -> None:
    calls = _capture_llm(monkeypatch)
    tid = "capped"
    for i in range(6):
        await _ask(client, f"第{i}轮问题：我的持仓怎么样？", thread_id=tid)
    hist = _payload(calls[-1]).get("history") or []
    assert 0 < len(hist) <= 8, f"历史消息数应封顶（4 轮 = 8 条），实际 {len(hist)}"


async def test_no_model_means_no_history_query(client, monkeypatch) -> None:
    """未接入模型时不做历史查询（模板路径零额外 IO）。"""
    async def _no_llm() -> bool:
        return False

    monkeypatch.setattr(service.llm, "llm_available", _no_llm)
    tid = "no-model"
    await _ask(client, "我这个月的钱都花到哪了？", thread_id=tid)
    calls: list[tuple] = []
    orig = db.list_runs

    async def spy(*a, **kw):
        calls.append((a, kw))
        return await orig(*a, **kw)

    monkeypatch.setattr(service.db, "list_runs", spy)
    await _ask(client, "那上个月呢？", thread_id=tid)
    assert calls == [], "无模型时不应查询历史"


# —— 对话内一句话记账（不依赖模型，命中即入账）——
async def test_chat_nl_records_transaction(client) -> None:
    before = len((await client.get("/api/dashboard")).json()["transactions"])
    final = await _ask(client, "午饭 35 元")
    assert final["route"] == "nl_add"
    assert "已记一笔" in final["answer"]
    assert "35" in final["answer"]
    d = (await client.get("/api/dashboard")).json()
    assert len(d["transactions"]) == before + 1
    tx = d["transactions"][0]
    assert tx["category"] == "餐饮"
    assert tx["amount"] == -35.0


async def test_chat_nl_records_income(client) -> None:
    """大额收入：先走待确认，回复「确认」后才入账（一次确认只入一笔）。"""
    tid = "nl-income-confirm"
    before = len((await client.get("/api/dashboard")).json()["transactions"])

    pending = await _ask(client, "工资 8000 已到账", thread_id=tid)
    assert pending["route"] == "nl_pending"
    assert "确认" in pending["answer"]
    d = (await client.get("/api/dashboard")).json()
    assert len(d["transactions"]) == before  # 未确认前不得入账

    final = await _ask(client, "确认", thread_id=tid)
    assert final["route"] == "nl_add"
    d = (await client.get("/api/dashboard")).json()
    assert len(d["transactions"]) == before + 1
    tx = d["transactions"][0]
    assert tx["category"] == "收入"
    assert tx["amount"] == 8000.0

    # 再次「确认」不重复入账（pending 上下文已消费）
    await _ask(client, "确认", thread_id=tid)
    d = (await client.get("/api/dashboard")).json()
    assert len(d["transactions"]) == before + 1


async def test_chat_nl_pending_cancel(client) -> None:
    """大额待确认回复「取消」：不入账 + 取消回执。"""
    tid = "nl-income-cancel"
    before = len((await client.get("/api/dashboard")).json()["transactions"])

    pending = await _ask(client, "奖金 6600 到账", thread_id=tid)
    assert pending["route"] == "nl_pending"

    final = await _ask(client, "取消", thread_id=tid)
    assert final["route"] == "nl_cancel"
    d = (await client.get("/api/dashboard")).json()
    assert len(d["transactions"]) == before


async def test_confirm_reply_without_pending_not_hijacked(client) -> None:
    """无 pending 上下文时，「确认」不得被当作审批回执。"""
    final = await _ask(client, "确认", thread_id="no-pending-thread")
    assert final["route"] not in ("nl_add", "nl_cancel", "nl_pending")


async def test_chat_nl_multi_segment_large_amount_needs_approval(client) -> None:
    """多段句里任一段大额都必须走审批（防「奶茶 20，房租 6000」只取第一段绕过门槛）。"""
    tid = "nl-multi-bypass"
    before = len((await client.get("/api/dashboard")).json()["transactions"])

    pending = await _ask(client, "奶茶 20，房租 6000", thread_id=tid)
    assert pending["route"] == "nl_pending"
    d = (await client.get("/api/dashboard")).json()
    assert len(d["transactions"]) == before  # 未确认前整句都不入账

    final = await _ask(client, "确认", thread_id=tid)
    assert final["route"] == "nl_add"
    newest = sorted(abs(t["amount"]) for t in (await client.get("/api/dashboard")).json()["transactions"][:2])
    assert newest == [20.0, 6000.0]


async def test_chat_nl_concurrent_confirm_records_once(client) -> None:
    """并发两个「确认」只允许一笔入账（claim 原子消费；防双标签页/重试重复入账）。"""
    tid = "nl-concurrent-confirm"
    pending = await _ask(client, "工资 9000 已到账", thread_id=tid)
    assert pending["route"] == "nl_pending"

    await asyncio.gather(
        _ask(client, "确认", thread_id=tid),
        _ask(client, "确认", thread_id=tid),
    )
    tx = (await client.get("/api/dashboard")).json()["transactions"]
    assert sum(1 for t in tx if t["amount"] == 9000.0) == 1


async def test_watchlist_command_not_hijacked_by_bookkeeping(client) -> None:
    """「把 600519 加入自选」不得被记账解析劫持（6 位代码会被 nlparse 当成 60 万金额）。"""
    before = len((await client.get("/api/dashboard")).json()["transactions"])
    final = await _ask(client, "把 600519 加入自选")
    assert final["route"] not in ("nl_add", "nl_pending", "bookkeeping")
    assert len((await client.get("/api/dashboard")).json()["transactions"]) == before


@pytest.mark.parametrize("question", ["600519 最近走势怎么样？", "看看茅台的走势"])
async def test_market_keyword_routes_market(client, question) -> None:
    """走势类问句路由到 market（此前落 general，模型只能答「无法联网」）。"""
    final = await _ask(client, question)
    assert final["route"] == "market"


async def test_llm_classify_fallback(monkeypatch) -> None:
    """规则未命中时的模型兜底分类：合法 JSON 采纳，非法/越界一律 None。"""

    async def good(system: str, user: str, timeout: float = 20.0) -> dict:
        return {"route": "market"}

    monkeypatch.setattr(service.llm, "json_complete", good)
    assert await service.classify_question_llm("茅台现在多少钱") == "market"

    async def bad(system: str, user: str, timeout: float = 20.0) -> dict:
        return {"route": "not-a-route"}

    monkeypatch.setattr(service.llm, "json_complete", bad)
    assert await service.classify_question_llm("随便聊聊") is None


async def test_mem_legacy_recall_fallback(client) -> None:
    """mem0 不可用（无 embedding 凭据）时，记忆检索降级为 user_memory 关键词检索。"""
    from app import mem

    await client.post("/api/memory", json={"content": "用户每个月 10 号要还房贷 6000"})
    await client.post("/api/memory", json={"content": "用户偏好稳健型投资"})
    hits = await mem._legacy_recall("还房贷是几号", 5)
    assert hits and "房贷" in hits[0]["memory"]
    assert all("memory" in h for h in hits)


async def test_api_run_skill_endpoint(client) -> None:
    """POST /api/skills/{id}/run：成功归档（skill:<id>、不进会话）；不存在 → 400。"""
    cfg = (await client.get("/api/agent-config")).json()["config"]
    cfg.setdefault("skills", {})["api_run"] = {
        "name": "接口触发",
        "description": "",
        "enabled": True,
        "action": {"prompt": "帮我看看这个月的支出", "time": "09:00"},
    }
    r = await client.post("/api/agent-config", json={"config": cfg})
    assert r.status_code == 200 and r.json()["ok"] is True

    r = await client.post("/api/skills/api_run/run")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True and d["thread_id"] == "skill:api_run"
    # 归档可见、会话列表不可见
    runs = (await client.get("/api/history", params={"thread_id": "skill:api_run", "limit": 5})).json()["runs"]
    assert len(runs) == 1
    sessions = (await client.get("/api/sessions")).json()["sessions"]
    assert all(s["thread_id"] != "skill:api_run" for s in sessions)

    r = await client.post("/api/skills/nope/run")
    assert r.status_code == 400 and "不存在" in r.json()["error"]


async def test_mem_suggest_endpoint(client, monkeypatch) -> None:
    """AI 归纳偏好：未接模型报错；无对话记录报错；有记录时出建议且去重、不落库。"""
    # 未接入模型
    r = await client.post("/api/memory/suggest", json={})
    d = r.json()
    assert d["ok"] is False and "模型" in d["error"]

    async def fake_avail() -> bool:
        return True

    monkeypatch.setattr(service.llm, "llm_available", fake_avail)
    # 无对话记录 → 友好报错
    d = (await client.post("/api/memory/suggest", json={})).json()
    assert d["ok"] is False and "对话" in d["error"]

    # 有一条对话记录 → 走模型（mock）；输出含重复与已有记忆，应被去重
    await _ask(client, "我这个月花了多少钱", thread_id="mem-suggest-1")
    await client.post("/api/memory", json={"content": "用户偏好稳健型投资"})

    async def fake_json(system: str, user: str, timeout: float = 25.0) -> dict:
        assert "已记住的内容" in user  # 现有记忆应进 prompt（防重复建议）
        return {
            "suggestions": [
                "用户偏好稳健型投资",  # 与已有记忆重复 → 剔除
                "用户关注每月开销变化",
                "用户关注每月开销变化",  # 自身重复 → 剔除
                "用户常看持仓盈亏",
            ]
        }

    monkeypatch.setattr(service.llm, "json_complete", fake_json)
    d = (await client.post("/api/memory/suggest", json={})).json()
    assert d["ok"] is True
    assert d["suggestions"] == ["用户关注每月开销变化", "用户常看持仓盈亏"]
    # 不落库：建议不自动写入
    mem = (await client.get("/api/memory")).json()["memory"]
    assert not any("常看持仓盈亏" in m["content"] for m in mem)


async def test_agent_config_generate_endpoint(client, monkeypatch) -> None:
    """AI 生成端点：未接入模型友好报错；模型可用时返回建议且不落库。"""
    # 未接入模型（conftest 的 _no_real_llm autouse 已置空 llm._cfg）
    r = await client.post(
        "/api/agent-config/generate", json={"kind": "skill", "prompt": "每周提醒检查定投"}
    )
    d = r.json()
    assert d["ok"] is False and "模型" in d["error"]

    # 模拟模型可用 + 返回合法 JSON（service.llm 与 main 内引用的 llm 是同一模块对象）
    async def fake_json(system: str, user: str, timeout: float = 20.0) -> dict:
        return {"id": "weekly_check", "name": "定投检查", "description": "每周提醒检查定投计划"}

    async def fake_avail() -> bool:
        return True

    monkeypatch.setattr(service.llm, "json_complete", fake_json)
    monkeypatch.setattr(service.llm, "llm_available", fake_avail)
    r = await client.post(
        "/api/agent-config/generate", json={"kind": "skill", "prompt": "每周提醒检查定投"}
    )
    d = r.json()
    assert d["ok"] is True
    assert d["suggestion"]["id"] == "weekly_check"
    assert d["suggestion"]["enabled"] is True
    # 只产出建议、不落库
    cfg = (await client.get("/api/agent-config")).json()["config"]
    assert "weekly_check" not in cfg.get("skills", {})


async def test_budgets_suggest_endpoint(client, monkeypatch) -> None:
    """AI 预算建议：未接入模型友好报错；模型可用时按支出汇总给出建议且不落库。"""
    # 未接入模型
    r = await client.post("/api/budgets/suggest", json={})
    d = r.json()
    assert d["ok"] is False and "模型" in d["error"]

    # 有支出记录 + 模型可用
    await client.post("/api/transactions", json={"date": "2026-10-01", "item": "午餐", "category": "餐饮", "amount": -50})
    await client.post("/api/transactions", json={"date": "2026-10-02", "item": "打车", "category": "交通", "amount": -30})

    async def fake_json(system: str, user: str, timeout: float = 25.0) -> dict:
        assert "餐饮" in user  # 汇总里应包含真实分类
        return {"total": 3000, "categories": {"餐饮": 1500, "交通": 800}}

    async def fake_avail() -> bool:
        return True

    monkeypatch.setattr(service.llm, "json_complete", fake_json)
    monkeypatch.setattr(service.llm, "llm_available", fake_avail)
    r = await client.post("/api/budgets/suggest", json={})
    d = r.json()
    assert d["ok"] is True
    assert d["suggestion"]["total"] == 3000
    assert d["suggestion"]["categories"]["餐饮"] == 1500
    # 不落库：预算仍需用户确认后走 PUT /api/budgets
    budgets = (await client.get("/api/budgets")).json()["budgets"]
    assert not any(b["amount"] == 3000 for b in budgets)


async def test_rules_and_report_focus_suggest(client, monkeypatch) -> None:
    """规则建议 / 晨报关注点建议：未接模型友好报错；模型可用时出建议；夹取到合理区间。"""
    r = await client.post("/api/rules/suggest", json={})
    assert r.json()["ok"] is False
    r = await client.post("/api/reports/suggest-focus", json={})
    assert r.json()["ok"] is False

    # 准备数据：一笔收入 + 一笔支出
    await client.post("/api/transactions", json={"date": "2026-10-01", "item": "工资", "category": "收入", "amount": 20000})
    await client.post("/api/transactions", json={"date": "2026-10-02", "item": "午餐", "category": "餐饮", "amount": -50})

    async def fake_rules(system: str, user: str, timeout: float = 25.0) -> dict:
        return {
            "monthly_income": 20000,
            "emergency_target_months": 99,  # 越界：应被夹到 12
            "essential_categories": "餐饮,交通",
            "savings_goal": 1,  # 越界：应被夹到 5
        }

    async def fake_avail() -> bool:
        return True

    monkeypatch.setattr(service.llm, "json_complete", fake_rules)
    monkeypatch.setattr(service.llm, "llm_available", fake_avail)
    d = (await client.post("/api/rules/suggest", json={})).json()
    assert d["ok"] is True
    assert d["suggestion"]["monthly_income"] == 20000
    assert d["suggestion"]["emergency_target_months"] == 12
    assert d["suggestion"]["savings_goal"] == 5
    # 不落库：设置未变
    st = (await client.get("/api/settings")).json()["settings"]
    assert st.get("monthly_income") != "20000"

    async def fake_focus(system: str, user: str, timeout: float = 20.0) -> dict:
        assert "贵州茅台" in user or "持仓" in user
        return {"focus": "重点关注白酒持仓的集中度风险"}

    monkeypatch.setattr(service.llm, "json_complete", fake_focus)
    d = (await client.post("/api/reports/suggest-focus", json={})).json()
    assert d["ok"] is True and "集中度" in d["suggestion"]["focus"]


async def test_report_focus_setting_roundtrip(client) -> None:
    """report_focus 为自由文本设置：可保存、可读回、可清空（晨报生成会读取它）。"""
    r = await client.put("/api/settings", json={"settings": {"report_focus": "  盯住房贷利率变化  "}})
    assert r.status_code == 200 and r.json()["ok"] is True
    st = (await client.get("/api/settings")).json()["settings"]
    assert st["report_focus"] == "盯住房贷利率变化"  # 去空白
    await client.put("/api/settings", json={"settings": {"report_focus": ""}})
    st = (await client.get("/api/settings")).json()["settings"]
    assert st.get("report_focus", "") == ""


@pytest.mark.parametrize(
    "question",
    ["我这个月花了3000怎么办", "昨天打车32元花了吗", "这个月餐饮预算应该定多少"],
)
async def test_chat_does_not_hijack_questions(client, question) -> None:
    """疑问句不得被记账劫持。"""
    before = len((await client.get("/api/dashboard")).json()["transactions"])
    final = await _ask(client, question)
    assert final["route"] != "nl_add"
    d = (await client.get("/api/dashboard")).json()
    assert len(d["transactions"]) == before


# —— 问答来源可溯源（route/llm 随回答落库，历史才能显示真实来源）——
async def test_run_stores_route_and_llm(client, monkeypatch) -> None:
    """通用问答的 route 与 llm 来源应正确落库（无模型模板路径）。"""
    async def _no_llm() -> bool:
        return False

    async def _fake_stream(system: str, user: str, fallback: str):
        yield fallback, "template"

    monkeypatch.setattr(service.llm, "llm_available", _no_llm)
    monkeypatch.setattr(service.llm, "stream_narrate", _fake_stream)
    await _ask(client, "帮我写一段周末计划", thread_id="prov-1")
    runs = (await client.get("/api/history?thread_id=prov-1")).json()["runs"]
    assert len(runs) == 1
    r = runs[0]
    assert r["route"] == "general", "通用问答的 route 应落库"
    assert r["llm"] == "template", "未接入模型时 llm 应落 template"
    assert r["route_reason"], "route_reason 应一并落库"


async def test_finance_run_stores_route(client) -> None:
    await _ask(client, "我这个月的钱都花到哪了？", thread_id="prov-2")
    r = (await client.get("/api/history?thread_id=prov-2")).json()["runs"][0]
    assert r["route"] in ("ledger", "both", "market")
    assert r["llm"] in ("template", "llm")


async def test_history_without_provenance_does_not_fake_it(client) -> None:
    """旧记录（新增列前写入、来源为空）不得被当成有来源。"""
    await _ask(client, "我这个月的钱都花到哪了？", thread_id="prov-3")
    # 模拟「新增列之前写入」的旧记录：来源列为空
    conn = await db._conn()
    await conn.execute(
        "UPDATE runs SET route='', llm='', route_reason='' WHERE thread_id=?", ("prov-3",)
    )
    await conn.commit()
    r = (await client.get("/api/history?thread_id=prov-3")).json()["runs"][0]
    assert r["route"] == "" and r["llm"] == ""
    assert r["level"], "等级仍应保留（runs 一直有存）"


# —— 默认路径必须是通用 agent（有记忆、无财务分级、无内部步骤泄漏）——
async def test_general_chat_carries_conversation_memory(client, monkeypatch) -> None:
    """通用 agent 的基本要求：第二轮要看得见第一轮。"""
    calls = _capture_general_agent(monkeypatch)
    tid = "agent-mem"
    await _ask(client, "帮我写一段周末计划", thread_id=tid)
    await _ask(client, "再短一点", thread_id=tid)
    assert len(calls) == 2
    hist = calls[1]["history"] or []
    assert len(hist) == 2, "第二轮应带上第一轮问答"
    assert "周末计划" in hist[0]["content"]
    assert hist[1]["role"] == "assistant"


async def test_general_chat_never_carries_finance_history(client, monkeypatch) -> None:
    """隐私边界不因加记忆而破：财务历史绝不进入通用请求。"""
    calls = _capture_general_agent(monkeypatch)
    tid = "agent-privacy"
    await _ask(client, "我这个月的钱都花到哪了？", thread_id=tid)
    await _ask(client, "帮我写一段周末计划", thread_id=tid)
    assert len(calls) == 1
    assert (calls[0]["history"] or []) == [], "通用请求不得携带财务历史"


async def test_general_answer_has_no_internal_level(client) -> None:
    """通用闲聊不该套财务分级（level 留空 → 前端不显示等级徽标）。"""
    final = await _ask(client, "帮我写一段周末计划", thread_id="agent-level")
    assert final["route"] == "general"
    assert final["level"] == "", "通用回答不应带等级代号"


async def test_general_answer_emits_no_internal_steps(client) -> None:
    """通用闲聊不该显示「查看分析过程」（内部步骤不进用户界面）。"""
    async with client.stream(
        "POST", "/api/ask", json={"question": "帮我写一段周末计划", "thread_id": "agent-steps"}
    ) as resp:
        events = await _sse_events(resp)
    assert not [e for e in events if e["type"] == "step"], "通用路径不应发内部步骤事件"
    assert [e["type"] for e in events][-1] == "done"


async def test_ask_emits_single_start_event(client) -> None:
    """start 只发一次：事件契约归 service，API 层曾重复发首帧。"""
    async with client.stream(
        "POST", "/api/ask", json={"question": "帮我写一段周末计划", "thread_id": "start-once"}
    ) as resp:
        events = await _sse_events(resp)
    types = [e["type"] for e in events]
    assert types.count("start") == 1, f"start 应恰好一次，实际 {types.count('start')}"
    assert types[0] == "start" and types[-1] == "done"


async def test_ask_sse_flow(client) -> None:
    async with client.stream(
        "POST", "/api/ask", json={"question": "我这个月的钱都花到哪了？"}
    ) as resp:
        assert resp.status_code == 200
        events = await _sse_events(resp)
    types = [e["type"] for e in events]
    assert types[0] == "start"
    assert "final" in types
    assert types[-1] == "done"
    final = next(e for e in events if e["type"] == "final")
    assert final["route"] == "ledger"
    assert "收入" in final["answer"]
    assert "结余" in final["answer"]


async def test_ask_missing_question_400(client) -> None:
    r = await client.post("/api/ask", json={})
    assert r.status_code == 400


async def test_history_archival(client) -> None:
    async with client.stream(
        "POST", "/api/ask", json={"question": "我的组合怎么样？", "thread_id": "t1"}
    ) as resp:
        await resp.aread()
    runs = (await client.get("/api/history?thread_id=t1")).json()["runs"]
    assert len(runs) == 1
    assert runs[0]["question"] == "我的组合怎么样？"


async def test_ask_regenerate_replaces_last(client) -> None:
    """重新生成：run 数量不变（替换而非追加），且最后一条是重新生成的结果。"""
    tid = "regen-test"
    async with client.stream(
        "POST", "/api/ask", json={"question": "我的组合怎么样？", "thread_id": tid}
    ) as resp:
        await resp.aread()
    async with client.stream(
        "POST",
        "/api/ask",
        json={"question": "我的组合怎么样？", "thread_id": tid, "regenerate": True},
    ) as resp:
        await resp.aread()
    runs = (await client.get(f"/api/history?thread_id={tid}")).json()["runs"]
    assert len(runs) == 1, "重新生成后不应追加新记录"
    assert runs[0]["question"] == "我的组合怎么样？"
    assert "总市值" in runs[0]["answer"]


@pytest.mark.timeout(120)
async def test_ai_misconfig_falls_back_to_template(client) -> None:
    """AI 配置了但端点不可达 → 自动降级模板（不冒充模型输出）。

    走真实故障转移链：agent 调用 + stream_narrate 多模型各带 num_retries=2 退避重试，
    实测约 40s（机器相关）——全局 30s 超时不够，此处单独放宽；链路本身是产品行为。
    """
    r = await client.put(
        "/api/settings",
        json={
            "settings": {
                "ai_enabled": "on",
                "ai_base_url": "http://127.0.0.1:1/v1",  # 必然连接失败
                "ai_api_key": "test-key",
                "ai_model": "test-model",
            }
        },
    )
    assert r.status_code == 200
    async with client.stream(
        "POST",
        "/api/ask",
        json={"question": "我的组合怎么样？", "thread_id": "ai-fallback"},
    ) as resp:
        events = await _sse_events(resp)
    final = next(e for e in events if e["type"] == "final")
    assert final["llm"] == "template"
    assert "总市值" in final["answer"]


async def test_nl_add_rule_and_fallback(client) -> None:
    """一句话记账：规则解析直接入账；读不懂时 422 引导；空输入 400。"""
    r = await client.post("/api/nl-add", json={"text": "昨天打车 32 元"})
    assert r.status_code == 200
    d = r.json()
    assert d["source"] == "rule"
    assert d["transaction"]["amount"] == -32
    assert d["transaction"]["category"] == "交通"
    assert d["transaction"]["item"] == "打车"

    r2 = await client.post("/api/nl-add", json={"text": "工资 8000 已到账"})
    assert r2.status_code == 200
    assert r2.json()["transaction"]["amount"] == 8000
    assert r2.json()["transaction"]["category"] == "收入"

    # 规则拿不到金额 + 测试环境无 AI 配置 → 422 引导
    r3 = await client.post("/api/nl-add", json={"text": "乱七八糟"})
    assert r3.status_code == 422

    r4 = await client.post("/api/nl-add", json={"text": "  "})
    assert r4.status_code == 400

    # 入账后流水可查
    r5 = (await client.get("/api/dashboard")).json()
    assert any(t["item"] == "打车" and t["amount"] == -32 for t in r5["transactions"])


async def test_csv_import_preview_and_commit(client) -> None:
    """账单 CSV：解析/列映射/预览 → 批量入账 → 流水可查。"""
    csv_text = (
        "交易时间,收/支,交易对方,金额\n"
        "2026-09-10 12:00:00,支出,滴滴出行,32.00\n"
        "2026-09-11 08:00:00,收入,工资,8000\n"
        "2026-09-12 20:00:00,支出,某某超市,56.50\n"
    )
    r = await client.post("/api/import/csv", json={"content": csv_text, "source": "generic"})
    assert r.status_code == 200, r.text
    d = r.json()
    preview = d["preview"]
    assert preview["summary"]["count"] == 3
    by_desc = {p["item"]: p for p in preview["transactions"]}
    assert by_desc["滴滴出行"]["amount"] == -32
    assert by_desc["滴滴出行"]["category"] == "交通"
    assert by_desc["工资"]["amount"] == 8000
    assert by_desc["工资"]["category"] == "收入"

    r2 = await client.post("/api/import/csv/confirm", json={"transactions": preview["transactions"]})
    assert r2.status_code == 200, r2.text
    assert r2.json()["imported"] == 3

    r3 = (await client.get("/api/dashboard")).json()
    assert any(
        t["item"] == "滴滴出行" and t["amount"] == -32 for t in r3["transactions"]
    )
    assert any(t["item"] == "工资" and t["amount"] == 8000 for t in r3["transactions"])

    # 表头不可识别 → 新实现不报错，返回 200 并在 errors 中收集
    r4 = await client.post("/api/import/csv", json={"content": "foo,bar\n1,2\n", "source": "generic"})
    assert r4.status_code == 200
    d4 = r4.json()
    assert d4["warnings"] or d4["preview"]["errors"]

    # 空内容 → 422 (Pydantic min_length=1 校验)
    r5 = await client.post("/api/import/csv", json={"content": ""})
    assert r5.status_code == 422


async def test_debt_due_day(client) -> None:
    """负债扣款日：保存与归一化（非法值回退空）。"""
    r = await client.post(
        "/api/debts",
        json={
            "name": "车贷",
            "monthly": 2000,
            "balance": 80000,
            "rate": 0.05,
            "due_day": "28",
        },
    )
    assert r.status_code == 200
    d = (await client.get("/api/dashboard")).json()
    item = next(x for x in d["debts"]["items"] if x["name"] == "车贷")
    assert item["due_day"] == "28"

    await client.post(
        "/api/debts",
        json={
            "name": "车贷",
            "monthly": 2000,
            "balance": 80000,
            "rate": 0.05,
            "due_day": "abc",
        },
    )
    d2 = (await client.get("/api/dashboard")).json()
    item2 = next(x for x in d2["debts"]["items"] if x["name"] == "车贷")
    assert item2["due_day"] == ""


async def test_subscriptions_crud(client) -> None:
    """订阅增删：新增入账、dashboard 汇总、非法值 400、删除后消失。"""
    r = await client.post(
        "/api/subscriptions",
        json={"name": "Netflix", "monthly": 68, "note": "影音", "due_day": "5"},
    )
    assert r.status_code == 200 and r.json()["ok"]

    d = (await client.get("/api/dashboard")).json()
    item = next(x for x in d["subscriptions"]["items"] if x["name"] == "Netflix")
    assert item["monthly"] == 68 and item["due_day"] == "5"

    # 非法：空名称 / 负金额
    r2 = await client.post("/api/subscriptions", json={"name": "", "monthly": 10})
    assert r2.status_code == 400
    r3 = await client.post("/api/subscriptions", json={"name": "x", "monthly": -1})
    assert r3.status_code == 400

    r4 = await client.delete("/api/subscriptions/Netflix")
    assert r4.status_code == 200 and r4.json()["deleted"] == 1
    d2 = (await client.get("/api/dashboard")).json()
    assert all(x["name"] != "Netflix" for x in d2["subscriptions"]["items"])


async def test_import_backup_roundtrip(client) -> None:
    """备份恢复：导出 → 清空业务表 → 恢复 → 数据一致；AI Key 不恢复。"""
    await client.put(
        "/api/settings",
        json={"settings": {"ai_api_key": "sk-secret", "savings_goal": "18"}},
    )
    backup = (await client.get("/api/export")).json()
    assert str(backup.get("version")) == "3"  # 3 = 含家庭成员/审计链的当前格式
    assert "sk-secret" not in json.dumps(backup)

    # 清空业务表
    for t in ("positions", "transactions", "subscriptions", "debts", "budgets"):
        await client.post("/api/portfolio/reset")  # 幂等：重播种后再删
        from app import db

        await db.execute(f"DELETE FROM {t}")
    await client.delete("/api/sessions/1")

    r = await client.post("/api/import/backup", json=backup)
    assert r.status_code == 200, r.json()
    counts = r.json()["counts"]
    assert counts["positions"] > 0 and counts["transactions"] > 0

    # 恢复后的数据与备份一致
    restored = (await client.get("/api/export")).json()
    assert len(restored["positions"]) == len(backup["positions"])
    assert restored["positions"][0]["symbol"] == backup["positions"][0]["symbol"]
    assert len(restored["transactions"]) == len(backup["transactions"])
    # AI Key 不恢复（安全边界）
    assert restored["settings"].get("ai_api_key") in (None, "")

    # 非法备份 → 400
    r2 = await client.post("/api/import/backup", json={"meta": {"version": "unknown"}})
    assert r2.status_code == 400


async def test_kline_endpoint(client, monkeypatch) -> None:
    """K 线端点：正常返回、非法代码 404。"""
    from app import quotes as quotes_mod

    async def _fake(symbol, period, limit):
        return {
            "symbol": symbol,
            "period": period,
            "source": "fake",
            "points": [{"date": "2026-09-01", "close": 10.0, "pct_change": 0.1}],
        }

    monkeypatch.setattr(quotes_mod, "kline", _fake)
    r = await client.get("/api/kline", params={"symbol": "600519"})
    assert r.status_code == 200
    assert r.json()["points"]

    async def _empty(symbol, period, limit):
        return None

    monkeypatch.setattr(quotes_mod, "kline", _empty)
    r2 = await client.get("/api/kline", params={"symbol": "000000"})
    assert r2.status_code == 404


async def test_export_csv(client) -> None:
    """流水 CSV 导出：带 BOM、含表头与示例数据。"""
    r = await client.get("/api/export/csv")
    assert r.status_code == 200
    text = r.text
    assert text.startswith("\ufeff日期")
    assert "项目" in text and "分类" in text and "金额" in text


async def test_budgets_lifecycle(client) -> None:
    """预算：设置本月总预算+分类预算 → 实时使用率计算；非法月份拒绝。"""
    month = datetime.now().astimezone().strftime("%Y-%m")
    r = await client.put(
        "/api/budgets",
        json={
            "month": month,
            "budgets": [
                {"category": "__total", "amount": 5000},
                {"category": "餐饮", "amount": 800},
            ],
        },
    )
    assert r.status_code == 200
    assert r.json()["count"] == 2

    d = (await client.get(f"/api/budgets?month={month}")).json()
    assert d["month"] == month
    assert d["usage"]["total_budget"] == 5000
    assert d["usage"]["total_spent"] > 0
    assert d["usage"]["total_pct"] > 0
    assert d["usage"]["days_left"] >= 1
    cats = {c["category"]: c for c in d["usage"]["categories"]}
    assert "餐饮" in cats
    assert cats["餐饮"]["budget"] == 800

    # 非法月份拒绝
    r2 = await client.put("/api/budgets", json={"month": "2026-13", "budgets": []})
    assert r2.status_code == 400

    # 重置后预算被清空
    await client.post("/api/portfolio/reset")
    d2 = (await client.get(f"/api/budgets?month={month}")).json()
    assert d2["usage"]["total_budget"] == 0


async def test_budget_excludes_non_consumption(client) -> None:
    """R3 回归：预算使用口径不含投资/还款（储蓄转移不计入消费支出）。"""
    month = datetime.now().astimezone().strftime("%Y-%m")
    d = (await client.get(f"/api/budgets?month={month}")).json()
    dash = (await client.get("/api/dashboard")).json()
    month_neg = [
        t
        for t in dash["transactions"]
        if str(t["date"]).startswith(month) and t["amount"] < 0
    ]
    excluded = [t for t in month_neg if t["category"] in {"投资", "还款"}]
    assert excluded, "种子流水应含投资/还款，否则本测试失去意义"
    expected = round(
        sum(-t["amount"] for t in month_neg if t["category"] not in {"投资", "还款"}),
        2,
    )
    assert d["usage"]["total_spent"] == expected


async def test_manual_report(client, monkeypatch) -> None:
    """手动晨报走五维体检输出（无模型模板路径，含综合评分/总市值）。"""
    async def _no_llm() -> bool:
        return False

    async def _fake_stream(system: str, user: str, fallback: str):
        yield fallback, "template"

    monkeypatch.setattr(service.llm, "llm_available", _no_llm)
    monkeypatch.setattr(service.llm, "stream_narrate", _fake_stream)
    r = await client.post("/api/reports/generate")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    # 晨报走五维体检输出：含综合评分、总市值与维度结论
    assert "综合评分" in body["answer"]
    assert "总市值" in body["answer"]


# ---------------------------------------------------------------------------
# 会话管理 / 导出 / 趋势（新增能力）
# ---------------------------------------------------------------------------


async def test_sessions_lifecycle(client) -> None:
    # 新建会话（默认标题）
    r = await client.post("/api/sessions")
    assert r.status_code == 200
    sid = r.json()["id"]
    tid = r.json()["thread_id"]

    # 问答落库应自动登记会话，且默认标题被首个问题覆盖
    async with client.stream(
        "POST", "/api/ask", json={"question": "测试问答一", "thread_id": tid}
    ) as resp:
        await resp.aread()
    sess = (await client.get("/api/sessions")).json()["sessions"]
    assert any(s["thread_id"] == tid and s["title"] == "测试问答一" for s in sess)

    # 重命名
    r = await client.patch(f"/api/sessions/{sid}", json={"title": "改名后的会话"})
    assert r.status_code == 200
    sess = (await client.get("/api/sessions")).json()["sessions"]
    assert any(s["id"] == sid and s["title"] == "改名后的会话" for s in sess)

    # 重命名后的标题在后续问答中保持（自定义标题不覆盖）
    async with client.stream(
        "POST", "/api/ask", json={"question": "测试问答二", "thread_id": tid}
    ) as resp:
        await resp.aread()
    sess = (await client.get("/api/sessions")).json()["sessions"]
    assert any(s["id"] == sid and s["title"] == "改名后的会话" for s in sess)

    # 删除会话应连带删除该 thread 的问答
    await client.delete(f"/api/sessions/{sid}")
    sess = (await client.get("/api/sessions")).json()["sessions"]
    assert all(s["thread_id"] != tid for s in sess)
    runs = (await client.get(f"/api/history?thread_id={tid}")).json()["runs"]
    assert runs == []


async def test_history_search_delete_clear(client) -> None:
    """全局历史：搜索（跨会话）、单条删除、清空全部。"""
    async with client.stream(
        "POST", "/api/ask", json={"question": "这个月花了多少", "thread_id": "hs-1"}
    ) as resp:
        await resp.aread()

    # 全局搜索命中，且附带会话标题（供前端跳转）
    r = (await client.get("/api/history?q=花了")).json()["runs"]
    assert any(run["question"] == "这个月花了多少" and run["session_title"] for run in r)

    # 单条删除
    target = next(run for run in r if run["question"] == "这个月花了多少")
    d = (await client.delete(f"/api/runs/{target['id']}")).json()
    assert d["deleted"] == 1
    r2 = (await client.get("/api/history?thread_id=hs-1")).json()["runs"]
    assert all(run["id"] != target["id"] for run in r2)

    # 清空全部历史（会话一并清空）
    await client.post("/api/history/clear")
    assert (await client.get("/api/history?thread_id=hs-1")).json()["runs"] == []
    assert (await client.get("/api/sessions")).json()["sessions"] == []


async def test_settings_new_keys(client) -> None:
    r = await client.put(
        "/api/settings",
        json={
            "settings": {
                "voice_input": "on",
                "compact_numbers": "off",
                "savings_goal": "25",
                "auto_refresh": "on",
                "auto_refresh_seconds": "120",
                "bad_key": "x",
            }
        },
    )
    body = r.json()
    assert body["errors"] == ["未知配置项：bad_key"]
    st = body["settings"]
    assert st["voice_input"] == "on"
    assert st["savings_goal"] == "25"

    # 越界值被拒绝
    r = await client.put("/api/settings", json={"settings": {"savings_goal": "200"}})
    assert r.json()["errors"]


async def test_agent_behavior_settings(client) -> None:
    """Agent 行为可配置化：工具轮次/规划/反思 键可写、越界被拒。"""
    r = await client.put(
        "/api/settings",
        json={"settings": {"agent_tool_turns": "12", "agent_plan": "off", "agent_reflect": "on"}},
    )
    body = r.json()
    assert body["errors"] == []
    st = body["settings"]
    assert st["agent_tool_turns"] == "12"
    assert st["agent_plan"] == "off"
    assert st["agent_reflect"] == "on"

    # 越界 / 非法枚举被拒
    r = await client.put("/api/settings", json={"settings": {"agent_tool_turns": "99"}})
    assert r.json()["errors"]
    r = await client.put("/api/settings", json={"settings": {"agent_plan": "maybe"}})
    assert r.json()["errors"]

    # 默认值存在（seed）
    assert body["settings"]["agent_reflect"] == "on"


async def test_export_and_trend(client) -> None:
    r = await client.get("/api/export")
    body = r.json()
    assert body["version"] == 3  # 3 = 含家庭成员/审计链的当前格式
    assert body["positions"] and body["transactions"] and body["settings"]

    r = await client.get("/api/trend?months=6")
    body = r.json()
    assert body["months"]
    m = body["months"][-1]
    assert "income" in m and "expense" in m and "net" in m
    assert m["income"] > 0 and m["expense"] > 0


# ---------------------------------------------------------------------------
# 审查修复回归：边界 / 迁移 / 重置 / 鉴权
# ---------------------------------------------------------------------------


async def test_trend_bad_months(client) -> None:
    """months=0 / 负数不再触发 SQL LIMIT 0 崩溃，落到最小 1 个月。"""
    r0 = await client.get("/api/trend?months=0")
    assert r0.status_code == 200 and len(r0.json()["months"]) >= 1
    rn = await client.get("/api/trend?months=-5")
    assert rn.status_code == 200 and len(rn.json()["months"]) >= 1
    rb = await client.get("/api/trend?months=999")
    assert rb.status_code == 200 and len(rb.json()["months"]) <= 24


async def test_transaction_bad_amount_and_date(client) -> None:
    """金额非数字 / 日期格式非法返回 400，而不是 500。"""
    r = await client.post(
        "/api/transactions",
        json={
            "date": "2026-09-25",
            "item": "坏金额",
            "category": "餐饮",
            "amount": "abc",
        },
    )
    assert r.status_code == 400
    r = await client.post(
        "/api/transactions",
        json={
            "date": "2026/09/25",
            "item": "坏日期",
            "category": "餐饮",
            "amount": -66,
        },
    )
    assert r.status_code == 400
    r = await client.post(
        "/api/transactions",
        json={
            "date": "2026-09-25",
            "item": "零金额",
            "category": "餐饮",
            "amount": 0,
        },
    )
    assert r.status_code == 400
    # 合法请求仍成功
    r = await client.post(
        "/api/transactions",
        json={
            "date": "2026-09-25",
            "item": "正常",
            "category": "餐饮",
            "amount": -66,
        },
    )
    assert r.status_code == 200


async def test_migrate_sessions_from_runs(client) -> None:
    """旧库：已有 runs 但无 sessions，启动时应迁移出会话，标题取首问。"""
    # 模拟旧版本库：runs 存在但 sessions 表无对应记录（绕过 save_run 的自动登记）
    tid = "legacy-thread-1"
    conn = await db._conn()
    for q, a in (("第一个问题", "x"), ("第二个问题", "y")):
        await conn.execute(
            "INSERT INTO runs(thread_id,question,answer,level,flags_json,created_at)"
            " VALUES(?,?,?,?,?,?)",
            (tid, q, a, "L2 建议", "[]", "2026-09-01T08:00:00+08:00"),
        )
    await conn.commit()
    await db._migrate_sessions_from_runs()
    sess = await db.list_sessions()
    match = [s for s in sess if s["thread_id"] == tid]
    assert match and match[0]["title"] == "第一个问题"


async def test_reset_to_seed_keeps_data_note(client) -> None:
    """恢复示例数据后，data_note 仍保持 seed 标记，不应误报用户数据。"""
    r = await client.post(
        "/api/transactions",
        json={
            "date": "2026-09-25",
            "item": "临时",
            "category": "餐饮",
            "amount": -10,
        },
    )
    assert r.status_code == 200
    d = (await client.get("/api/dashboard")).json()
    assert d["source"]["seeded"] is False

    r = await client.post("/api/portfolio/reset")
    assert r.status_code == 200
    d = (await client.get("/api/dashboard")).json()
    assert d["source"]["seeded"] is True
    assert d["positions"]  # 种子持仓仍在


async def test_reset_to_seed_preserves_user_settings(client) -> None:
    """恢复示例数据只换数据：用户设置（AI 配置 / Agent 配置 / 偏好）一律保留。

    回归：此前 reset 会 DELETE 整张 settings 表——「恢复示例数据」把用户填的
    模型密钥、Agent 技能开关与偏好一起清掉（e2e 复用在跑服务时污染研发库）。
    """
    await client.put(
        "/api/settings",
        json={"settings": {"report_time": "22:10", "monthly_income": 12345}},
    )
    # 改一条 Agent 配置（关闭长期记忆技能）
    cfg = (await client.get("/api/agent-config")).json()["config"]
    cfg["skills"]["long_memory"]["enabled"] = False
    r = await client.post("/api/agent-config", json={"config": cfg})
    assert r.status_code == 200

    r = await client.post("/api/portfolio/reset")
    assert r.status_code == 200

    st = (await client.get("/api/settings")).json()["settings"]
    assert st["report_time"] == "22:10"
    assert st["monthly_income"] == "12345"
    cfg2 = (await client.get("/api/agent-config")).json()["config"]
    assert cfg2["skills"]["long_memory"]["enabled"] is False
    # 数据确实换回了种子
    d = (await client.get("/api/dashboard")).json()
    assert d["source"]["seeded"] is True and d["positions"]


async def test_deleting_all_positions_does_not_reseed(client, monkeypatch) -> None:
    """用户清空全部持仓后重启服务，不得重新灌入种子数据。"""
    for p in await db.list_positions():
        await db.delete_position(p["symbol"])
    d = (await client.get("/api/dashboard")).json()
    assert d["positions"] == []

    # 模拟重启：重新 init_db（settings 表已有数据，不应触发 seed）
    await db.close_db()
    await db.init_db()
    d = (await client.get("/api/dashboard")).json()
    assert d["positions"] == []


async def test_api_token_auth(client, monkeypatch) -> None:
    """设置 API_TOKEN 后：未带口令 401，带 query token 200。"""
    monkeypatch.setenv("API_TOKEN", "secret-review")
    # 首次请求已发生 token 相关初始化，直接验证 401 分支
    r = await client.get("/api/health")
    assert r.status_code == 200  # health 不做鉴权

    r = await client.get("/api/dashboard")
    assert r.status_code == 401
    r = await client.get("/api/dashboard?token=secret-review")
    assert r.status_code == 200


async def test_csv_import_commits_all_rows_not_preview(client) -> None:
    """CSV 超过 15 行：预览截断，但提交接口必须能拿到并导入全部行。"""
    header = "交易时间,收/支,交易对方,金额\n"
    rows = "".join(
        f"2026-09-{(i % 28) + 1:02d} 12:00:00,支出,商户{i},10.00\n" for i in range(20)
    )
    r = await client.post("/api/import/csv", json={"content": header + rows, "source": "generic"})
    assert r.status_code == 200, r.text
    d = r.json()
    preview = d["preview"]
    assert preview["summary"]["count"] == 20
    # 新实现不截断预览，所有行一次性返回
    assert len(preview["transactions"]) == 20

    r2 = await client.post("/api/import/csv/confirm", json={"transactions": preview["transactions"]})
    assert r2.status_code == 200, r2.text
    # 同一日期+商户名不同（商户0~19），不存在重复 → 全部导入
    assert r2.json()["imported"] == 20


async def test_generic_csv_import_path_not_shadowed(client) -> None:
    """回归：通用 CSV 预览必须挂在 /api/import/generic，不被源感知解析遮蔽。

    历史 bug：两个路由同名 /api/import/csv，源感知版本先注册导致通用解析永远不可达，
    前端 EntryView 的通用导入因此拿到错误响应结构。
    """
    csv_text = "日期,项目,分类,金额\n2026-09-01,午饭,餐饮,-28\n2026-09-02,工资,收入,10000\n"
    r = await client.post("/api/import/generic", json={"content": csv_text})
    assert r.status_code == 200, r.text
    d = r.json()
    # 通用解析的契约：columns/mapping/rows/total/skipped（EntryView 按此消费）
    for key in ("columns", "mapping", "preview", "rows", "total", "skipped"):
        assert key in d, f"缺少字段 {key}"
    assert d["total"] == 2 and len(d["rows"]) == 2

    # /api/import/csv 仍由源感知解析提供（契约不变：preview.transactions）
    r2 = await client.post("/api/import/csv", json={"content": csv_text, "source": "generic"})
    assert r2.status_code == 200, r2.text
    assert "transactions" in r2.json()["preview"]


async def test_regenerate_targets_matching_question(client) -> None:
    """重新生成指定问题：只替换该问题的最近一条，不误删线程最后一条。"""
    tid = "regen-target"
    for q in ("第一个问题", "第二个问题"):
        async with client.stream(
            "POST", "/api/ask", json={"question": q, "thread_id": tid}
        ) as resp:
            await resp.aread()
    # 对"第一个问题"重新生成
    async with client.stream(
        "POST",
        "/api/ask",
        json={"question": "第一个问题", "thread_id": tid, "regenerate": True},
    ) as resp:
        await resp.aread()
    runs = (await client.get(f"/api/history?thread_id={tid}")).json()["runs"]
    assert len(runs) == 2, "总数不变：替换而非追加"
    questions = [r["question"] for r in runs]
    assert questions.count("第一个问题") == 1
    assert questions.count("第二个问题") == 1, "最后一条（第二个问题）必须保留"


async def test_export_masks_ai_key(client) -> None:
    """全量导出不得携带 AI Key 明文（备份文件可能被分享/上传）。"""
    await client.put(
        "/api/settings",
        json={
            "settings": {
                "ai_enabled": "on",
                "ai_base_url": "https://api.example.com/v1",
                "ai_api_key": "sk-export-test",
                "ai_model": "test-model",
            }
        },
    )
    body = (await client.get("/api/export")).json()
    assert body["settings"]["ai_api_key"] != "sk-export-test"
    assert body["settings"]["ai_api_key"] == "********"


# ---------------------------------------------------------------------------
# 审查修复回归：无口令模式的跨站/Host 防护、预算去重、设置键
# ---------------------------------------------------------------------------


async def test_no_token_mode_blocks_foreign_host(client, monkeypatch) -> None:
    """未设口令时：外部 Host（DNS rebinding）与跨站 Origin 一律 403，本机放行。"""
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)

    r = await client.get("/api/dashboard", headers={"host": "evil.example"})
    assert r.status_code == 403

    r = await client.get("/api/dashboard", headers={"origin": "https://evil.example"})
    assert r.status_code == 403

    r = await client.get("/api/dashboard")
    assert r.status_code == 200

    # health 始终免检
    r = await client.get("/api/health", headers={"host": "evil.example"})
    assert r.status_code == 200


async def test_allowed_hosts_env_override(client, monkeypatch) -> None:
    """ALLOWED_HOSTS 显式白名单可放行内网主机名部署。"""
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.setenv("ALLOWED_HOSTS", "nas.local,10.0.0.5")

    r = await client.get("/api/dashboard", headers={"host": "nas.local:8787"})
    assert r.status_code == 200
    r = await client.get("/api/dashboard", headers={"host": "other.example"})
    assert r.status_code == 403


async def test_token_mode_skips_host_check(client, monkeypatch) -> None:
    """已设口令时以口令为准，Host 白名单不再拦截反代部署。"""
    monkeypatch.setenv("API_TOKEN", "secret-review")
    r = await client.get("/api/dashboard", headers={"host": "wealth.example.com"})
    assert r.status_code == 401
    r = await client.get(
        "/api/dashboard",
        headers={"host": "wealth.example.com", "authorization": "Bearer secret-review"},
    )
    assert r.status_code == 200


async def test_budget_duplicate_category_is_upsert(client) -> None:
    """同月重复分类不得触发主键冲突 500，后一项覆盖前一项。"""
    month = datetime.now().astimezone().strftime("%Y-%m")
    r = await client.put(
        "/api/budgets",
        json={
            "month": month,
            "budgets": [
                {"category": "餐饮", "amount": 500},
                {"category": "餐饮", "amount": 800},
            ],
        },
    )
    assert r.status_code == 200
    d = (await client.get(f"/api/budgets?month={month}")).json()
    cats = {c["category"]: c for c in d["usage"]["categories"]}
    assert cats["餐饮"]["budget"] == 800


async def test_essential_categories_trimmed(client) -> None:
    """分类名两侧空白不得让必要支出漏算（应急金口径）。"""
    r = await client.put(
        "/api/settings",
        json={"settings": {"essential_categories": "居住, 餐饮 ,  交通"}},
    )
    assert r.json()["errors"] == []
    st = (await client.get("/api/settings")).json()["settings"]
    assert st["essential_categories"] == "居住,餐饮,交通"


async def test_settings_batch_save_keys_all_valid(client) -> None:
    """前端「保存设置」提交的键集合必须全部被后端接受（不得再报未知配置项）。"""
    r = await client.put(
        "/api/settings",
        json={
            "settings": {
                "monthly_income": "30000",
                "emergency_target_months": "6",
                "essential_categories": "居住,餐饮,交通",
                "savings_goal": "20",
                "report_time": "08:00",
            }
        },
    )
    assert r.status_code == 200
    assert r.json()["errors"] == []


async def test_nl_add_invalid_date_not_500(client) -> None:
    """一句话记账遇到日历非法日期应回退今天入账，而不是 500。"""
    r = await client.post("/api/nl-add", json={"text": "2026年13月40日 打车10元"})
    assert r.status_code == 200
    assert r.json()["transaction"]["amount"] == -10

"""Agent 工具调用层单测：工具执行、工具循环、降级路径。

不触网：httpx.MockTransport 假冒 OpenAI 兼容端点（含 function calling 回包）。
"""

from __future__ import annotations

import json

import httpx
import pytest
from app import agent, db, llm, tools


def _chat_resp(content: str | None = None, tool_calls: list[dict] | None = None) -> httpx.Response:
    msg: dict = {"role": "assistant"}
    if content is not None:
        msg["content"] = content
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return httpx.Response(200, json={"choices": [{"message": msg, "finish_reason": "stop"}]})


def _tc(name: str, arguments: dict, call_id: str = "call_1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }


def _inject(monkeypatch, handler) -> None:
    """注入 mock LLM：让 litellm.acompletion 走 MockTransport，返回 litellm 兼容形态的响应。

    区分 stream=True（返回异步 chunk 迭代器）和 stream=False（返回含 choices 的响应对象）。
    错误 ≥400 → 抛 RuntimeError（create 捕获 → 重试/兜底）。
    """
    from types import SimpleNamespace

    import litellm

    async def _mock_acompletion(**kwargs):
        stream = kwargs.get("stream", False)
        import httpx as _httpx
        http_client = _httpx.AsyncClient(transport=_httpx.MockTransport(handler))
        api_base = kwargs.get("api_base") or "http://mock.invalid/v1"
        send_kwargs = {k: v for k, v in kwargs.items() if k not in ("api_base", "api_key", "num_retries", "client", "stream_timeout", "timeout")}
        req = http_client.build_request(
            "POST",
            f"{api_base}chat/completions",
            json=send_kwargs,
            headers={"Authorization": f"Bearer {kwargs.get('api_key', '')}"},
        )
        resp = await http_client.send(req)
        await http_client.aclose()

        if resp.status_code >= 400:
            raise RuntimeError(f"mock {resp.status_code}: {resp.content[:200]!r}")

        if stream:
            raw = resp.content.decode("utf-8", errors="replace")
            chunks: list[SimpleNamespace] = []

            # 如果 handler 返回的是 JSON（非 SSE），把 content 合成为单个 chunk
            # （兼容那些只返回 JSON 的 handler，如 _chat_resp）
            content_type = resp.headers.get("content-type", "")
            if "event-stream" not in content_type:
                try:
                    data = json.loads(raw)
                    content = data["choices"][0]["message"].get("content")
                    if content:
                        chunks.append(
                            SimpleNamespace(
                                choices=[SimpleNamespace(delta=SimpleNamespace(content=content), index=0, finish_reason="stop")],
                            ),
                        )
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass
            else:
                for line in raw.split("\n"):
                    if not line.startswith("data: "):
                        continue
                    payload = line[len("data: "):].strip()
                    if payload == "[DONE]":
                        continue
                    try:
                        item = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    for choice in item.get("choices", []):
                        delta = choice.get("delta") or {}
                        content = delta.get("content")
                        chunks.append(
                            SimpleNamespace(
                                choices=[
                                    SimpleNamespace(
                                        delta=SimpleNamespace(content=content),
                                        index=0,
                                        finish_reason=choice.get("finish_reason"),
                                    ),
                                ],
                            ),
                        )

            async def _gen():
                for chunk in chunks:
                    yield chunk
            return _gen()

        data = json.loads(resp.content)

        def _build_msg(msg: dict) -> SimpleNamespace:
            tool_calls = None
            if msg.get("tool_calls"):
                tool_calls = [
                    SimpleNamespace(
                        id=tc.get("id", f"call_{i}"),
                        type="function",
                        function=SimpleNamespace(
                            name=tc["function"]["name"],
                            arguments=tc["function"]["arguments"],
                        ),
                    )
                    for i, tc in enumerate(msg["tool_calls"])
                ]
            return SimpleNamespace(
                content=msg.get("content"),
                tool_calls=tool_calls,
                role=msg.get("role", "assistant"),
            )

        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=_build_msg(c["message"]), finish_reason=c.get("finish_reason"))
                for c in data["choices"]
            ],
            model=data.get("model", kwargs.get("model", "")),
        )

    monkeypatch.setattr(litellm, "acompletion", _mock_acompletion)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    llm.invalidate()
    monkeypatch.setattr(llm, "_client_singleton", None)
    monkeypatch.setattr(llm, "_cfg", None)
    yield
    llm.invalidate()


# ---------------------------------------------------------------------------
# 工具执行体
# ---------------------------------------------------------------------------


async def test_tool_market_view_with_empty_positions(temp_db):
    # init_db 会播种示例数据；先清空持仓模拟"还没有持仓"
    await db.execute("DELETE FROM positions")
    out = json.loads(await tools.tool_get_market_view({}))
    assert out["empty"] is True


async def test_tool_record_transaction_parses(temp_db):
    out = json.loads(await tools.tool_record_transaction({"text": "昨天打车 32 元"}))
    assert out["ok"] is True
    assert out["amount"] == -32
    rows = await db.list_transactions()
    assert any(r["item"] == "打车" for r in rows)


async def test_tool_budget_shape(temp_db):
    out = json.loads(await tools.tool_get_budget({}))
    assert "month" in out and "budgets" in out


async def test_tool_kline_falls_back(temp_db, monkeypatch):
    async def _fake(symbol, period, limit):
        return {
            "symbol": symbol,
            "period": period,
            "source": "fake",
            "points": [{"date": "2026-09-01", "close": 10.0, "pct_change": 0.1}],
        }

    # tools.py 在模块加载时绑定 fetch_kline，须直接 patch tools 模块
    monkeypatch.setattr(tools, "fetch_kline", _fake)
    out = json.loads(await tools.tool_get_kline({"symbol": "600519"}))
    assert out["symbol"] == "600519" and out["points"]


async def test_truncate_tool_result():
    long = "x" * 5000
    out = tools.truncate_tool_result(long)
    assert len(out) <= tools.TOOL_RESULT_MAX_CHARS + 20


# ---------------------------------------------------------------------------
# 工具循环编排
# ---------------------------------------------------------------------------


async def test_agent_calls_tool_then_answers(temp_db, monkeypatch):
    """模型先要求查持仓 → 工具结果回填 → 模型成文。"""
    calls: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if not body.get("tools"):
            raise AssertionError("请求必须带 tools 定义")
        n_tool_msgs = sum(1 for m in body["messages"] if m["role"] == "tool")
        if n_tool_msgs == 0:
            return _chat_resp(tool_calls=[_tc("get_market_view", {})])
        return _chat_resp(content="你的持仓总市值 X 元。")

    _inject(monkeypatch, handler)
    llm._cfg = {
        "base": "http://mock.invalid/v1",
        "key": "sk-test",
        "model": "gpt-4o-mini",
        "provider": "openai",
        "litellm_model": "openai/gpt-4o-mini",
    }

    events: list[dict] = []

    async def emit(e: dict) -> None:
        events.append(e)

    result = await agent.run_agent("我的持仓怎么样", emit)
    assert result["answer"] == "你的持仓总市值 X 元。"
    assert result["tools_used"] == ["get_market_view"]
    # 工具结果确实回填给了模型（messages 里出现 role=tool 且内容非空）
    last = calls[-1]
    tool_msgs = [m for m in last["messages"] if m["role"] == "tool"]
    assert tool_msgs and json.loads(tool_msgs[0]["content"])["total_market_value"] >= 0
    # 过程事件：agent_step 已发出
    assert any(e["type"] == "agent_step" and e["name"] == "get_market_view" for e in events)


async def test_agent_direct_answer_no_tools(temp_db, monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return _chat_resp(content="这是闲聊，不需要工具。")

    _inject(monkeypatch, handler)
    llm._cfg = {"base": "http://mock.invalid/v1", "key": "sk-test", "model": "gpt-4o-mini", "provider": "openai", "litellm_model": "openai/gpt-4o-mini"}
    result = await agent.run_agent("你好", lambda e: _noop())
    assert result["answer"] == "这是闲聊，不需要工具。"
    assert result["tools_used"] == []


async def _noop() -> None:
    return None


async def test_agent_unavailable_without_config(temp_db):
    llm._cfg = {}
    with pytest.raises(agent.AgentUnavailable):
        await agent.run_agent("我的持仓怎么样", lambda e: _noop())


async def test_agent_unavailable_on_http_error(temp_db, monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "boom"}})

    _inject(monkeypatch, handler)
    llm._cfg = {"base": "http://mock.invalid/v1", "key": "sk-test", "model": "gpt-4o-mini", "provider": "openai", "litellm_model": "openai/gpt-4o-mini"}
    with pytest.raises(agent.AgentUnavailable):
        await agent.run_agent("我的持仓怎么样", lambda e: _noop())


async def test_agent_loop_cap(temp_db, monkeypatch):
    """模型每次都要求调工具 → 超过轮数上限抛 AgentUnavailable（防死循环）。"""
    n = {"turns": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        n["turns"] += 1
        return _chat_resp(tool_calls=[_tc("get_market_view", {})])

    _inject(monkeypatch, handler)
    llm._cfg = {"base": "http://mock.invalid/v1", "key": "sk-test", "model": "gpt-4o-mini", "provider": "openai", "litellm_model": "openai/gpt-4o-mini"}
    with pytest.raises(agent.AgentUnavailable):
        await agent.run_agent("我的持仓怎么样", lambda e: _noop())
    assert n["turns"] <= agent.MAX_TURNS + 1


async def test_agent_survives_unknown_tool(temp_db, monkeypatch):
    """模型调用未知工具 → 回填错误而非崩溃。"""
    async def handler(request: httpx.Request) -> httpx.Response:
        return _chat_resp(tool_calls=[_tc("not_a_real_tool", {})])

    _inject(monkeypatch, handler)
    llm._cfg = {"base": "http://mock.invalid/v1", "key": "sk-test", "model": "gpt-4o-mini", "provider": "openai", "litellm_model": "openai/gpt-4o-mini"}
    # 未知工具回填后模型未继续产出 → 本轮无内容 → AgentUnavailable（不崩溃即达标）
    with pytest.raises(agent.AgentUnavailable):
        await agent.run_agent("查一下", lambda e: _noop())


async def test_agent_memory_preinjected(temp_db, monkeypatch):
    """用户长期记忆预注入 system 消息：模型无需先调工具即可参考用户背景。"""
    await db.add_memory("明年计划买房，首付预算 30 万")
    captured: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured.append(body)
        return _chat_resp(content="了解，按你的买房计划看…")

    _inject(monkeypatch, handler)
    llm._cfg = {"base": "http://mock.invalid/v1", "key": "sk-test", "model": "gpt-4o-mini", "provider": "openai", "litellm_model": "openai/gpt-4o-mini"}
    result = await agent.run_agent("我该怎么为买房准备", lambda e: _noop())
    assert result["answer"] == "了解，按你的买房计划看…"
    sys_msgs = captured[0]["messages"]
    mem_sys = [m for m in sys_msgs if m["role"] == "system" and "明年计划买房" in m["content"]]
    assert mem_sys, "长期记忆应预注入 system 消息"


# ---------------------------------------------------------------------------
# 买入动作（run_action）：行情不可达降级提示补成本；行情可达按现价建仓
# ---------------------------------------------------------------------------


async def test_buy_without_quote_asks_for_cost(temp_db, monkeypatch):
    """行情源不可达时「买入 600519 100 股」应提示补成本，而不是报错。"""
    async def no_quote(_sym: str) -> dict | None:
        return None

    monkeypatch.setattr(tools, "quote_now", no_quote)
    before = {p["symbol"]: p["shares"] for p in await db.list_positions()}
    out = await tools.run_action("买入 600519 100 股")
    assert out["route"] == "action"
    assert out["level"] == "需要补充"
    assert "成本" in out["answer"]
    # 持仓未被误改（seed 里 600519 的份额保持不变）
    after = {p["symbol"]: p["shares"] for p in await db.list_positions()}
    assert after.get("600519") == before.get("600519")


async def test_buy_with_quote_records_position(temp_db, monkeypatch):
    """行情可达时「买入 600519 100 股」→ 生成待确认动作（HITL），确认后落库。"""
    async def with_quote(_sym: str) -> dict:
        return {"price": 1250.0, "name": "贵州茅台", "symbol": "600519"}

    monkeypatch.setattr(tools, "quote_now", with_quote)
    out = await tools.run_action("买入 600519 100 股")
    assert out["route"] == "action"
    assert out["level"] == "待确认"
    assert out["pending_token"]
    assert "600519" in out["answer"]
    # 确认前不落库（HITL 边界）：seed 已有 600519，成本不变
    before = next(p["cost"] for p in await db.list_positions() if p["symbol"] == "600519")
    assert before != 1250.0
    # 确认后执行
    pending = await db.get_pending_action(out["pending_token"])
    assert pending is not None and pending["tool_name"] == "record_position"
    ans = await tools.TOOL_IMPL["record_position"](pending["args"])
    # seed 里已有 600519 → 走追加语义（股数累加、成本加权平均）。
    # 覆盖语义会让「再买 100 股」把原持仓抹掉，是资金数据错误。
    assert "已追加买入" in ans
    await db.mark_pending_action(out["pending_token"], "consumed")
    # token 一次性：二次确认失效
    assert await db.get_pending_action(out["pending_token"]) is None
    # 确认后落库：原份额 + 100，成本为加权平均（不再是单一 1250）
    pos = next(p for p in await db.list_positions() if p["symbol"] == "600519")
    assert pos["shares"] > 100
    assert pos["cost"] != 1250.0 or pos["shares"] == 100


# ---------------------------------------------------------------------------
# 补充：设置白名单 / 自选增删 / 半仓卖出（工具执行体直达）
# ---------------------------------------------------------------------------


async def test_set_setting_rejects_unknown_key(temp_db):
    """tool_set_setting 只接受白名单键，未知键报错。"""
    out = await tools.tool_set_setting({"key": "not_a_key", "value": "1"})
    assert "不支持" in out or "未知" in out or "仅支持" in out


async def test_set_setting_applies_valid_key(temp_db):
    """合法键（color_scheme）写入设置。"""
    out = await tools.tool_set_setting({"key": "color_scheme", "value": "us"})
    assert "us" in out.lower() or "绿涨红跌" in out
    settings = await db.get_settings()
    assert settings.get("color_scheme") == "us"


async def test_watchlist_add_remove_roundtrip(temp_db):
    """自选增删往返（db API 名为 list/add/delete_watchlist）。"""
    await tools.tool_add_watchlist({"symbol": "600519", "name": "贵州茅台"})
    wl = await db.list_watchlist()
    assert any(w["symbol"] == "600519" for w in wl)
    await tools.tool_remove_watchlist({"symbol": "600519"})
    wl2 = await db.list_watchlist()
    assert all(w["symbol"] != "600519" for w in wl2)


async def test_sell_half_keeps_remainder(temp_db):
    """「卖出一半」：HITL 确认后份额减半、保留一半。"""
    before = {p["symbol"]: p["shares"] for p in await db.list_positions()}
    target = next((s for s in before if before[s] > 1), None)
    assert target, "seed 应有可减半持仓"
    out = await tools.run_action(f"卖出一半的 {target}")
    assert out["route"] == "action"
    # HITL：待确认后执行
    pending = await db.get_pending_action(out["pending_token"])
    ans = await tools.TOOL_IMPL[pending["tool_name"]](pending["args"])
    assert "已" in ans
    await db.mark_pending_action(out["pending_token"], "consumed")
    after = {p["symbol"]: p["shares"] for p in await db.list_positions()}
    assert after[target] == round(before[target] / 2, 4)


async def test_graph_hitl_resume_survives_memory_clear(temp_db, monkeypatch):
    """LangGraph 写操作 HITL 磁盘持久化：token→thread_id 与线程 checkpoint 落盘后，
    清空进程内存注册表（模拟进程重启），resume 仍能从磁盘恢复并确认落库。"""
    from app import agent_graph, service

    async def with_quote(_sym):
        return {"price": 1250.0, "name": "贵州茅台", "symbol": "600519"}

    async def _no_llm():
        return False

    monkeypatch.setattr(tools, "quote_now", with_quote)
    monkeypatch.setattr(service.llm, "llm_available", _no_llm)

    events: list = []

    async def emit(ev):
        events.append(ev)

    out = await service.run_question("买入 600519 100 股", emit, None, "zh")
    token = out.get("pending_token")
    assert token, "写操作应生成待确认 token"
    tid = await agent_graph._load_pending(token)
    assert tid, "token→thread_id 应已落盘(agent_pending.db)"

    # 模拟进程重启：内存注册表清空，只剩磁盘持久化（checkpoint + pending 映射）
    agent_graph._HITL_THREADS.clear()
    ans = await agent_graph.resume_action(token, "confirm")
    assert ans is not None and ans.get("level") == "已执行"
    # 追加语义：seed 已有 600519，再买 100 股 → 份额增加、成本为加权平均。
    # 断言「成本落在原成本与本次成交价之间」比断言具体数值更稳，也更贴合业务含义。
    pos = next(p for p in await db.list_positions() if p["symbol"] == "600519")
    assert pos["shares"] > 100
    assert min(1250.0, 1680.0) <= pos["cost"] <= max(1250.0, 1680.0)
    # token 已消费（一次性）
    assert await agent_graph._load_pending(token) is None


async def test_pending_token_expires_after_ttl(temp_db):
    """过期 token 不得从磁盘恢复（防止陈旧确认被误执行）。

    pending 表此前只增不删：用户反复触发写操作但不确认时无限增长，
    且过期 token 仍能被 resume。现在 _save_pending 顺手清理、
    _load_pending 按 TTL 过滤。
    """
    from app import agent_graph

    token = "expired-token-probe"
    await agent_graph._save_pending(token, "run-abc")
    # 未过期：能读到
    assert await agent_graph._load_pending(token) == "run-abc"

    # 把记录改成 31 分钟前，模拟过期
    def _age() -> None:
        c = agent_graph._pending_sql()
        c.execute(
            "UPDATE pending SET created_at=? WHERE token=?",
            ("2020-01-01T00:00:00", token),
        )
        c.commit()

    await agent_graph.asyncio.to_thread(_age)
    assert await agent_graph._load_pending(token) is None


async def test_save_pending_prunes_expired_rows(temp_db):
    """写入新 token 时应顺带清理过期行，避免表无限增长。"""
    from app import agent_graph

    def _insert_old() -> None:
        c = agent_graph._pending_sql()
        c.execute(
            "INSERT OR REPLACE INTO pending(token,thread_id,created_at) VALUES(?,?,?)",
            ("old-token", "run-old", "2020-01-01T00:00:00"),
        )
        c.commit()

    await agent_graph.asyncio.to_thread(_insert_old)
    await agent_graph._save_pending("new-token", "run-new")

    def _count_old() -> int:
        row = agent_graph._pending_sql().execute(
            "SELECT COUNT(*) FROM pending WHERE token='old-token'"
        ).fetchone()
        return int(row[0])

    assert await agent_graph.asyncio.to_thread(_count_old) == 0

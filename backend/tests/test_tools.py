"""tools 工具层覆盖测试：AI 会调用的确定性工具（行情/账本/风控/记账/目标/记忆/体检/自选）。

目标：把 tools.py 覆盖从 54% 拉上来（工具执行是「一句话工作流」的易错层），
行情一律走快照 mock，避免网络。
"""

from __future__ import annotations

import asyncio
import json

import pytest
from app import quotes as quotes_mod
from app import tools, tools_market, tools_system, tools_views


@pytest.fixture
def snap_quotes(monkeypatch):
    """行情走本地快照 + 单标的报价 mock，杜绝网络请求。"""

    async def _snap(positions):
        return {p["symbol"]: float(p["last"]) for p in positions}

    async def _quote(sym: str) -> dict:
        return {"symbol": sym, "price": 1250.0, "name": "演示", "last": 1250.0}

    monkeypatch.setattr(quotes_mod, "live_quotes", _snap)
    monkeypatch.setattr(quotes_mod, "quote_now", _quote)
    # 行情/持仓工具已拆到 tools_market，模块前缀绑定要替换到子模块上，
    # 只 patch quotes 模块属性不会影响它，否则测试会真的走网络。
    monkeypatch.setattr(tools_market, "quote_now", _quote)
    return _snap


def _loads(s: str):
    assert isinstance(s, str) and s
    return json.loads(s)


async def test_tool_market_view(snap_quotes, temp_db):
    out = _loads(await tools.tool_get_market_view({}))
    assert "total_market_value" in out


async def test_tool_ledger_view(snap_quotes, temp_db):
    out = _loads(await tools.tool_get_ledger_view({}))
    assert out.get("empty") is not True or "income" in out


async def test_tool_risk_flags(snap_quotes, temp_db):
    out = _loads(await tools.tool_get_risk_flags({}))
    assert "flags" in out and "count" in out


async def test_tool_budget(snap_quotes, temp_db):
    out = _loads(await tools.tool_get_budget({}))
    assert "month" in out and "budgets" in out


async def test_tool_trend(snap_quotes, temp_db):
    out = _loads(await tools.tool_get_trend({"months": 3}))
    assert isinstance(out, list)


async def test_tool_record_transaction(snap_quotes, temp_db):
    out = _loads(await tools.tool_record_transaction({"text": "买咖啡 28 元"}))
    assert out["ok"] is True
    assert out["item"] == "咖啡"


async def test_tool_record_transaction_missing_text(temp_db):
    assert await tools.tool_record_transaction({}) == "缺少 text 参数"


async def test_tool_get_goals(snap_quotes, temp_db):
    out = _loads(await tools.tool_get_goals({}))
    assert "empty" in out or isinstance(out, list)


async def test_tool_user_memory_roundtrip(snap_quotes, temp_db):
    saved = _loads(await tools.tool_save_user_memory({"content": "明年计划买房"}))
    assert saved["ok"] is True
    got = _loads(await tools.tool_get_user_memory({}))
    assert any(r["content"] == "明年计划买房" for r in got)
    # 缺少 content
    assert await tools.tool_save_user_memory({}) == "缺少 content 参数"


async def test_tool_health_check(snap_quotes, temp_db):
    out = _loads(await tools.tool_get_health_check({}))
    assert isinstance(out, dict)


async def test_tool_watchlist_roundtrip(snap_quotes, temp_db):
    await tools.tool_add_watchlist({"symbol": "600519", "name": "贵州茅台"})
    txt = await tools.tool_get_watchlist({})
    assert "600519" in txt or "贵州茅台" in txt
    await tools.tool_remove_watchlist({"symbol": "600519"})
    txt2 = await tools.tool_get_watchlist({})
    assert "600519" not in txt2


async def test_tool_get_quote(snap_quotes, temp_db):
    out = await tools.tool_get_quote({"symbol": "600519"})
    assert "600519" in out and "现价" in out


async def test_tool_kline_with_data(monkeypatch, snap_quotes, temp_db):
    async def fake_kline(symbol, period="daily", limit=60):
        return {
            "source": "mock",
            "points": [{"date": "2026-01-01", "close": 100.0, "pct_change": 0.5}] * 40,
        }

    monkeypatch.setattr(tools_views, "fetch_kline", fake_kline)
    out = _loads(await tools.tool_get_kline({"symbol": "600519"}))
    assert out["symbol"] == "600519" and out["points"]


async def test_tool_kline_missing_symbol():
    assert await tools.tool_get_kline({}) == "缺少 symbol 参数"


async def test_tool_kline_no_data(monkeypatch, snap_quotes, temp_db):
    async def empty_kline(symbol, period="daily", limit=60):
        return None

    monkeypatch.setattr(tools_views, "fetch_kline", empty_kline)
    assert "无法获取" in await tools.tool_get_kline({"symbol": "999999"})


async def test_tool_trigger_morning_report(monkeypatch, snap_quotes, temp_db):
    from app import scheduler

    async def fake_report() -> dict:
        return {"skipped": True, "answer": "", "level": "", "flags": []}

    monkeypatch.setattr(scheduler, "generate_report", fake_report)
    out = await tools.tool_trigger_morning_report({})
    assert "还没有足够" in out
    out_en = await tools.tool_trigger_morning_report({}, "en")
    assert "Not enough data" in out_en and "还没有" not in out_en


async def test_general_tools_registered() -> None:
    """通用技能包：领域无关工具（get_now/web_search），供 general 分支装配。"""
    names = {t["function"]["name"] for t in tools.GENERAL_TOOLS}
    assert names == {"get_now", "web_search"}
    assert set(tools.GENERAL_IMPL) == names
    assert callable(tools.GENERAL_IMPL["get_now"])
    assert callable(tools.GENERAL_IMPL["web_search"])
    # schema 合法：无多余 required，参数带说明
    ws = next(t for t in tools.GENERAL_TOOLS if t["function"]["name"] == "web_search")
    assert ws["function"]["parameters"]["required"] == ["q"]


async def test_unified_tool_registry_splits_skills() -> None:
    """统一技能注册表：财务/通用技能包由单一真源派生，互不混入。"""
    finance = {t["function"]["name"] for t in tools.FINANCE_TOOLS}
    general = {t["function"]["name"] for t in tools.GENERAL_TOOLS}
    # 财务与通用技能互斥
    assert not (finance & general)
    # 财务技能覆盖全部现有财务工具；通用技能为时间/搜索
    assert finance == {t["function"]["name"] for t in tools.TOOLS}
    assert general == {"get_now", "web_search"}
    # 注册表单一真源：每一项都带 schema/impl/mode
    assert set(tools.TOOL_REGISTRY) == finance | general
    assert all(r["mode"] in ("finance", "general") and r["schema"] and r["impl"]
               for r in tools.TOOL_REGISTRY.values())


async def test_get_now_returns_time() -> None:
    out = await tools.tool_get_now({})
    assert "现在是" in out and "20" in out


async def test_web_search_missing_query() -> None:
    out = await tools.tool_web_search({})
    assert "缺少搜索关键词" in out


async def test_web_search_fallback_on_search_failure(monkeypatch) -> None:
    """搜索库抛错必须兜底（返回提示），绝不抛错拖垮对话；不依赖真实网络。"""
    ddgs_module = tools._load_ddgs()

    class _BoomDDGS:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("boom")

    def _boom_search(q: str):
        raise RuntimeError("boom")

    # 搜索链已经是 Bing → 360 → DDGS；只打挂 DDGS 不会触发兜底，
    # 必须把前两级也模拟成不可用，才测得到「全部搜索源失败」的提示。
    monkeypatch.setattr(tools_system, "_bing_search", _boom_search)
    monkeypatch.setattr(tools_system, "_so_search", _boom_search)
    monkeypatch.setattr(ddgs_module, "DDGS", _BoomDDGS)
    out = await tools.tool_web_search({"q": "今天的新闻"})
    assert "暂时不可用" in out


async def test_deterministic_action_follows_language() -> None:
    """确定性动作回执（买入缺代码/确认、未识别、设置回执）按 lang 本地化，en 无中文。"""
    en_missing = await tools.run_action("买入", lang="en")
    assert "Buying needs a stock code" in en_missing["answer"]
    assert not any("\u4e00" <= ch <= "\u9fff" for ch in en_missing["answer"])
    assert en_missing["route_reason"] == "Buy instruction missing symbol"

    zh_missing = await tools.run_action("买入", lang="zh")
    assert "买入需要告诉我股票代码" in zh_missing["answer"]

    en_unknown = await tools.run_action("帮我查下天气", lang="en")
    assert "can't run that instruction directly" in en_unknown["answer"]
    assert en_unknown["route_reason"] == "Action instruction not matched"

    en_setting = await tools.tool_set_setting({"key": "not_a_key", "value": "1"}, "en")
    assert "Unsupported config key" in en_setting and "不支持" not in en_setting

async def test_web_search_preserves_event_loop_policy(monkeypatch) -> None:
    """DDGS 调用不得替换宿主事件循环策略。

    回归：duckduckgo_search 在 Windows 上 import 时会全局换成
    WindowsSelectorEventLoopPolicy，把 uvicorn/pytest-asyncio 的当前循环变成
    孤儿（表现为「unclosed event loop」+ 事件循环行为漂移）。
    用桩替换 DDGS，只验证策略不被换掉，不依赖真实网络。
    """
    ddgs_module = tools._load_ddgs()

    class _StubDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def text(self, *args, **kwargs):
            return [{"title": "t", "body": "b"}]

    monkeypatch.setattr(ddgs_module, "DDGS", _StubDDGS)
    policy_before = asyncio.get_event_loop_policy()
    out = await tools.tool_web_search({"q": "policy probe"})
    assert asyncio.get_event_loop_policy() is policy_before
    assert "搜索结果" in out


def test_ddgs_import_restores_policy_in_fresh_process() -> None:
    """子进程实测 import 副作用被立即恢复（修复前 Windows 上首次 import 必被换策略）。"""
    import subprocess
    import sys
    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[1]
    code = (
        "import asyncio\n"
        "from app import tools\n"
        "before = asyncio.get_event_loop_policy()\n"
        "module = tools._load_ddgs()\n"
        "after = asyncio.get_event_loop_policy()\n"
        "assert after is before, (type(after).__name__, type(before).__name__)\n"
        "assert callable(module.DDGS)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert proc.returncode == 0, proc.stderr

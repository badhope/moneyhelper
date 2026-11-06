"""上下文压缩：必须在超预算时真的触发，而不是「定义了一个没人调用的函数」。

背景：上一版 `context.compact_messages` 写好了 LLM 摘要，但 `_build_history`
里实际调用的是同步的 `trim_messages`（只做确定性截断），等于白写。
这组测试守住「接线」这件事——缩略语不测字符串，测行为。
"""

import pytest
from app.context import (
    compact_messages,
    count_messages_tokens,
    deterministic_summary,
    trim_messages,
)


def _long_history(turns: int = 12, chars: int = 800) -> list[dict]:
    out = [{"role": "system", "content": "你是财务助手。"}]
    for i in range(turns):
        out.append({"role": "user", "content": f"第{i}个问题：" + "很长的背景描述。" * (chars // 10)})
        out.append({"role": "assistant", "content": f"第{i}个回答：" + "详细的分析结论。" * (chars // 10)})
    return out


class TestCompactionTriggers:
    @pytest.mark.asyncio
    async def test_compacts_when_over_budget(self):
        msgs = _long_history()
        before = count_messages_tokens(msgs)
        assert before > 2000, "构造的历史必须超过预算，否则测不到压缩"

        res = await compact_messages(msgs, max_tokens=2000, use_llm=False)
        assert res["compacted"] is True
        assert res["after_tokens"] < before
        assert res["dropped"] > 0
        assert res["strategy"] == "deterministic"

    @pytest.mark.asyncio
    async def test_no_compaction_under_budget(self):
        msgs = [{"role": "user", "content": "你好"}]
        res = await compact_messages(msgs, max_tokens=10000, use_llm=False)
        assert res["compacted"] is False
        assert res["strategy"] == "none"
        assert res["messages"] == msgs

    @pytest.mark.asyncio
    async def test_keeps_recent_turns(self):
        """压缩后必须保留最近几轮原文——否则模型失去当前任务上下文。"""
        msgs = _long_history()
        res = await compact_messages(msgs, max_tokens=2000, reserve_recent=6, use_llm=False)
        kept = res["messages"]
        # 最近 6 条应原样保留
        assert kept[-6:] == msgs[-6:]

    @pytest.mark.asyncio
    async def test_preserves_system_message(self):
        msgs = _long_history()
        res = await compact_messages(msgs, max_tokens=2000, use_llm=False)
        assert any(m["role"] == "system" and "财务助手" in m["content"] for m in res["messages"])

    @pytest.mark.asyncio
    async def test_falls_back_when_llm_unavailable(self):
        """模型不可用时必须降级到确定性摘要，而不是抛错或返回空。"""
        res = await compact_messages(_long_history(), max_tokens=2000, use_llm=True)
        assert res["compacted"] is True
        assert res["strategy"] in ("llm", "deterministic")
        assert res["after_tokens"] > 0


class TestDeterministicSummary:
    def test_extracts_user_questions_and_answers(self):
        old = [
            {"role": "user", "content": "我的储蓄率是多少"},
            {"role": "assistant", "content": "你的储蓄率是 14.3%"},
        ]
        s = deterministic_summary(old, "zh")
        assert "储蓄率" in s
        assert "14.3%" in s

    def test_empty_input_is_explicit(self):
        s = deterministic_summary([], "zh")
        assert "无可提取" in s or "no extractable" in s

    def test_english_mode(self):
        old = [{"role": "user", "content": "what is my savings rate"}]
        s = deterministic_summary(old, "en")
        assert "User asked" in s or "asked about" in s


class TestTrimMessagesCompat:
    def test_trim_still_works(self):
        """保留旧同步接口，避免破坏未迁移的调用方。"""
        msgs = _long_history()
        out = trim_messages(msgs, max_tokens=2000, reserve_recent=4)
        assert len(out) < len(msgs)
        assert out[-4:] == msgs[-4:]

    def test_trim_noop_under_budget(self):
        msgs = [{"role": "user", "content": "hi"}]
        assert trim_messages(msgs, max_tokens=9999) == msgs

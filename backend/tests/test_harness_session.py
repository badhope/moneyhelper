"""harness 能力：会话 token 计量与会话分叉。

对齐 opencode / codex 这类 agent harness 的两个基础能力：
  - 上下文用量可见（每轮 token 由模型真实回传，落库可查）
  - 会话可从历史某点分叉（复制该轮及之前的历史，各自独立演化）

这里断言的是「行为」：计量口径、分叉边界、越权不复制。
"""

import pytest
from app import db


async def _seed(thread_id: str, pairs, tokens=None):
    """写入若干轮问答，tokens 可选按轮指定 (in, out)。"""
    ids = []
    for i, (q, a) in enumerate(pairs):
        tin, tout = (tokens[i] if tokens and i < len(tokens) else (0, 0))
        r = await db.save_run(
            thread_id=thread_id, question=q, answer=a, level="L1",
            route="ledger", llm="test", tokens={"prompt": tin, "completion": tout},
        )
        ids.append(r["id"])
    return ids


@pytest.mark.asyncio
async def test_session_usage_sums_tokens_and_counts_turns():
    tid = "usage-1"
    await _seed(tid, [("q1", "a1"), ("q2", "a2")], tokens=[(100, 20), (150, 30)])
    usage = await db.session_usage(tid)
    assert usage["turns"] == 2
    assert usage["tokens_in"] == 250
    assert usage["tokens_out"] == 50
    assert usage["tokens_total"] == 300


@pytest.mark.asyncio
async def test_session_usage_zero_for_unknown_thread():
    usage = await db.session_usage("nope-usage")
    assert usage["turns"] == 0
    assert usage["tokens_total"] == 0


@pytest.mark.asyncio
async def test_template_turns_keep_zero_tokens():
    """模板降级轮（无模型）不产生 token，不能凭空计数。"""
    tid = "usage-template"
    await _seed(tid, [("q", "a")])  # 不传 tokens
    usage = await db.session_usage(tid)
    assert usage["tokens_in"] == 0
    assert usage["tokens_out"] == 0


@pytest.mark.asyncio
async def test_fork_copies_up_to_the_chosen_run():
    tid = "fork-src"
    ids = await _seed(tid, [("q1", "a1"), ("q2", "a2"), ("q3", "a3")],
                      tokens=[(10, 1), (20, 2), (30, 3)])
    forked = await db.fork_session(tid, ids[1])  # 从第 2 轮分叉
    assert forked and forked["copied"] == 2
    runs = await db.list_runs(forked["thread_id"])
    assert [r["question"] for r in reversed(runs)] == ["q1", "q2"]


@pytest.mark.asyncio
async def test_fork_preserves_tokens():
    tid = "fork-tokens"
    ids = await _seed(tid, [("q1", "a1")], tokens=[(77, 7)])
    forked = await db.fork_session(tid, ids[0])
    usage = await db.session_usage(forked["thread_id"])
    assert usage["tokens_in"] == 77
    assert usage["tokens_out"] == 7


@pytest.mark.asyncio
async def test_fork_rejects_run_from_another_thread():
    """run_id 不属于该会话时不得复制任何数据（防越权/串号）。"""
    a = "fork-a"
    b = "fork-b"
    ids_a = await _seed(a, [("qa", "aa")])
    await _seed(b, [("qb", "bb")])
    assert await db.fork_session(b, ids_a[0]) is None


@pytest.mark.asyncio
async def test_fork_does_not_touch_source_session():
    tid = "fork-immutable"
    ids = await _seed(tid, [("q1", "a1"), ("q2", "a2")])
    await db.fork_session(tid, ids[0])
    runs = await db.list_runs(tid)
    assert len(runs) == 2  # 源会话轮次不变

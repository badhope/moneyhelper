"""回答依据与反馈：来源只列真实命中，反馈只改自己的 run。"""

from __future__ import annotations

import pytest
from app import db
from app.qa_sources import collect_sources, knowledge_sources, web_sources


def test_web_sources_extracts_dedupes_and_filters_localhost():
    answer = (
        "参考 https://example.com/a。另见 https://example.com/a#x 和 "
        "http://127.0.0.1:8099/private，最后是 https://docs.python.org/3/。"
    )
    out = web_sources(answer)
    assert [s["url"] for s in out] == ["https://example.com/a", "https://docs.python.org/3/"]
    assert out[0]["kind"] == "web"
    assert out[0]["title"] == "example.com"


@pytest.mark.asyncio
async def test_knowledge_sources_dedupes_same_document(monkeypatch):
    docs = [
        {
            "id": 7,
            "filename": "2026 预算说明.txt",
            "content": "预算说明：必要支出包括房租、餐饮和交通。" * 8,
        },
        {
            "id": 8,
            "filename": "旅行清单.txt",
            "content": "旅行清单：护照、充电器、雨伞。",
        },
    ]

    async def _docs():
        return docs

    async def _settings():
        return {"knowledge_enabled": "on"}

    monkeypatch.setattr(db, "list_indexed_attachments", _docs)
    monkeypatch.setattr(db, "get_settings", _settings)
    out = await knowledge_sources("预算里的必要支出怎么算")
    assert out
    assert out[0]["kind"] == "knowledge"
    assert out[0]["attachment_id"] == 7
    assert out[0]["title"] == "2026 预算说明.txt"
    # 同一文档多个 chunk 只保留一条，避免依据面板被同一份文件刷满。
    assert len({s["attachment_id"] for s in out}) == len(out)


@pytest.mark.asyncio
async def test_collect_sources_keeps_knowledge_before_web(monkeypatch):
    async def _kb(_q):
        return [{"kind": "knowledge", "title": "预算说明.txt", "attachment_id": 1}]

    def _web(_a):
        return [{"kind": "web", "title": "example.com", "url": "https://example.com"}]

    import app.qa_sources as qs

    monkeypatch.setattr(qs, "knowledge_sources", _kb)
    monkeypatch.setattr(qs, "web_sources", _web)
    out = await collect_sources("q", "a")
    assert [s["kind"] for s in out] == ["knowledge", "web"]


@pytest.mark.asyncio
async def test_feedback_is_tenant_scoped_and_summarized(temp_db):
    run = await db.save_run(
        "t-feedback",
        "本月花了多少",
        "本月支出 100 元",
        "L1",
    )
    saved = await db.save_run_feedback(run["id"], -1, "数字不对")
    assert saved is not None
    assert saved["feedback_rating"] == -1
    assert saved["feedback_reason"] == "数字不对"

    summary = await db.feedback_summary()
    assert summary["total"] == 1
    assert summary["negative"] == 1
    assert summary["satisfaction_pct"] == 0.0
    assert summary["top_reasons"][0] == {"reason": "数字不对", "count": 1}

    # 撤销后不再计入汇总；rating=0 是撤销而不是第三条评价。
    await db.save_run_feedback(run["id"], 0, "")
    summary = await db.feedback_summary()
    assert summary["total"] == 0


@pytest.mark.asyncio
async def test_feedback_rejects_unknown_run_and_bad_rating(temp_db):
    with pytest.raises(ValueError):
        await db.save_run_feedback(999999, 2, "x")
    assert await db.save_run_feedback(999999, 1, "") is None


@pytest.mark.asyncio
async def test_sources_survive_run_history(temp_db):
    sources = [
        {"kind": "knowledge", "title": "预算说明.txt", "attachment_id": 3},
        {"kind": "web", "title": "example.com", "url": "https://example.com/a"},
    ]
    await db.save_run("t-sources", "问题", "回答", "L1", sources=sources)
    runs = await db.list_runs("t-sources")
    assert runs[0]["sources"] == sources
    assert runs[0]["feedback_rating"] == 0

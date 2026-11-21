"""`search_symbol` 与 `/api/search` 必须同一口径。

症状：网页搜"茅台"能出结果，对话里问"茅台代码多少"却回答"没找到"。
根因不是网络，是两份解析：路由那份按顶层 `QuotationCodeTable` 修过，
工具那份还停在 `{"data": {...}}`，于是永远解析出空列表。
这个测试锁死"工具也认顶层形态"，防止再次分叉。
"""

from __future__ import annotations

import pytest
from app.tools_market import tool_search_symbol

REAL_SHAPE = {
    "QuotationCodeTable": {
        "Data": [
            {"Code": "600519", "Name": "贵州茅台", "SecurityTypeName": "沪A"},
            {"Code": "000858", "Name": "五粮液", "SecurityTypeName": "深A"},
        ]
    }
}


@pytest.fixture(autouse=True)
async def _auto_temp_db(temp_db):
    yield


async def test_search_symbol_parses_top_level_shape(monkeypatch):
    from app.connect import search_suggest

    async def fake_fetch(kw: str, timeout: float = 4.0):  # noqa: ARG001
        return REAL_SHAPE

    monkeypatch.setattr(search_suggest, "fetch_suggest", fake_fetch)
    out = await tool_search_symbol({"query": "茅台"})
    assert "贵州茅台（600519，股票）" in out
    assert "五粮液（000858，股票）" in out


async def test_search_symbol_no_hit_is_explicit(monkeypatch):
    from app.connect import search_suggest

    async def fake_fetch(kw: str, timeout: float = 4.0):  # noqa: ARG001
        return {"QuotationCodeTable": {"Data": []}}

    monkeypatch.setattr(search_suggest, "fetch_suggest", fake_fetch)
    out = await tool_search_symbol({"query": "不存在的标的"})
    assert "没有找到" in out


async def test_search_symbol_network_error_is_explicit(monkeypatch):
    from app.connect import search_suggest

    async def boom(kw: str, timeout: float = 4.0):  # noqa: ARG001
        raise RuntimeError("net down")

    monkeypatch.setattr(search_suggest, "fetch_suggest", boom)
    out = await tool_search_symbol({"query": "茅台"})
    assert "搜索服务暂时不可用" in out

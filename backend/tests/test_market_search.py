"""行情搜索解析回归：东财 suggest 的响应没有外层 data。

此前按 {"data": {"QuotationCodeTable": ...}} 解析，实际返回是顶层
{"QuotationCodeTable": ...}，导致搜索永远返回空列表（前端显示"没找到"）。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
async def _auto_temp_db(temp_db):
    """保持原文件的 autouse 语义：本文件每个用例都跑在临时库上。

    `_temp_db` 转发版已收敛到 conftest；此处只保留「自动生效」这一行为差异。
    """
    yield


@pytest.mark.parametrize(
    "payload",
    [
        # 真实返回：顶层就有 QuotationCodeTable
        {
            "QuotationCodeTable": {
                "Data": [
                    {
                        "Code": "600519",
                        "Name": "贵州茅台",
                        "SecurityTypeName": "沪A",
                    }
                ]
            }
        },
        # 兼容旧格式：外面多包一层 data
        {
            "data": {
                "QuotationCodeTable": {
                    "Data": [
                        {
                            "Code": "600519",
                            "Name": "贵州茅台",
                            "SecurityTypeName": "沪A",
                        }
                    ]
                }
            }
        },
    ],
)
async def test_search_parses_both_payload_shapes(client, monkeypatch, payload) -> None:
    from app.routes import market

    async def fake_fetch(kw: str) -> dict:  # noqa: ARG001
        return payload

    monkeypatch.setattr(market, "_fetch_suggest", fake_fetch)
    r = await client.get("/api/search", params={"q": "600519"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert items == [{"symbol": "600519", "name": "贵州茅台", "kind": "股票"}]


async def test_search_empty_query_returns_empty(client) -> None:
    r = await client.get("/api/search", params={"q": "   "})
    assert r.json() == {"items": []}

"""端点健康门禁：所有无参端点都不得返回 5xx。

为什么需要这组测试：上一轮新增策略时单元测试全绿，但三个策略接口返回 500
（路由漏 import + 文案函数对新策略崩溃）。也发现 `/openapi.json` 本身 500
（`Response` 未 import，因为 `from __future__ import annotations` 让它在运行时
不报错，只在生成 schema 时炸）。

单测测「函数对不对」，这组测「接口活不活」。两者互补。

设计取舍：
  - 只打「无路径参数」的端点——带 {id} 的需要构造真实数据，扔给业务测试。
  - 空 body 的 POST 期望 4xx（参数缺失/非法），**不允许 5xx**（未捕获异常）。
  - 401/403 也算通过：鉴权拒绝是正常行为，不是崩。
"""

import json
import urllib.error
import urllib.request

import pytest


def _openapi() -> dict:
    from app.main import app

    return app.openapi()


def test_openapi_schema_generates():
    """OpenAPI 必须能生成——它是 SDK 生成、前端类型、文档的共同源头。

    回归背景：`export.py` 的 `-> Response` 没 import Response，
    由于 `from __future__ import annotations`，运行时完全不报错，
    只有 FastAPI 生成 schema 时抛 PydanticUserError → /openapi.json 500。
    """
    schema = _openapi()
    assert schema["paths"], "OpenAPI 路径为空"
    assert len(schema["paths"]) > 100, f"路径数异常少：{len(schema['paths'])}"


def test_all_get_endpoints_have_summary_or_operation_id():
    """每个端点都该有可读的标识（否则生成的 SDK 方法名是一串路径）。"""
    schema = _openapi()
    missing = []
    for path, ops in schema["paths"].items():
        for method, op in ops.items():
            if method not in ("get", "post", "put", "delete", "patch"):
                continue
            if not (op.get("summary") or op.get("operationId")):
                missing.append(f"{method.upper()} {path}")
    # 允许少量历史端点缺失，但不能大面积
    assert len(missing) < 20, f"过多端点缺少 summary：{missing[:10]}"


class TestNoServerErrors:
    """用 ASGI transport 逐端点探测（比起真实服务快，且不依赖网络）。"""

    @pytest.mark.asyncio
    async def test_get_endpoints_never_500(self, client):
        paths = _openapi()["paths"]
        gets = sorted(p for p, ops in paths.items() if "get" in ops and "{" not in p)
        assert len(gets) > 50, "无参 GET 端点太少，探测覆盖不足"

        failures = []
        for p in gets:
            r = await client.get(p)
            if r.status_code >= 500:
                failures.append(f"{p} -> {r.status_code}: {r.text[:120]}")
        assert not failures, "以下端点返回 5xx：\n" + "\n".join(failures[:10])

    @pytest.mark.asyncio
    async def test_post_endpoints_reject_empty_body_gracefully(self, client):
        """空 body 应是 4xx（参数缺失），不能是 500（未捕获异常）。"""
        paths = _openapi()["paths"]
        posts = sorted(p for p, ops in paths.items() if "post" in ops and "{" not in p)
        assert len(posts) > 30

        failures = []
        for p in posts:
            r = await client.post(p, json={})
            if r.status_code >= 500:
                failures.append(f"{p} -> {r.status_code}: {r.text[:120]}")
        assert not failures, "以下 POST 端点空 body 时 5xx：\n" + "\n".join(failures[:10])


class TestValueErrorBecomes400:
    """db 层用 ValueError 表达「输入非法」，必须转成 400 而不是 500。"""

    @pytest.mark.asyncio
    async def test_empty_watchlist_symbol(self, client):
        r = await client.post("/api/watchlist", json={})
        assert r.status_code == 400, f"空 symbol 应 400，实际 {r.status_code}"
        assert r.json().get("error"), "400 必须带可读原因"

    @pytest.mark.asyncio
    async def test_error_message_is_readable(self, client):
        """用户要能看懂哪里错了，不能只看到「内部错误」。"""
        r = await client.post("/api/watchlist", json={})
        msg = r.json().get("error", "")
        assert "内部错误" not in msg
        assert len(msg) > 2


@pytest.fixture
async def client(temp_db):
    import httpx

    from app import main

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac

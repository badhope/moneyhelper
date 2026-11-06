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


# ---------------------------------------------------------------------------
# 升级探测：schema 派生的「有效」POST body
#
# 空 body 探测只能抓住「参数校验缺失→500」；抓不住「参数合法但实现有 bug」。
# 这里从 OpenAPI 的 requestBody schema 递归构造最小有效 body（required 字段 +
# 类型默认值 + 枚举首值），打到实现里去。
#
# 已知外呼/重副作用端点显式跳过，每个写明理由——这是允许的例外清单。
# ---------------------------------------------------------------------------

# schema 派生 body 会真实执行的端点里，这些会真实外呼或产生不可回滚副作用
VALID_BODY_SKIP = {
    "/api/connect/sync": "会真实拉取外部平台（东财/天天基金），探测环境无意义",
    "/api/backup": "会真实写备份包到数据目录",
    "/api/backup/restore": "会覆盖当前库——探测环境跑了也验证不了什么",
}


def _resolve_ref(spec: dict, ref: str) -> dict:
    node = spec
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    return node


def _example_value(spec: dict, schema: dict, depth: int = 0) -> object:
    """从 JSON Schema 构造最小可用值。不追求语义正确，只追求「能过校验进实现」。"""
    if depth > 8:  # 防循环引用
        return None
    if "$ref" in schema:
        return _example_value(spec, _resolve_ref(spec, schema["$ref"]), depth + 1)

    if schema.get("enum"):
        return schema["enum"][0]
    if "default" in schema:
        return schema["default"]
    if "example" in schema:
        return schema["example"]

    t = schema.get("type")
    if t == "object" or "properties" in schema:
        out = {}
        for k, sub in (schema.get("properties") or {}).items():
            required = k in (schema.get("required") or [])
            # 顶层（含 $ref 解开后的第一层）全字段都给——很多路由的手动校验
            # 字段不进 OpenAPI required（如 /api/ask 的 question），只给 required
            # 会大量假 4xx，探测覆盖度归零。嵌套对象只给 required（防误触发
            # 非默认分支的副作用）。
            if required or depth <= 1:
                out[k] = _example_value(spec, sub, depth + 1)
        return out
    if t == "array":
        item = schema.get("items") or {"type": "string"}
        return [_example_value(spec, item, depth + 1)]
    if t == "string":
        fmt = schema.get("format")
        if fmt in ("date",):
            return "2026-01-15"
        if fmt in ("date-time",):
            return "2026-01-15T08:00:00"
        if fmt == "time":
            return "08:00"
        if "pattern" in schema:
            return "abc123"
        return "test"
    if t == "number":
        return 100.0
    if t == "integer":
        return 1
    if t == "boolean":
        return True
    return None


class TestPostWithValidBodies:
    """schema 派生有效 body 的 POST 探测：抓「参数合法但实现炸」。"""

    @pytest.mark.asyncio
    async def test_valid_body_post_never_500(self, client):
        from app.main import app as _app

        spec = _app.openapi()

        posts = sorted(
            p for p, ops in spec["paths"].items()
            if "post" in ops and "{" not in p and p not in VALID_BODY_SKIP
        )
        assert len(posts) > 30

        failures = []
        for p in posts:
            body = {}
            rb = spec["paths"][p]["post"].get("requestBody")
            if rb:
                content = rb.get("content", {})
                js = (content.get("application/json") or {}).get("schema")
                if js:
                    body = _example_value(spec, js) or {}
            try:
                r = await client.post(p, json=body)
            except Exception as e:  # noqa: BLE001 — 探测自身异常也算端点故障
                failures.append(f"{p} -> 探测异常 {type(e).__name__}: {str(e)[:100]}")
                continue
            if r.status_code >= 500:
                failures.append(f"{p} -> {r.status_code}: {r.text[:140]}")
        assert not failures, (
            "以下 POST 端点在有效 body 下返回 5xx：\n" + "\n".join(failures[:12])
        )

    @pytest.mark.asyncio
    async def test_4xx_responses_are_readable(self, client):
        """4xx 的错误必须是用户能懂的文案，不能是空串、堆栈或内部细节。

        校验拒绝本身是好行为（上一轮 ValueError→400 的落点）；
        这里保证拒绝时用户拿到的是「代码需为 6 位数字」而不是
        「内部错误」或一段 traceback。
        """
        from app.main import app as _app

        spec = _app.openapi()
        posts = sorted(
            p for p, ops in spec["paths"].items()
            if "post" in ops and "{" not in p and p not in VALID_BODY_SKIP
        )

        bad = []
        for p in posts:
            body = {}
            rb = spec["paths"][p]["post"].get("requestBody")
            if rb:
                js = (rb.get("content", {}).get("application/json") or {}).get("schema")
                if js:
                    body = _example_value(spec, js) or {}
            r = await client.post(p, json=body)
            if r.status_code < 400:
                continue
            try:
                payload = r.json()
            except Exception:  # noqa: BLE001 — 4xx 必须是 JSON
                bad.append(f"{p} -> {r.status_code} 非 JSON: {r.text[:80]}")
                continue
            msg = ""
            if isinstance(payload, dict):
                msg = str(payload.get("error") or payload.get("detail") or payload.get("message") or "")
            if not msg.strip():
                bad.append(f"{p} -> {r.status_code} 错误信息为空: {str(payload)[:80]}")
            elif "Traceback" in msg or 'File "' in msg:
                bad.append(f"{p} -> {r.status_code} 错误信息含堆栈: {msg[:80]}")
        assert not bad, chr(10).join(["以下 4xx 的错误文案不合格：", *bad[:10]])

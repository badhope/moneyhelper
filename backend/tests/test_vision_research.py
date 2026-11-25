"""4.16.45：图片真正进入模型，而不是只落在工作台。

守两件事：
1. `/api/ask` 把图片的原始字节放进本轮 `images`，不是只传文件名；
2. 上下文装配把图片变成 OpenAI 兼容的 image_url 内容块，文本问题不丢。
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest
from app import main, service
from app.agent_context import build_turn_context

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+XK6cAAAAASUVORK5CYII="
)


@pytest.fixture
async def client(_temp_db):
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac


async def _upload_png(client: httpx.AsyncClient) -> int:
    r = await client.post(
        "/api/attachments",
        files={"file": ("截图.png", PNG_1PX, "image/png")},
    )
    assert r.status_code == 200, r.text
    return int(r.json()["id"])


async def _final_of_ask(client: httpx.AsyncClient, payload: dict) -> dict:
    async with client.stream("POST", "/api/ask", json=payload) as resp:
        body = (await resp.aread()).decode("utf-8")
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                continue
    return next(e for e in events if e.get("type") == "final")


async def test_ask_passes_image_bytes_to_generation(client, monkeypatch) -> None:
    aid = await _upload_png(client)
    captured: dict = {}

    async def fake_run_question(question: str, emit, **kwargs):
        captured.update(kwargs)
        return {
            "answer": "图里是一只测试像素。",
            "level": "ok",
            "flags": [],
            "route": "general",
            "route_reason": "vision",
            "metrics": {},
            "llm": "stub",
            "tools": [],
            "actions": [],
        }

    monkeypatch.setattr(service, "run_question", fake_run_question)
    final = await _final_of_ask(
        client,
        {
            "question": "图里有什么",
            "thread_id": "t-vision",
            # 前端真实载荷是对象数组，不是裸 id；这里锁住这个接口形状。
            "attachments": [{"id": aid, "filename": "截图.png", "kind": "image"}],
        },
    )
    assert final["answer"].startswith("图里")
    images = captured["images"]
    assert len(images) == 1
    assert images[0]["mime"] == "image/png"
    assert images[0]["data"]
    assert images[0]["filename"] == "截图.png"


async def test_context_builds_image_url_content(_temp_db) -> None:
    messages, _temperature, _settings = await build_turn_context(
        "这张截图说明了什么？",
        lang="zh",
        system="你是财务助手。",
        inject_memories=False,
        history=None,
        cfg={},
        images=[{"mime": "image/png", "data": "AAAA", "filename": "a.png"}],
    )
    user = messages[-1]
    assert user["role"] == "user"
    assert isinstance(user["content"], list)
    assert user["content"][0] == {"type": "text", "text": "这张截图说明了什么？"}
    assert user["content"][1]["type"] == "image_url"
    assert user["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert any("先读取图片里真实可见的信息" in str(m.get("content")) for m in messages)


async def test_canvas_export_docx_html_and_escape(client) -> None:
    body = "# 结论\n\n**510880** 是红利低波 ETF。\n\n<script>alert(1)</script>\n\n- 条目一\n- 条目二"
    docx = await client.post(
        "/api/canvas/export",
        json={"title": "红利低波 备忘", "body": body, "format": "docx"},
    )
    assert docx.status_code == 200, docx.text
    assert docx.content[:2] == b"PK"
    assert "wordprocessingml.document" in docx.headers["content-type"]
    assert "filename*=UTF-8''" in docx.headers["content-disposition"]

    page = await client.post(
        "/api/canvas/export",
        json={"title": "红利低波 备忘", "body": body, "format": "html"},
    )
    assert page.status_code == 200, page.text
    assert "text/html" in page.headers["content-type"]
    assert "<script>alert(1)</script>" not in page.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text
    assert "<strong>510880</strong>" in page.text

    bad = await client.post(
        "/api/canvas/export",
        json={"title": "x", "body": "x", "format": "exe"},
    )
    assert bad.status_code == 400


async def test_drop_image_parts_keeps_question_and_adds_fallback_notice() -> None:
    from app.agent import _drop_image_parts

    messages = [
        {"role": "system", "content": "你是财务助手。"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "这张截图说明了什么？"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        },
    ]
    _drop_image_parts(messages)
    assert messages[1]["content"].startswith("这张截图说明了什么？")
    assert "图片未能送入当前模型" in messages[1]["content"]
    assert "image_url" not in str(messages)


async def test_general_route_forwards_images_to_agent(monkeypatch, _temp_db) -> None:
    from app import agent, llm

    captured: dict = {}

    async def fake_run_agent(question, emit, history, lang, **kwargs):
        captured.update(kwargs)
        return {"answer": "图里是一个设置页。", "llm": "stub", "tools": [], "actions": []}

    async def fake_available() -> bool:
        return True

    monkeypatch.setattr(agent, "run_agent", fake_run_agent)
    monkeypatch.setattr(llm, "llm_available", fake_available)
    image = {"mime": "image/png", "data": "AAAA", "filename": "a.png"}
    result = await service._run_general(
        "这张截图里显示了什么设置？",
        "通用问答",
        lambda _event: None,
        thread_id="t-general-vision",
        images=[image],
    )
    assert result["answer"].startswith("图里")
    assert captured["images"] == [image]


async def test_graph_general_node_carries_state_images(monkeypatch) -> None:
    from app import agent_graph, service

    seen: dict = {}

    async def fake_run_general(question, reason, emit, thread_id=None, lang="zh", images=None):
        seen["images"] = images
        return {"answer": "ok"}

    monkeypatch.setattr(service, "_run_general", fake_run_general)
    state = {
        "question": "看图",
        "reason": "通用",
        "thread_id": "t",
        "lang": "zh",
        "images": [{"mime": "image/png", "data": "AAAA"}],
    }
    result = await agent_graph.general(state)
    assert result["result"]["answer"] == "ok"
    assert seen["images"][0]["mime"] == "image/png"

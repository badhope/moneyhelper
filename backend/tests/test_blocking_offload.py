"""上传类端点必须把阻塞解析推入线程池（不阻塞事件循环）。

背景：`/api/connect/invoices`、`/invoices/image`、`/import/statement-pdf` 在
`async def` 里直接调用 pypdf / pdfplumber / pyzbar+tesseract 这类同步函数。
它们耗时从几百毫秒到几十秒，跑在事件循环里会让**所有**并发请求停摆——
包括正在输出的 SSE 问答和页面轮询。仓库对 CPU-bound 已有统一做法
（`asyncio.to_thread`，见 vault.py、routes/export.py、routes/execute.py），
本测试把这个约定钉住，防止有人"顺手"改回同步调用。

判据不用绝对耗时，而是**并发性**：慢解析还在跑时，另一个请求必须立刻返回。
同步实现会让它一起等慢解析（回归时本用例会红）。
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from app import main
from app.import_parsers import invoice_vision, pdf_statement

SLOW = 0.8  # 模拟解析耗时（真实 OCR / PDF 远大于此）


@pytest.fixture(autouse=True)
async def _auto_temp_db(temp_db):
    yield


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac


async def _measure_concurrency(client, slow_call):
    """并发跑「慢解析」与「快请求」，返回快请求的耗时。"""

    async def fast_call():
        t0 = time.monotonic()
        resp = await client.get("/api/health")
        return resp, time.monotonic() - t0

    slow_resp, (fast_resp, elapsed) = await asyncio.gather(slow_call(), fast_call())
    assert slow_resp.status_code == 200, slow_resp.text
    assert fast_resp.status_code == 200, fast_resp.text
    return elapsed


async def test_invoice_image_offloaded(client, monkeypatch) -> None:
    """图片发票识别（二维码 + OCR）不得阻塞事件循环。"""

    def _slow(raw: bytes) -> dict:
        time.sleep(SLOW)
        return {"ok": False, "method": "test", "invoice": {}, "warnings": [], "install_hint": None}

    monkeypatch.setattr(invoice_vision, "invoice_from_image", _slow)

    async def slow_call():
        files = {"file": ("a.png", b"\x89PNG\r\n\x1a\n", "image/png")}
        return await client.post("/api/connect/invoices/image", files=files)

    elapsed = await _measure_concurrency(client, slow_call)
    assert elapsed < SLOW / 2, f"健康检查被阻塞 {elapsed:.2f}s：OCR 未推入线程池"


async def test_statement_pdf_offloaded(client, monkeypatch) -> None:
    """PDF 对账单导入（pdfplumber）不得阻塞事件循环。"""

    class _Res:
        def to_preview(self) -> dict:
            return {"rows": [], "pages": 0, "warnings": ["test"]}

    def _slow(raw: bytes) -> _Res:
        time.sleep(SLOW)
        return _Res()

    monkeypatch.setattr(pdf_statement, "parse_pdf_statement", _slow)

    async def slow_call():
        files = {"file": ("s.pdf", b"%PDF-1.4\n", "application/pdf")}
        return await client.post("/api/connect/import/statement-pdf", files=files)

    elapsed = await _measure_concurrency(client, slow_call)
    assert elapsed < SLOW / 2, f"健康检查被阻塞 {elapsed:.2f}s：PDF 解析未推入线程池"

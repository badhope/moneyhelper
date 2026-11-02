"""v4.6 攻坚 HTTP 测试：发票图片识别、PDF 对账单、规则归类、券商执行层。

外部行情与重依赖都可能缺失：所有用例都要么验证真实能力，要么验证降级提示准确。
"""

from __future__ import annotations

import io

import httpx
import pytest
from app import main


@pytest.fixture(autouse=True)
async def _temp_db(temp_db):
    yield


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac


# ---------------------------------------------------------------------------
# 能力探测
# ---------------------------------------------------------------------------


async def test_vision_status_shape(client) -> None:
    r = await client.get("/api/connect/invoices/vision/status")
    assert r.status_code == 200
    body = r.json()
    assert "qr" in body and "ocr" in body and "pdf_tables" in body
    assert isinstance(body["qr"]["available"], bool)
    assert isinstance(body["ocr"]["engines"], list)


# ---------------------------------------------------------------------------
# 发票图片（无解码器时也要给出提示而不是 500）
# ---------------------------------------------------------------------------


async def test_invoice_image_without_decoder_returns_hint(client) -> None:
    files = {"file": ("invoice.png", b"\x89PNG\r\n\x1a\nfake", "image/png")}
    r = await client.post("/api/connect/invoices/image", files=files)
    assert r.status_code == 200
    body = r.json()
    if not body.get("ok"):
        assert body["install_hint"]


async def test_invoice_image_rejects_non_multipart(client) -> None:
    r = await client.post("/api/connect/invoices/image", json={"file": "x"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# PDF 对账单
# ---------------------------------------------------------------------------


def _make_pdf() -> bytes | None:
    try:
        from reportlab.lib.pagesizes import A4  # type: ignore
        from reportlab.pdfgen import canvas  # type: ignore
    except ImportError:
        return None
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    rows = [
        ["Date", "Description", "Amount"],
        ["2026-09-01", "Ride", "-35.00"],
        ["2026-09-02", "Salary", "20000.00"],
    ]
    x0, y0, rh = 40, 780, 22
    colw = [120, 220, 100]
    c.setFont("Helvetica", 10)
    for ri, row in enumerate(rows):
        x = x0
        for ci, cell in enumerate(row):
            c.rect(x, y0 - (ri + 1) * rh, colw[ci], rh)
            c.drawString(x + 4, y0 - (ri + 1) * rh + 6, cell)
            x += colw[ci]
    c.save()
    return buf.getvalue()


async def test_pdf_statement_preview(client) -> None:
    raw = _make_pdf()
    if raw is None:
        pytest.skip("未安装 reportlab")
    files = {"file": ("statement.pdf", raw, "application/pdf")}
    r = await client.post("/api/connect/import/statement-pdf", files=files)
    assert r.status_code == 200
    body = r.json()
    if body["count"] == 0:
        assert body["warnings"]
        return
    assert body["count"] == 2


async def test_pdf_statement_apply_imports(client) -> None:
    raw = _make_pdf()
    if raw is None:
        pytest.skip("未安装 reportlab")
    files = {"file": ("statement.pdf", raw, "application/pdf")}
    r = await client.post(
        "/api/connect/import/statement-pdf",
        files=files,
        data={"apply": "true"},
    )
    body = r.json()
    if body["count"] == 0:
        assert body["warnings"]
        return
    assert body["imported"] == 2

    # 重复导入全部去重
    r2 = await client.post(
        "/api/connect/import/statement-pdf",
        files={"file": ("statement.pdf", raw, "application/pdf")},
        data={"apply": "true"},
    )
    body2 = r2.json()
    assert body2["imported"] == 0
    assert body2["duplicated"] == 2


async def test_statement_reconcile_api(client) -> None:
    r = await client.post(
        "/api/connect/statement/reconcile",
        json={"rows": [{"date": "2026-09-01", "amount": -35.0, "item": "打车"}]},
    )
    assert r.status_code == 200
    body = r.json()
    assert "missing_in_ledger" in body
    assert "balanced" in body


async def test_statement_reconcile_rejects_bad_payload(client) -> None:
    r = await client.post("/api/connect/statement/reconcile", json={"rows": "x"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 规则归类
# ---------------------------------------------------------------------------


async def test_categorize_rules_listed(client) -> None:
    r = await client.get("/api/connect/categorize/rules")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] > 10
    assert all("specificity" in x for x in body["rules"])


async def test_categorize_preview(client) -> None:
    r = await client.post(
        "/api/connect/categorize/preview",
        json={
            "rows": [
                {"item": "滴滴快车", "amount": -35},
                {"item": "工资", "amount": 20000},
                {"item": "未知商户 XYZ", "amount": -10},
            ]
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert body["fallback"] == 1
    cats = [x["category"] for x in body["results"]]
    assert "交通" in cats and "收入" in cats


async def test_categorize_preview_rejects_empty(client) -> None:
    r = await client.post("/api/connect/categorize/preview", json={"rows": []})
    assert r.status_code == 400


async def test_categorize_apply_changes_categories(client) -> None:
    # 先写入一条分类不对的流水
    await client.post(
        "/api/transactions",
        json={"date": "2026-09-11", "item": "滴滴快车", "category": "其他", "amount": -35},
    )
    r = await client.post("/api/connect/categorize/apply", json={})
    assert r.status_code == 200
    assert r.json()["changed"] >= 1


# ---------------------------------------------------------------------------
# 券商执行层
# ---------------------------------------------------------------------------


async def test_execute_status_default_safe(client) -> None:
    r = await client.get("/api/execute/status")
    assert r.status_code == 200
    body = r.json()
    assert body["guardrails"]["trading_enabled"] is False
    assert body["guardrails"]["dry_run"] is True
    assert body["current"]["id"] == "null"
    ids = {a["id"] for a in body["adapters"]}
    assert {"null", "paper", "xtquant", "easytrader"} == ids


async def test_execute_preview_blocked_by_switch(client) -> None:
    r = await client.post(
        "/api/execute/preview",
        json={"symbol": "000001", "side": "buy", "quantity": 100, "limit_price": 11.44},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["stage"] == "switch"
    assert body["confirmation_token"] == ""


async def test_execute_submit_also_blocked_by_switch(client) -> None:
    r = await client.post(
        "/api/execute/submit",
        json={"symbol": "000001", "side": "buy", "quantity": 100, "limit_price": 11.44},
    )
    body = r.json()
    assert body["ok"] is False
    assert body["stage"] == "switch"


async def test_execute_preview_rejects_bad_symbol(client) -> None:
    r = await client.post(
        "/api/execute/preview",
        json={"symbol": "abc", "side": "buy", "quantity": 100, "limit_price": 11.44},
    )
    assert r.status_code == 400


async def test_execute_connect_unavailable_adapter(client) -> None:
    r = await client.post("/api/execute/adapters/xtquant/connect")
    assert r.status_code in (400, 502)
    body = r.json()
    assert "error" in body


async def test_execute_orders_null_broker_empty(client) -> None:
    r = await client.get("/api/execute/orders")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["broker"] == "null"
    assert body["dry_run"] is True

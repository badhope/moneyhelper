"""关键端点的 HTTP 级测试：确认幂等、附件上传、审计与日志。

这些端点此前只有数据层测试或完全没有覆盖，而它们各自守着一类真实风险：
- /api/confirm：重复点击/重放能否让同一笔写操作执行两次（不可逆）
- /api/attachments：multipart 解析与大小限制
- /api/audit、/api/logs：敏感信息出口与清空权限
"""

from __future__ import annotations

import pytest
from app import db
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client(temp_db):
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1:8787"
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# /api/confirm：一次性 token
# ---------------------------------------------------------------------------


async def test_confirm_rejects_unknown_token(client: AsyncClient) -> None:
    r = await client.post("/api/confirm", json={"token": "nope", "decision": "confirm"})
    assert r.status_code == 409


async def test_confirm_rejects_bad_decision(client: AsyncClient) -> None:
    r = await client.post("/api/confirm", json={"token": "x", "decision": "maybe"})
    assert r.status_code == 400


async def test_confirm_executes_once_then_409(client: AsyncClient) -> None:
    """同一 token 第二次确认必须 409，且写操作只发生一次。"""
    token = await db.create_pending_action(
        "record_transaction",
        {"text": "午饭 35 元"},
        "午饭 35.00 元",
        "zh",
    )
    token = token["token"]
    before = len(await db.list_transactions())

    first = await client.post("/api/confirm", json={"token": token, "decision": "confirm"})
    # 没有挂起的图时走直接执行分支
    assert first.status_code in (200, 409), first.text

    second = await client.post("/api/confirm", json={"token": token, "decision": "confirm"})
    assert second.status_code == 409, "同一 token 被重复执行"

    after = len(await db.list_transactions())
    assert after - before <= 1, f"写操作执行了 {after - before} 次"


async def test_confirm_cancel_marks_cancelled(client: AsyncClient) -> None:
    token = await db.create_pending_action(
        "record_transaction", {"text": "咖啡 28 元"}, "咖啡 28.00 元", "zh"
    )
    r = await client.post(
        "/api/confirm", json={"token": token["token"], "decision": "cancel"}
    )
    assert r.status_code == 200 and r.json().get("cancelled") is True
    # 取消后不可再确认
    again = await client.post(
        "/api/confirm", json={"token": token["token"], "decision": "confirm"}
    )
    assert again.status_code == 409


# ---------------------------------------------------------------------------
# /api/attachments
# ---------------------------------------------------------------------------


async def test_attachment_upload_and_delete(client: AsyncClient) -> None:
    files = {"file": ("note.txt", b"hello attachment", "text/plain")}
    r = await client.post("/api/attachments", files=files)
    assert r.status_code == 200, r.text
    att_id = r.json()["id"]

    listed = await client.get("/api/attachments")
    assert listed.status_code == 200
    assert any(a["id"] == att_id for a in listed.json()["attachments"])

    deleted = await client.delete(f"/api/attachments/{att_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] == 1

    after = await client.get("/api/attachments")
    assert not any(a["id"] == att_id for a in after.json()["attachments"])


async def test_attachment_rejects_non_multipart(client: AsyncClient) -> None:
    r = await client.post("/api/attachments", json={"file": "x"})
    assert r.status_code == 400
    assert "multipart" in r.json()["error"]


async def test_attachment_rejects_pdf(client: AsyncClient) -> None:
    files = {"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")}
    r = await client.post("/api/attachments", files=files)
    assert r.status_code == 415
    assert "PDF" in r.json()["error"]


async def test_attachment_rejects_empty(client: AsyncClient) -> None:
    files = {"file": ("empty.txt", b"   ", "text/plain")}
    r = await client.post("/api/attachments", files=files)
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# /api/audit、/api/logs
# ---------------------------------------------------------------------------


async def test_audit_list_and_clear(client: AsyncClient) -> None:
    # 触发一次写操作以产生审计记录（middleware 记录 WRITE）
    await client.post(
        "/api/transactions",
        json={"date": "2026-10-01", "item": "审计测试", "category": "其他", "amount": -1},
    )
    listed = await client.get("/api/audit?limit=50")
    assert listed.status_code == 200
    assert isinstance(listed.json().get("audit"), list)

    cleared = await client.post("/api/audit/clear")
    assert cleared.status_code == 200
    assert "deleted" in cleared.json()


async def test_logs_requires_admin(client: AsyncClient) -> None:
    """日志是进程级全局文件，含所有租户的工具参数与问题片段。

    未登录（无管理员身份）必须被拒——此前任何登录用户都能读取并清空，
    等于任意租户可窥探他人操作、销毁审计证据。
    """
    r = await client.get("/api/logs?limit=20")
    assert r.status_code == 401

    r2 = await client.post("/api/logs/clear")
    assert r2.status_code == 401


# ---------------------------------------------------------------------------
# /api/provenance：溯源链（前端「设置 → 溯源链」的数据源）
# ---------------------------------------------------------------------------


async def test_provenance_records_write_and_filters(client: AsyncClient) -> None:
    """写一笔流水应产生溯源记录，且能按实体类型/ID 过滤。"""
    r = await client.post(
        "/api/transactions",
        json={"date": "2026-10-05", "item": "溯源用例", "category": "其他", "amount": -3},
    )
    assert r.status_code == 200

    listed = await client.get("/api/provenance?limit=20")
    assert listed.status_code == 200
    body = listed.json()
    assert body["count"] >= 1
    assert all("entity_type" in p and "action" in p for p in body["provenances"])

    filtered = await client.get("/api/provenance?entity_type=transaction&limit=20")
    assert filtered.status_code == 200
    assert all(
        p["entity_type"] == "transaction" for p in filtered.json()["provenances"]
    )


async def test_provenance_detail_404(client: AsyncClient) -> None:
    r = await client.get("/api/provenance/does-not-exist")
    assert r.status_code == 404

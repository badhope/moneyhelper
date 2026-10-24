"""审计底稿导出测试：内容必须真实来自 provenance，且不能有注入面。

关键断言：
- 每个条目都出现在 HTML 里，before/after 差异表只列变化字段
- 标题/实体名里的 HTML 被转义（防 XSS）
- 过滤条件与文件名头正确
"""

from __future__ import annotations

import httpx
import pytest
from app import main
from app.audit_report import MAX_ENTRIES, render_audit_report
from app.provenance import flush_writes, record_provenance


@pytest.fixture(autouse=True)
async def _temp_db(temp_db):
    yield


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as ac:
        yield ac


def test_render_empty_report():
    html = render_audit_report([])
    assert "该范围内没有任何审计记录" in html
    assert "<!doctype html>" in html


def test_render_escapes_html_injection():
    entries = [
        {
            "id": "e1",
            "timestamp": "2026-10-23T10:00:00+08:00",
            "action": "<script>alert(1)</script>",
            "entity_type": "transaction",
            "entity_id": "1",
            "before": {"item": "<img src=x onerror=alert(1)>"},
            "after": {"item": "safe"},
            "source": "api",
            "username": "<b>attacker</b>",
            "metadata": {},
        }
    ]
    html = render_audit_report(entries)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "<img src=x" not in html
    assert "&lt;img" in html


def test_render_lists_only_changed_fields():
    entries = [
        {
            "id": "e2",
            "timestamp": "2026-10-23T10:00:00+08:00",
            "action": "update_position",
            "entity_type": "position",
            "entity_id": "600519",
            "before": {"shares": 100, "cost": 1680, "name": "茅台"},
            "after": {"shares": 200, "cost": 1680, "name": "茅台"},
            "source": "agent",
            "username": "me",
            "metadata": {"thread_id": "t1"},
        }
    ]
    html = render_audit_report(entries)
    assert "shares" in html
    # cost/name 没变化，不应出现在差异表里
    assert "<td>cost</td>" not in html
    assert "<td>name</td>" not in html
    assert "100" in html and "200" in html


def test_render_marks_source_badge():
    entries = [
        {
            "id": "e3",
            "timestamp": "2026-10-23T10:00:00+08:00",
            "action": "add_transaction",
            "entity_type": "transaction",
            "entity_id": "9",
            "before": None,
            "after": {"amount": -32},
            "source": "mcp",
            "username": "",
            "metadata": {},
        }
    ]
    html = render_audit_report(entries)
    assert "src-mcp" in html
    assert "add_transaction" in html


def test_render_truncation_notice():
    entries = [
        {
            "id": f"e{i}",
            "timestamp": "2026-10-23T10:00:00+08:00",
            "action": "a",
            "entity_type": "t",
            "entity_id": str(i),
            "before": None,
            "after": None,
            "source": "api",
            "username": "",
            "metadata": {},
        }
        for i in range(MAX_ENTRIES + 5)
    ]
    html = render_audit_report(entries)
    assert "记录数超过" in html
    assert f"前 {MAX_ENTRIES} 条" in html


async def test_audit_report_endpoint_returns_html(client):
    await record_provenance(
        action="add_transaction",
        entity_type="transaction",
        entity_id="77",
        before=None,
        after={"amount": -32, "item": "打车"},
        source="api",
        username="tester",
    )
    await flush_writes()
    r = await client.get("/api/audit-report")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]
    assert "打车" in r.text
    assert "add_transaction" in r.text


async def test_audit_report_filter_by_entity(client):
    await record_provenance(
        action="add_position",
        entity_type="position",
        entity_id="510300",
        before=None,
        after={"shares": 8000},
        source="api",
        username="tester",
    )
    await flush_writes()
    r = await client.get("/api/audit-report?entity_type=position&entity_id=510300")
    assert r.status_code == 200
    assert "510300" in r.text
    r2 = await client.get("/api/audit-report?entity_type=position&entity_id=999999")
    # ID 会出现在"审计范围"说明里，但不应有任何记录条目
    assert "没有任何审计记录" in r2.text


async def test_provenance_list_supports_date_filters(client):
    r = await client.get("/api/provenance?date_from=2000-01-01&date_to=2000-12-31")
    assert r.status_code == 200
    assert r.json()["count"] == 0


async def test_audit_report_has_no_inline_script_except_print_button(client):
    r = await client.get("/api/audit-report")
    # 只允许打印按钮那一处内联 onclick；不允许外部脚本
    assert "<script src=" not in r.text
    assert r.headers["content-security-policy"].startswith("default-src 'none'")

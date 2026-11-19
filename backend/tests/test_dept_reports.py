"""M3.5 老板呈批 HITL 测试。

呈批件必须持久化（老板离开页面再回来仍能批），审批必须幂等（并发不能重复批），
追问必须产生新呈批件（原记录保留为历史）。这三点是"审批链可查"的基础。
"""

from __future__ import annotations

import pytest
from app import db
from httpx import AsyncClient


@pytest.fixture(autouse=True)
async def _clean_dept_reports(temp_db):
    """每个测试前清空呈批件表。

    reset_to_seed 按设计只重置示例数据、保留业务记录（用户的呈批件不该被
    "恢复示例数据"清掉），所以测试需要自己清理，否则计数类断言会串数据。
    """
    await db.execute("DELETE FROM dept_reports")
    yield


def _report_payload(**kw):
    base = {
        "question": "盘一下上季度",
        "verdict": "4 个部门口径一致，可以直接决策。",
        "report": "# 呈批件\n\n**结论**：可以直接决策。",
        "orders": [{"dept": "accounting", "status": "done", "metrics": {"expense": 100}}],
        "conflicts": [],
        "dispatch": "rules",
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------


async def test_save_and_get_report() -> None:
    rid = await db.dept_report_save("盘一下上季度", _report_payload())
    assert rid
    got = await db.dept_report_get(rid)
    assert got is not None
    assert got["status"] == "pending"
    assert got["question"] == "盘一下上季度"
    assert got["orders"][0]["dept"] == "accounting"
    assert got["conflicts"] == []


async def test_get_missing_report_returns_none() -> None:
    assert await db.dept_report_get("nope") is None


async def test_list_reports_filters_by_status() -> None:
    r1 = await db.dept_report_save("q1", _report_payload())
    r2 = await db.dept_report_save("q2", _report_payload())
    await db.dept_report_decide(r1, "approve")

    pending = await db.dept_report_list("pending")
    assert [r["report_id"] for r in pending] == [r2]
    approved = await db.dept_report_list("approved")
    assert [r["report_id"] for r in approved] == [r1]
    assert len(await db.dept_report_list()) == 2


async def test_list_reports_newest_first() -> None:
    old = await db.dept_report_save("old", _report_payload())
    new = await db.dept_report_save("new", _report_payload())
    rows = await db.dept_report_list()
    assert [r["report_id"] for r in rows] == [new, old]


# ---------------------------------------------------------------------------
# 审批状态机
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("decision", ["approve", "reject", "inquire"])
async def test_decide_transitions(decision: str) -> None:
    rid = await db.dept_report_save("q", _report_payload())
    out = await db.dept_report_decide(rid, decision, "理由")
    assert out is not None
    assert out["status"] == {"approve": "approved", "reject": "rejected", "inquire": "inquired"}[
        decision
    ]
    assert out["decided_at"]


async def test_decide_is_idempotent_guard() -> None:
    """同一份呈批件只能被审批一次（并发安全靠条件 UPDATE）。"""
    rid = await db.dept_report_save("q", _report_payload())
    first = await db.dept_report_decide(rid, "approve")
    assert first is not None
    second = await db.dept_report_decide(rid, "reject", "反悔")
    assert second is None, "已处理的呈批件不能被二次审批"


async def test_decide_unknown_report() -> None:
    assert await db.dept_report_decide("nope", "approve") is None


async def test_decide_invalid_decision_raises() -> None:
    rid = await db.dept_report_save("q", _report_payload())
    with pytest.raises(ValueError):
        await db.dept_report_decide(rid, "maybe")


async def test_pending_count() -> None:
    assert await db.dept_report_pending_count() == 0
    a = await db.dept_report_save("a", _report_payload())
    await db.dept_report_save("b", _report_payload())
    assert await db.dept_report_pending_count() == 2
    await db.dept_report_decide(a, "approve")
    assert await db.dept_report_pending_count() == 1


async def test_note_is_truncated() -> None:
    """理由长度设上限，防止塞入超长文本污染审计链。"""
    rid = await db.dept_report_save("q", _report_payload())
    out = await db.dept_report_decide(rid, "reject", "x" * 5000)
    assert out is not None and len(out["decision_note"]) == 1000


# ---------------------------------------------------------------------------
# HTTP 端点
# ---------------------------------------------------------------------------


async def test_api_list_and_detail(client: AsyncClient) -> None:
    rid = await db.dept_report_save("盘一下上季度", _report_payload())
    r = await client.get("/api/department/reports")
    assert r.status_code == 200
    assert any(x["report_id"] == rid for x in r.json()["reports"])

    r2 = await client.get(f"/api/department/reports/{rid}")
    assert r2.status_code == 200 and r2.json()["question"] == "盘一下上季度"

    r3 = await client.get("/api/department/reports/nope")
    assert r3.status_code == 404


async def test_api_approve(client: AsyncClient) -> None:
    rid = await db.dept_report_save("q", _report_payload())
    r = await client.post(
        f"/api/department/reports/{rid}/decide", json={"decision": "approve"}
    )
    assert r.status_code == 200
    assert r.json()["report"]["status"] == "approved"
    # 审计链有一条决策记录
    prov = await db.fetch_all(
        "SELECT action FROM provenance_log WHERE entity_id=?", (rid,)
    )
    assert any(p["action"] == "dept_report_approve" for p in prov)


async def test_api_reject_requires_note(client: AsyncClient) -> None:
    rid = await db.dept_report_save("q", _report_payload())
    r = await client.post(
        f"/api/department/reports/{rid}/decide", json={"decision": "reject"}
    )
    assert r.status_code == 400
    assert "理由" in r.json()["error"]


async def test_api_invalid_decision(client: AsyncClient) -> None:
    rid = await db.dept_report_save("q", _report_payload())
    r = await client.post(
        f"/api/department/reports/{rid}/decide", json={"decision": "maybe"}
    )
    assert r.status_code == 400


async def test_api_double_decide_returns_409(client: AsyncClient) -> None:
    rid = await db.dept_report_save("q", _report_payload())
    first = await client.post(
        f"/api/department/reports/{rid}/decide", json={"decision": "approve"}
    )
    assert first.status_code == 200
    second = await client.post(
        f"/api/department/reports/{rid}/decide", json={"decision": "approve"}
    )
    assert second.status_code == 409
    assert "已被处理" in second.json()["error"]


async def test_api_inquire_creates_followup(client: AsyncClient) -> None:
    """追问产生新呈批件，原呈批件保留为历史（审批链不被覆盖）。"""
    rid = await db.dept_report_save("盘一下", _report_payload())
    r = await client.post(
        f"/api/department/reports/{rid}/decide",
        json={"decision": "inquire", "note": "投资部再看细一点"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["report"]["status"] == "inquired"
    new_id = body.get("followup_report_id")
    assert new_id and new_id != rid
    follow = await db.dept_report_get(new_id)
    assert follow is not None and follow["status"] == "pending"
    assert "老板追问" in follow["question"]
    # 原记录仍在
    origin = await db.dept_report_get(rid)
    assert origin is not None and origin["status"] == "inquired"


async def test_api_approve_missing_report(client: AsyncClient) -> None:
    r = await client.post(
        "/api/department/reports/nope/decide", json={"decision": "approve"}
    )
    assert r.status_code == 404


async def test_stream_report_carries_status_and_id(client: AsyncClient) -> None:
    """回归：SSE 推给前端的呈批件必须带 status='pending' 与 report_id。

    前端靠这两个字段决定是否显示审批按钮。此前只拼了 report_id 没带 status，
    结果是"待批的呈批件看不到批准按钮"——e2e 实测发现。
    """
    import json as _json

    events: list[dict] = []
    async with client.stream(
        "POST", "/api/department/stream", json={"question": "盘一下上季度"}
    ) as r:
        assert r.status_code == 200
        async for line in r.aiter_lines():
            if line.startswith("data:"):
                ev = _json.loads(line[5:].strip())
                events.append(ev)
                if ev.get("type") == "dept_report":
                    break

    report_ev = next(e for e in events if e.get("type") == "dept_report")
    report = report_ev["report"]
    assert report.get("report_id"), "必须带 report_id 才能审批"
    assert report.get("status") == "pending", "必须带 status，否则前端不显示审批按钮"
    assert report.get("verdict")

"""数字身份证与月度复盘的接口契约测试。"""

from __future__ import annotations

from datetime import date


async def test_identity_card_is_local_and_non_sensitive(client) -> None:
    r = await client.get("/api/identity/card")
    assert r.status_code == 200
    body = r.json()
    assert body["fingerprint"].startswith("MH-")
    assert body["profile"]["storage"]
    assert body["permissions"]["local_only"] is True
    assert body["permissions"]["revocable"] is True
    # 身份证不是"身份号码"：不得出现身份证号/卡号/密码字段
    for key in ("id_number", "card_number", "password", "id_card"):
        assert key not in body["profile"]
        assert key not in body["financials"]
        assert key not in body["coverage"]
    assert set(body["permissions"]["controls"]) == {"read", "import", "handoff", "manual", "confirm"}
    assert body["coverage"]["transactions"] > 0
    assert body["boundaries"]


async def test_monthly_review_is_deterministic_and_capped(client) -> None:
    month = date.today().strftime("%Y-%m")
    r = await client.get(f"/api/review/monthly/{month}")
    assert r.status_code == 200
    body = r.json()
    assert body["month"] == month
    assert body["fingerprint"].startswith("MH-")
    assert body["status"] in {"in_progress", "closed"}
    assert body["cashflow"]["income"] > 0
    assert body["cashflow"]["expense"] > 0
    assert len(body["closing"]["checks"]) == 5
    assert 0 <= body["closing"]["completeness_pct"] <= 100
    assert 1 <= len(body["actions"]) <= 3
    # 复盘不能把"模型建议"混成数字：每个动作都带 code 与可核对的金额
    for action in body["actions"]:
        assert action["code"]
        assert action["title"]
    assert body["disclaimer"]


async def test_monthly_review_rejects_invalid_and_future(client) -> None:
    for month in ("2026-13", "2026-1", "not-a-month"):
        r = await client.get(f"/api/review/monthly/{month}")
        assert r.status_code == 400
    future = f"{date.today().year + 1}-01"
    r = await client.get(f"/api/review/monthly/{future}")
    assert r.status_code == 400
    assert "未来" in r.json()["error"]


async def test_empty_month_points_to_data_gap(client) -> None:
    r = await client.get("/api/review/monthly/2025-01")
    assert r.status_code == 200
    body = r.json()
    assert body["closing"]["ready"] is False
    assert body["actions"][0]["code"] == "NO_DATA"
    assert len(body["actions"]) <= 3


def test_identity_and_review_are_exposed_to_the_agent() -> None:
    from app import agent_tooling, tools

    names = {t["function"]["name"] for t in tools.TOOLS}
    assert {"get_financial_identity", "get_monthly_review"} <= names
    read_names = {t["function"]["name"] for t in agent_tooling.READ_TOOLS}
    assert {"get_financial_identity", "get_monthly_review"} <= read_names

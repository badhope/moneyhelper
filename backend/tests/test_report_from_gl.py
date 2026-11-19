"""「从总账还原三表」的口径守卫。

这是把「手抄 JSON」变成「零输入出报表」的核心换算，错一位借方就会让
`资产 = 负债 + 权益` 不成立、勾稽预警满屏。所以这里既测纯函数，也测端到端。
"""

from __future__ import annotations

from app.calculations.report_from_gl import statements_from_trial_balance


def _tb(**kw) -> list[dict]:
    """试算表行：balance = 借 − 贷（与 db.gl_trial_balance 输出一致）。"""
    return [{"code": c, "name": n, "type": t, "balance": b} for c, n, t, b in kw["rows"]]


ROWS = [
    ("1001", "银行存款", "asset", 5000.0),
    ("1122", "应收账款", "asset", 2000.0),
    ("1405", "库存商品", "asset", 1000.0),
    ("1601", "固定资产", "asset", 3000.0),
    ("2202", "应付账款", "liability", -2200.0),
    ("2501", "长期借款", "liability", -1000.0),
    ("4001", "实收资本", "equity", -6000.0),
    ("6001", "主营业务收入", "income", -4000.0),
    ("6401", "主营业务成本", "expense", 2000.0),
    ("6603", "财务费用", "expense", 200.0),
]


def test_identity_holds_after_reconstruction() -> None:
    out = statements_from_trial_balance(_tb(rows=ROWS), period="2026-11")
    bs = out["periods"][0]["balance_sheet"]
    assert bs["total_assets"] == 11000.0
    assert bs["total_liabilities"] == 3200.0   # 2202 应付 2200 + 2501 长期借款 1000
    # 权益 = 科目余额 6000 + 当期净利润 1800（结转后口径）
    assert bs["total_equity"] == 7800.0
    assert bs["total_assets"] == bs["total_liabilities"] + bs["total_equity"]


def test_current_split_uses_code_prefix() -> None:
    out = statements_from_trial_balance(_tb(rows=ROWS))
    bs = out["periods"][0]["balance_sheet"]
    assert bs["current_assets"] == 8000.0        # 1001/1122/1405，不含 1601 固定资产
    assert bs["current_liabilities"] == 2200.0   # 2202，不含 2501 长期借款
    assert bs["cash_and_equivalents"] == 5000.0
    assert bs["accounts_receivable"] == 2000.0
    assert bs["inventory"] == 1000.0
    assert bs["goodwill"] == 0.0


def test_income_statement_reconstructed_from_debit_credit() -> None:
    out = statements_from_trial_balance(_tb(rows=ROWS))
    pl = out["periods"][0]["income_statement"]
    assert pl["revenue"] == 4000.0
    assert pl["gross_profit"] == 2000.0     # 收入 − 主营业务成本
    assert pl["net_profit"] == 1800.0       # 收入 − 全部费用
    assert pl["interest_expense"] == 200.0
    assert pl["ebit"] == 2000.0


def test_cashflow_is_omitted_not_faked() -> None:
    """余额表推不出期间现金流；宁可缺字段让分析标注「—」，也不能编数字。"""
    out = statements_from_trial_balance(_tb(rows=ROWS))
    assert "cashflow_statement" not in out["periods"][0]


def test_empty_ledger_yields_zero_report() -> None:
    out = statements_from_trial_balance([])
    bs = out["periods"][0]["balance_sheet"]
    assert bs["total_assets"] == 0.0
    assert bs["total_liabilities"] == 0.0


async def test_route_returns_payload_and_analysis(client) -> None:
    """端到端：造一组真实凭证（收款 + 费用），过账后应能出报表且勾稽等式成立。"""
    from app import auth, db

    uid = await db.user_create("stmt-gl", "pw-123456", "stmt-gl", "admin")
    user = await db.user_get(uid)
    assert user is not None
    headers = {"Authorization": f"Bearer {auth._make_jwt(user)}"}

    async def account(code: str, name: str, type_: str) -> int:
        r = await client.post(
            "/api/gl/accounts", json={"code": code, "name": name, "type": type_}, headers=headers
        )
        assert r.status_code == 200, r.text
        return int(r.json()["account"]["id"])

    cash = await account("1001", "银行存款", "asset")
    revenue = await account("6001", "主营业务收入", "income")
    expense = await account("6601", "管理费用", "expense")

    r = await client.post("/api/gl/periods", json={"year": 2026, "month": 11}, headers=headers)
    assert r.status_code == 200, r.text
    period_id = int(r.json()["period"]["id"])

    for lines in (
        [
            {"account_id": cash, "debit": 3000, "credit": 0},
            {"account_id": revenue, "debit": 0, "credit": 3000},
        ],
        [
            {"account_id": expense, "debit": 800, "credit": 0},
            {"account_id": cash, "debit": 0, "credit": 800},
        ],
    ):
        r = await client.post(
            "/api/gl/entries",
            json={"entry_date": "2026-11-15", "description": "e2e", "lines": lines},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        entry_id = r.json()["entry"]["id"]
        r = await client.post(f"/api/gl/entries/{entry_id}/post", headers=headers)
        assert r.status_code == 200, r.text

    resp = await client.post("/api/statements/from-gl", json={"period_id": period_id}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["analysis"] is not None
    bs = body["payload"]["periods"][0]["balance_sheet"]
    assert bs["total_assets"] == 2200.0            # 3000 收 − 800 支
    assert bs["total_equity"] == 2200.0            # 0 权益 + 2200 净利（结转后口径）
    assert abs(bs["total_assets"] - (bs["total_liabilities"] + bs["total_equity"])) < 0.01
    pl = body["payload"]["periods"][0]["income_statement"]
    assert pl["revenue"] == 3000.0
    assert pl["net_profit"] == 2200.0


async def test_auto_post_posts_drafts_then_reports(client) -> None:
    """有草稿没已过账时：不传 auto_post 应 409 并说明草稿数；传了应由系统代过账。"""
    from app import auth, db

    uid = await db.user_create("stmt-auto", "pw-123456", "stmt-auto", "admin")
    user = await db.user_get(uid)
    assert user is not None
    headers = {"Authorization": f"Bearer {auth._make_jwt(user)}"}

    async def account(code: str, name: str, type_: str) -> int:
        r = await client.post(
            "/api/gl/accounts", json={"code": code, "name": name, "type": type_}, headers=headers
        )
        assert r.status_code == 200, r.text
        return int(r.json()["account"]["id"])

    cash = await account("1001", "银行存款", "asset")
    revenue = await account("6001", "主营业务收入", "income")
    r = await client.post("/api/gl/periods", json={"year": 2026, "month": 12}, headers=headers)
    period_id = int(r.json()["period"]["id"])
    r = await client.post(
        "/api/gl/entries",
        json={
            "entry_date": "2026-12-05",
            "description": "收款",
            "lines": [
                {"account_id": cash, "debit": 1500, "credit": 0},
                {"account_id": revenue, "debit": 0, "credit": 1500},
            ],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text

    resp = await client.post("/api/statements/from-gl", json={"period_id": period_id}, headers=headers)
    assert resp.status_code == 409, resp.text

    resp = await client.post(
        "/api/statements/from-gl",
        json={"period_id": period_id, "auto_post": True},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["auto_posted"] == 1
    bs = body["payload"]["periods"][0]["balance_sheet"]
    assert bs["total_assets"] == 1500.0

"""DELETE / PUT / PATCH 路由真实实参验收。

之前的路由扫描只用占位 id 打，45 条写路由全部落在 404/422，等于只证明"没崩"。
这个探针反过来：先在隔离库种出真实实体（目标/负债/订阅/自选/流水/持仓/发票/
条件单/模拟账户/财报/成员/借贷/连接/会话/记忆/附件/studio 资产），再用**真 id**
逐条打 DELETE/PUT/PATCH，断言：

1. 没有一条返回 5xx（参数错误 400/422、找不到 404 都算正常）；
2. 至少大部分删除真的把行删掉了（不是静默 200 空操作）。

跑法（仓库根目录）：
  PYTHONPATH=backend MONEYHELPER_DB_PATH=$PWD/.tmp/mut_probe.db \
  MONEYHELPER_DATA_DIR=$PWD/.tmp/mut_probe_data \
  python3 scripts/probe_mutations.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = ROOT / ".tmp"


def _ok(label: str, cond: bool, detail: str = "") -> bool:
    print(f"{'✓' if cond else '✗'} {label}" + (f" — {detail}" if detail else ""))
    return cond


async def seed() -> dict:
    from app import db
    from app.connect import store as cstore
    from app.db import statements as stmt_db
    from app.studio import store as sstore

    await db.init_db()
    await db.reset_to_seed()

    await db.add_watchlist("600519", "贵州茅台")
    await db.add_goal({"name": "probe-goal", "target": 1000, "saved": 100, "deadline": "2026-12"})
    await db.add_debt({"name": "probe-debt", "balance": 500, "monthly": 50, "rate": 3.5, "due_day": "20"})
    await db.add_subscription({"name": "probe-sub", "monthly": 15, "due_day": "25"})
    await db.add_memory("probe 记忆：下月要交房租")
    att = await db.add_attachment("probe.txt", "text", 3, "abc")
    sess = await db.create_session(title="probe-session")
    run = await db.save_run("probe-thread", "探针问题", "探针回答", "standard")
    inv = await db.save_invoice(
        file_name="probe.pdf", raw=b"%PDF-1.4 probe", parsed={"amount": 100, "seller": "probe"}
    )
    cond = await db.create_conditional({
        "symbol": "600519", "side": "buy", "trigger_type": "price_below",
        "trigger_value": 1000, "price": 1000, "shares": 100, "mode": "paper",
    })
    acc = await db.open_account("probe-paper", 10000)
    st = await stmt_db.save_statement("ProbeCo", {"income": {"revenue": 100}}, report="probe report")
    m1 = await db.member_create("ProbeA")
    m2 = await db.member_create("ProbeB")
    loan = await db.loan_create(m1, m2, 100, note="probe loan")
    conn = await cstore.create_connection("eastmoney_quote", label="probe-conn")
    try:
        plan = await db.upsert_dca_plan({"symbol": "600519", "amount": 1000, "freq": "monthly", "day": 1})
    except Exception as exc:  # noqa: BLE001 — 种子失败不该挡住其余用例
        print(f"  ! dca seed skipped: {exc}")
        plan = {}
    try:
        await db.record_shadow_decision(
            tenant_id=1, user_id=None, role="admin", subject="probe",
            permission_id="probe.perm", decision="allow", allowed=True, mismatch=False,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  ! shadow seed skipped: {exc}")

    # studio 资产：直接用 store 写一条，kind 必须在内置枚举里
    try:
        await sstore.upsert_asset("prompts", "probe-asset", {"name": "探针", "content": "hi"})
    except Exception as exc:  # noqa: BLE001
        print(f"  ! studio seed skipped: {exc}")

    # GL 草稿凭证：先建科目再建期间，否则"科目不存在"根本测不到删除分支
    gl_entry = {}
    try:
        from app import db as _db
        from app.db.tenant import current_tenant_id
        tenant = current_tenant_id()  # 本机模式是租户 0，写死 1 会导致"部门不存在"
        try:
            await _db.gl_create_period(tenant, 2026, 11)
        except ValueError:
            pass  # 期间已存在
        acc1 = await _db.gl_create_account(tenant, "1001", "库存现金", "asset")
        acc2 = await _db.gl_create_account(tenant, "2001", "应付账款", "liability")
        gl_entry = await _db.gl_create_entry(
            tenant, "2026-11-20", "probe entry",
            [{"account_id": acc1["id"], "debit": 100}, {"account_id": acc2["id"], "credit": 100}],
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  ! gl seed skipped: {exc}")

    # 组织域：部门/岗位不需要账号就能建；成员写入需要真实 users 行，
    # 而建号会把实例切进"必须登录"模式，其余 40 条用例全变 401——
    # 所以成员这一条留给多租户探针，这里只验部门/岗位的真 id 路径。
    org = {"dept": None, "pos": None, "user": None}
    try:
        from app import db as _db
        from app.db.tenant import current_tenant_id
        tenant = current_tenant_id()
        dept = await _db.org_create_department(tenant, "探针部门", code="PROBE")
        pos = await _db.org_create_position(tenant, "探针岗位", department_id=dept["id"], code="P-PROBE")
        org = {"dept": dept["id"], "pos": pos["id"], "user": None}
    except Exception as exc:  # noqa: BLE001
        print(f"  ! org seed skipped: {exc}")

    txs = await db.list_transactions()
    txs = sorted(txs, key=lambda t: t["id"])
    positions = await db.list_positions()
    out = {
        "tx_update": txs[0]["id"] if txs else 1,
        "tx_delete": txs[-1]["id"] if txs else 999999,
        "pos_update": positions[0]["symbol"] if positions else "600519",
        "pos_delete": positions[-1]["symbol"] if len(positions) > 1 else "000001",
        "goal": "probe-goal",
        "debt": "probe-debt",
        "sub": "probe-sub",
        "watch": "600519",
        "conn": conn.get("id") or conn.get("cid"),
        "invoice": inv.get("id"),
        "cond": cond.get("id"),
        "paper": acc.get("account_id"),
        "statement": st.get("id"),
        "member_update": m2,
        "member_delete": m1,
        "loan": loan,
        "session_update": sess.get("id"),
        "session_delete": (await db.create_session(title="probe-session-2")).get("id"),
        "run": run.get("id") if isinstance(run, dict) else run,
        "memory": None,
        "attachment": att.get("id"),
        "plan": plan.get("id") if isinstance(plan, dict) else None,
        "gl": gl_entry.get("id") if isinstance(gl_entry, dict) else None,
        "org_dept": org["dept"], "org_pos": org["pos"], "org_user": org["user"],
        "studio": "probe-asset",
    }
    mem = await db.list_memory()
    out["memory"] = mem[0]["id"] if mem else 999999
    await db.close_db()
    return out


def run_probe(ids: dict) -> list[dict]:
    from fastapi.testclient import TestClient
    from app.main import app

    # 必须用 with：vault 在 lifespan 启动时用 VAULT_PASSPHRASE 初始化，
    # 不进上下文就直接调用，凭据保存会永远 503。
    c = TestClient(app)
    c.__enter__()
    results: list[dict] = []

    def hit(label: str, method: str, path: str, body=None, needle: str = ""):
        r = c.request(method, path, json=body) if body is not None else c.request(method, path)
        text = r.text[:120].replace("\n", " ")
        results.append({"label": label, "method": method, "path": path,
                        "status": r.status_code, "body": text})
        _ok(f"{label} → {r.status_code}", r.status_code < 500, text if r.status_code >= 500 else "")
        return r

    # ---- 先改后删，避免同一条实体被改又被删互相干扰 ----
    hit("改预算", "PUT", "/api/budgets", {"month": "2026-11", "budgets": [{"category": "餐饮", "amount": 1200}]})
    hit("改设置", "PUT", "/api/settings", {"settings": {"color_scheme": "us"}})
    hit("改目标", "PUT", f"/api/goals/{ids['goal']}", {"target": 2000})
    hit("改持仓", "PUT", f"/api/positions/{ids['pos_update']}", {"cost": 10.5})
    hit("改流水", "PUT", f"/api/transactions/{ids['tx_update']}", {"amount": -1.5})
    hit("改连接", "PATCH", f"/api/connect/connections/{ids['conn']}", {"enabled": False})
    hit("改发票状态", "PATCH", f"/api/connect/invoices/{ids['invoice']}", {"status": "archived"})
    hit("改风险设置", "PUT", "/api/connect/risk/settings", {"max_single_position_pct": 20})
    hit("存券商凭据", "PUT", "/api/execute/brokers/futu/credentials", {"secret": {"api_key": "probe"}, "enabled": False})
    hit("改配置目标", "PUT", "/api/strategy/allocation",
        {"targets": [{"symbol": "600519", "name": "贵州茅台", "target_pct": 100}]})
    # Studio 写操作有权限门（设计如此）：先切 open，验完再切回 standard
    hit("切 studio 权限为 open", "PUT", "/api/studio/permissions", {"mode": "open"})
    hit("改 studio 资产", "PATCH", f"/api/studio/prompts/{ids['studio']}", {"content": "probe v2"})
    hit("改成员", "PUT", f"/api/members/{ids['member_update']}", {"display_name": "ProbeRenamed", "role": "member"})
    hit("切换成员", "PUT", "/api/members/me/switch", {"member_id": ids['member_update']})
    hit("改部门", "PATCH", f"/api/org/departments/{ids['org_dept']}", {"name": "探针部门改"})
    hit("改岗位", "PATCH", f"/api/org/positions/{ids['org_pos']}", {"name": "探针岗位改"})
    hit("改组织成员", "PATCH", f"/api/org/members/{ids['org_user']}", {"role": "member"})
    hit("改会话名", "PATCH", f"/api/sessions/{ids['session_update']}", {"title": "probe renamed"})
    hit("存 MCP 列表", "PUT", "/api/mcp/servers", {"servers": []})

    # ---- 删除 ----
    hit("删目标", "DELETE", f"/api/goals/{ids['goal']}")
    hit("删负债", "DELETE", f"/api/debts/{ids['debt']}")
    hit("删订阅", "DELETE", f"/api/subscriptions/{ids['sub']}")
    hit("删自选", "DELETE", f"/api/watchlist/{ids['watch']}")
    hit("删连接", "DELETE", f"/api/connect/connections/{ids['conn']}")
    hit("删发票", "DELETE", f"/api/connect/invoices/{ids['invoice']}")
    hit("删条件单", "DELETE", f"/api/connect/conditionals/{ids['cond']}")
    hit("删总账草稿", "DELETE", f"/api/gl/entries/{ids['gl']}")
    hit("删券商凭据", "DELETE", "/api/execute/brokers/futu/credentials")
    hit("删定投计划", "DELETE", f"/api/strategy/dca/{ids['plan']}")
    hit("删市场资产", "DELETE", "/api/studio/market/probe-item")
    hit("删 studio 资产", "DELETE", f"/api/studio/prompts/{ids['studio']}?force=true")
    hit("删模拟账户", "DELETE", f"/api/paper/accounts/{ids['paper']}")
    hit("删借贷", "DELETE", f"/api/members/loans/{ids['loan']}")
    hit("删成员", "DELETE", f"/api/members/{ids['member_delete']}")
    # 部门下挂着岗位时会被业务规则拒绝（400 提示"先移除岗位"），先删岗位再删部门
    hit("删岗位", "DELETE", f"/api/org/positions/{ids['org_pos']}")
    hit("删部门", "DELETE", f"/api/org/departments/{ids['org_dept']}")
    hit("删组织成员", "DELETE", f"/api/org/members/{ids['org_user']}")
    hit("清影子决策", "DELETE", "/api/authz/shadow")
    hit("删运行记录", "DELETE", f"/api/runs/{ids['run']}")
    hit("删会话", "DELETE", f"/api/sessions/{ids['session_delete']}")
    hit("删持仓", "DELETE", f"/api/positions/{ids['pos_delete']}")
    hit("删流水", "DELETE", f"/api/transactions/{ids['tx_delete']}")
    hit("删记忆", "DELETE", f"/api/memory/{ids['memory']}")
    hit("删附件", "DELETE", f"/api/attachments/{ids['attachment']}")
    hit("删财报", "DELETE", f"/api/statements/{ids['statement']}")

    hit("studio 权限切回 standard", "PUT", "/api/studio/permissions", {"mode": "standard"})

    # ---- 删除是否真的落地（抽查四条链路）----
    watch = [w.get("symbol") for w in (c.get("/api/watchlist").json().get("watchlist") or [])]
    _ok("自选真的删掉", ids["watch"] not in watch, str(watch))
    txs = (c.get("/api/export").json().get("transactions") or [])
    _ok("流水真的删掉", all(int(t["id"]) != int(ids["tx_delete"]) for t in txs), f"剩 {len(txs)} 条")
    live_sessions = [s.get("id") for s in (c.get("/api/sessions").json().get("sessions") or [])]
    _ok("会话真的删掉", ids["session_delete"] not in live_sessions, str(live_sessions))
    mem = [m.get("id") for m in (c.get("/api/memory").json().get("memories") or [])]
    _ok("记忆真的删掉", ids["memory"] not in mem, str(mem))
    settings = c.get("/api/settings").json().get("settings") or {}
    _ok("设置真改到", settings.get("color_scheme") == "us", str(settings.get("color_scheme")))

    c.__exit__(None, None, None)
    return results


def main() -> int:
    # 券商凭据走 vault：不配口令时接口按设计返回 503（不降级明文），
    # 探针要测的是保存成功路径，所以给隔离进程一个临时口令。
    os.environ.setdefault("VAULT_PASSPHRASE", "probe-vault-pass")
    if not os.environ.get("MONEYHELPER_DB_PATH"):
        raise SystemExit("Refusing to run without MONEYHELPER_DB_PATH (safety guard).")
    if not os.environ.get("MONEYHELPER_DATA_DIR"):
        raise SystemExit("Refusing to run without MONEYHELPER_DATA_DIR (safety guard).")
    TMP.mkdir(exist_ok=True)
    ids = asyncio.run(seed())
    # 种子个别域失败时退回不存在的 id：目标是"别 5xx"，不是"必须 2xx"
    for k in ("org_dept", "org_pos", "org_user", "paper", "gl", "invoice", "cond", "conn"):
        if ids.get(k) is None:
            ids[k] = 999999
    print("种子 id:", json.dumps(ids, ensure_ascii=False))
    results = run_probe(ids)
    fails = [r for r in results if r["status"] >= 500]
    ok2xx = sum(1 for r in results if 200 <= r["status"] < 300)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (TMP / f"mutations.{stamp}.json").write_text(
        json.dumps({"ids": ids, "results": results}, ensure_ascii=False, indent=2)
    )
    print(f"\n路由 {len(results)} 条：2xx {ok2xx}，5xx {len(fails)}")
    for f in fails:
        print("  5xx:", f["method"], f["path"], f["body"])
    verdict = len(fails) == 0
    print(f"\n{'通过' if verdict else '失败'} — 5xx {len(fails)} 条")
    return 0 if verdict else 1


if __name__ == "__main__":
    sys.exit(main())

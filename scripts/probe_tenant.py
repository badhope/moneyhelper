"""多租户隔离验收：两个账号各写各的，互不可见；无登录一律 401。

这是隐私红线：一处 `current_user_id()` 漏掉，B 就能在导出/列表里看到 A 的账。
单测按函数测，这里从 HTTP 打进去，用真 JWT 验。
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8087
sys.path.insert(0, str(ROOT / "backend"))


async def _seed() -> None:
    from app import db
    from app.db.tenant import reset_current_user_id, set_current_user_id

    await db.init_db()
    uid_a = await db.user_create("tenant_a", "password-a", display_name="A", role="admin")
    uid_b = await db.user_create("tenant_b", "password-b", display_name="B", role="user")
    for uid, item in ((uid_a, "A 的午餐"), (uid_b, "B 的房租")):
        tok = set_current_user_id(uid)
        try:
            await db.add_transaction("2026-11-20", item, "餐饮", -10)
        finally:
            reset_current_user_id(tok)


async def main() -> int:
    db_path = ROOT / ".tmp" / "tenant_probe.db"
    data_dir = ROOT / ".tmp" / "tenant_data"
    db_path.unlink(missing_ok=True)
    os.environ["MONEYHELPER_DB_PATH"] = str(db_path)
    os.environ["MONEYHELPER_DATA_DIR"] = str(data_dir)
    await _seed()

    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend"), "LLM_ENABLED": "0"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"],
        cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    rows: list[dict] = []

    def case(name: str, ok: bool, detail: str = "") -> None:
        rows.append({"case": name, "ok": ok, "detail": detail})

    try:
        import httpx

        base = f"http://127.0.0.1:{PORT}"
        for _ in range(60):
            try:
                async with httpx.AsyncClient(timeout=3) as c:
                    if (await c.get(f"{base}/api/health")).status_code < 500:
                        break
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(0.5)

        async with httpx.AsyncClient(timeout=20, base_url=base) as c:
            tok = {}
            for name, pwd in (("tenant_a", "password-a"), ("tenant_b", "password-b")):
                r = await c.post("/api/auth/login", json={"username": name, "password": pwd})
                tok[name] = (r.json().get("access_token") if r.status_code == 200 else "") or ""
                case(f"{name} 登录", r.status_code == 200 and bool(tok[name]), str(r.status_code))

            # A 的导出里只能有 A 的数据
            ea = await c.get("/api/export", headers={"Authorization": f"Bearer {tok['tenant_a']}"})
            eb = await c.get("/api/export", headers={"Authorization": f"Bearer {tok['tenant_b']}"})
            ta = json.dumps(ea.json(), ensure_ascii=False)
            tb = json.dumps(eb.json(), ensure_ascii=False)
            case("A 看不到 B 的账", "B 的房租" not in ta and "A 的午餐" in ta, f"{ea.status_code}")
            case("B 看不到 A 的账", "A 的午餐" not in tb and "B 的房租" in tb, f"{eb.status_code}")

            # 无登录访问业务数据：必须 401
            anon = await c.get("/api/export")
            case("无登录访问数据", anon.status_code == 401, str(anon.status_code))

            # 普通用户不能看账号列表，管理员可以
            users_b = await c.get("/api/auth/users", headers={"Authorization": f"Bearer {tok['tenant_b']}"})
            users_a = await c.get("/api/auth/users", headers={"Authorization": f"Bearer {tok['tenant_a']}"})
            case("普通用户无权看账号列表", users_b.status_code == 403, str(users_b.status_code))
            case("管理员可看账号列表", users_a.status_code == 200, str(users_a.status_code))

            # 越权改用别人的 token 前缀乱写：签名校验必须拒绝
            bad = await c.get("/api/export", headers={"Authorization": f"Bearer {tok['tenant_a'][:-3]}xxx"})
            case("篡改 JWT 拒绝", bad.status_code == 401, str(bad.status_code))
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    for x in rows:
        print(("✓" if x["ok"] else "✗"), x["case"], "—", x["detail"], flush=True)
    bad = [x for x in rows if not x["ok"]]
    print(f"\n通过 {len(rows) - len(bad)}/{len(rows)}")
    (ROOT / ".tmp" / "tenant_probe.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

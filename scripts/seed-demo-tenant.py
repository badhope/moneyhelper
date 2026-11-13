"""Seed a demo instance that exercises the global tenant switch (slice 7b).

Creates:
- account ``demo`` (instance admin) with a personal tenant;
- enterprise tenant ``Acme`` where ``demo`` is an admin member;
- a couple of GL accounts / a period in the enterprise tenant;
- one transaction in the personal ledger (to prove personal data does NOT move).

Usage (PowerShell):
  $env:MONEYHELPER_DATA_DIR="D:\\Moneyhelper\\.tmp\\demo-tenant"
  $env:PYTHONPATH="D:\\Moneyhelper\\backend"
  D:\\Moneyhelper\\.venv\\Scripts\\python.exe scripts\\seed-demo-tenant.py

Only touches the selected data dir; refuses to run without MONEYHELPER_DATA_DIR.
"""

from __future__ import annotations

import asyncio
import os

from app import db
from app.db.tenant import use_user


async def main() -> None:
    data_dir = os.environ.get("MONEYHELPER_DATA_DIR", "").strip()
    if not data_dir:
        raise SystemExit("Refusing to seed without MONEYHELPER_DATA_DIR (safety guard).")
    await db.init_db()

    try:
        uid = await db.user_create("demo", "demo123456", "演示管理员", "admin")
    except Exception:
        user = await db.user_get_by_username("demo")
        if user is None:
            raise
        uid = int(user["id"])
    print(f"user demo id={uid}")

    try:
        viewer_id = await db.user_create("viewer", "viewer123456", "只读同事", "user")
    except Exception:
        vuser = await db.user_get_by_username("viewer")
        if vuser is None:
            raise
        viewer_id = int(vuser["id"])
    print(f"user viewer id={viewer_id}")

    conn = await db._conn()
    await conn.execute(
        "INSERT OR IGNORE INTO tenants(id,name,kind,owner_user_id,status,created_at)"
        " VALUES(7100,'Acme 科技','enterprise',?,'active','2026-01-01')",
        (uid,),
    )
    await conn.execute(
        "INSERT OR IGNORE INTO org_memberships(tenant_id,user_id,role,status,created_at)"
        " VALUES(7100,?,'admin','active','2026-01-01')",
        (uid,),
    )
    await conn.execute(
        "INSERT OR IGNORE INTO org_memberships(tenant_id,user_id,role,status,created_at)"
        " VALUES(7100,?,'viewer','active','2026-01-01')",
        (viewer_id,),
    )
    await conn.commit()

    # 企业租户下的一点点总账数据，便于截图时看出"切过去看到的是另一份账"
    await db.gl_create_account(7100, "1001", "库存现金", "asset", None)
    await db.gl_create_account(7100, "4001", "营业收入", "income", None)
    await db.gl_create_period(7100, 2026, 11)

    # 个人账本的一笔流水：切换租户后它必须留在个人账本里
    with use_user(uid):
        await db.add_transaction("2026-11-12", "个人午餐", "餐饮", -38.5)

    await db.set_active_tenant(uid, 7100)
    await db.set_active_tenant(viewer_id, 7100)
    print("seeded: personal tenant + Acme enterprise tenant (active=Acme)")
    print("accounts: demo/demo123456 (admin), viewer/viewer123456 (viewer)")
    await db.close_db()


if __name__ == "__main__":
    asyncio.run(main())

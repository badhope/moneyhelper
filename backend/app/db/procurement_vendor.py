"""供应商：列表/创建/在用校验。"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..timeutil import now_str as _now
from ._core import _conn, fetch_all, fetch_one


async def vendor_list(tenant_id: int) -> list[dict[str, Any]]:
    return await fetch_all(
        "SELECT id,tenant_id,code,name,tax_no,contact,phone,status,created_at"
        " FROM vendors WHERE tenant_id=? ORDER BY code,id",
        (int(tenant_id),),
    )


async def vendor_create(
    tenant_id: int,
    code: str,
    name: str,
    tax_no: str = "",
    contact: str = "",
    phone: str = "",
) -> dict[str, Any]:
    clean_code = str(code or "").strip()[:30]
    clean_name = str(name or "").strip()[:120]
    if not clean_code or not clean_name:
        raise ValueError("供应商编码和名称不能为空")
    conn = await _conn()
    try:
        cur = await conn.execute(
            "INSERT INTO vendors(tenant_id,code,name,tax_no,contact,phone,status,created_at)"
            " VALUES(?,?,?,?,?,?,'active',?)",
            (
                int(tenant_id),
                clean_code,
                clean_name,
                str(tax_no or "")[:40],
                str(contact or "")[:60],
                str(phone or "")[:40],
                _now(),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("供应商编码已存在") from exc
    await conn.commit()
    row = await fetch_one(
        "SELECT id,tenant_id,code,name,tax_no,contact,phone,status,created_at"
        " FROM vendors WHERE tenant_id=? AND id=?",
        (int(tenant_id), int(cur.lastrowid)),
    )
    assert row is not None
    return dict(row)


async def _assert_vendor(tenant_id: int, vendor_id: int) -> dict[str, Any]:
    row = await fetch_one(
        "SELECT id,tenant_id,code,name,status FROM vendors WHERE tenant_id=? AND id=?",
        (int(tenant_id), int(vendor_id)),
    )
    if row is None or str(row["status"]) != "active":
        raise ValueError("供应商不存在或已停用")
    return dict(row)

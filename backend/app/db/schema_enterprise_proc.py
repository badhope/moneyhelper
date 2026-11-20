"""企业域建表 SQL · 采购（供应商 / 采购单 / 应付）。

从 schema_enterprise.py 按表组拆出；各段按原顺序拼回同一份 DDL。
"""

from __future__ import annotations

SQL = """CREATE TABLE IF NOT EXISTS vendors (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id  INTEGER NOT NULL,
    code       TEXT NOT NULL,
    name       TEXT NOT NULL,
    tax_no     TEXT NOT NULL DEFAULT '',
    contact    TEXT NOT NULL DEFAULT '',
    phone      TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_vendor_tenant_code
    ON vendors(tenant_id, code);

-- 采购单（切片 8）：审核只代表采购获批，不直接生成总账。
CREATE TABLE IF NOT EXISTS purchase_orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     INTEGER NOT NULL,
    po_no         TEXT NOT NULL,
    vendor_id     INTEGER NOT NULL,
    order_date    TEXT NOT NULL,
    expected_date TEXT NOT NULL DEFAULT '',
    amount_cents  INTEGER NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'draft',  -- draft/submitted/approved/cancelled
    approved_by   INTEGER,
    approved_at   TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT '',
    updated_at    TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_po_tenant_no
    ON purchase_orders(tenant_id, po_no);
CREATE INDEX IF NOT EXISTS idx_po_tenant_status
    ON purchase_orders(tenant_id, status, id DESC);

-- 应付单（切片 8）：审核通过生成「借费用/资产、贷应付」凭证草稿；
-- 付款时再生成「借应付、贷银行」凭证草稿，过账仍由会计确认。
CREATE TABLE IF NOT EXISTS payables (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id           INTEGER NOT NULL,
    payable_no          TEXT NOT NULL,
    vendor_id           INTEGER NOT NULL,
    po_id               INTEGER,
    invoice_no          TEXT NOT NULL DEFAULT '',
    invoice_date        TEXT NOT NULL,
    due_date            TEXT NOT NULL DEFAULT '',
    amount_cents        INTEGER NOT NULL,
    tax_cents           INTEGER NOT NULL DEFAULT 0,
    expense_account_id  INTEGER NOT NULL,
    payable_account_id  INTEGER NOT NULL,
    status              TEXT NOT NULL DEFAULT 'draft',  -- draft/submitted/approved/paid
    gl_entry_id         INTEGER,
    payment_id          INTEGER,
    approved_by         INTEGER,
    approved_at         TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT '',
    updated_at          TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_payable_tenant_no
    ON payables(tenant_id, payable_no);
CREATE INDEX IF NOT EXISTS idx_payable_tenant_status
    ON payables(tenant_id, status, id DESC);
"""

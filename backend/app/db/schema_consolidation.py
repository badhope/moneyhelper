"""多主体管理合并表（4.18.0）。

- `tenant_groups`：集团/管理合并范围，只有创建者本人可管理。
- `tenant_group_entities`：纳入合并的租户、持股比例与纳入方式。
- `consolidation_adjustments`：手工抵销分录的明细行，按 voucher_id 成组。

金额一律整数分；抵销分录在写入时校验借贷平衡，合并时只读已过账凭证。
"""

from __future__ import annotations

SQL = """
CREATE TABLE IF NOT EXISTS tenant_groups (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    owner_user_id INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active',
    created_at    TEXT NOT NULL DEFAULT '',
    updated_at    TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tenant_group_owner_name
    ON tenant_groups(owner_user_id, name) WHERE status='active';

CREATE TABLE IF NOT EXISTS tenant_group_entities (
    group_id      TEXT NOT NULL,
    tenant_id     INTEGER NOT NULL,
    ownership_pct REAL NOT NULL DEFAULT 100,
    method        TEXT NOT NULL DEFAULT 'full',  -- full / proportional
    sort_order    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (group_id, tenant_id)
);
CREATE INDEX IF NOT EXISTS idx_group_entities_order
    ON tenant_group_entities(group_id, sort_order, tenant_id);

CREATE TABLE IF NOT EXISTS consolidation_adjustments (
    id           TEXT PRIMARY KEY,
    group_id     TEXT NOT NULL,
    period       TEXT NOT NULL,              -- YYYY-MM
    voucher_id   TEXT NOT NULL,
    line_no      INTEGER NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    account_code TEXT NOT NULL,
    account_name TEXT NOT NULL DEFAULT '',
    account_type TEXT NOT NULL DEFAULT '',
    debit_cents  INTEGER NOT NULL DEFAULT 0,
    credit_cents INTEGER NOT NULL DEFAULT 0,
    memo         TEXT NOT NULL DEFAULT '',
    created_by   INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_consolidation_adj_line
    ON consolidation_adjustments(group_id, period, voucher_id, line_no);
CREATE INDEX IF NOT EXISTS idx_consolidation_adj_voucher
    ON consolidation_adjustments(group_id, period, voucher_id);
"""

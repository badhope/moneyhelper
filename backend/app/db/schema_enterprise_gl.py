"""企业域建表 SQL · 总账（科目 / 期间 / 分录 / 明细行）。

从 schema_enterprise.py 按表组拆出；各段按原顺序拼回同一份 DDL。
"""

from __future__ import annotations

SQL = """CREATE TABLE IF NOT EXISTS gl_accounts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id  INTEGER NOT NULL,
    code       TEXT NOT NULL,
    name       TEXT NOT NULL,
    type       TEXT NOT NULL,              -- asset/liability/equity/income/expense
    parent_id  INTEGER,
    is_active  INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_gl_account_tenant_code
    ON gl_accounts(tenant_id, code);
CREATE TABLE IF NOT EXISTS gl_periods (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id  INTEGER NOT NULL,
    year       INTEGER NOT NULL,
    month      INTEGER NOT NULL,
    start_date TEXT NOT NULL,
    end_date   TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'open',  -- open/closed
    created_at TEXT NOT NULL DEFAULT '',
    closed_at  TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_gl_period_tenant_ym
    ON gl_periods(tenant_id, year, month);
CREATE TABLE IF NOT EXISTS gl_entries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id    INTEGER NOT NULL,
    entry_no     TEXT NOT NULL,
    entry_date   TEXT NOT NULL,
    period_id    INTEGER NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'draft',  -- draft/posted
    source       TEXT NOT NULL DEFAULT 'manual', -- manual/reversal
    reversal_of  INTEGER,                        -- 反冲时指向原凭证
    created_by   INTEGER,
    created_at   TEXT NOT NULL DEFAULT '',
    posted_at    TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_gl_entry_tenant_no
    ON gl_entries(tenant_id, entry_no);
CREATE INDEX IF NOT EXISTS idx_gl_entry_tenant_period
    ON gl_entries(tenant_id, period_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_gl_entry_reversal
    ON gl_entries(tenant_id, reversal_of) WHERE reversal_of IS NOT NULL;
CREATE TABLE IF NOT EXISTS gl_entry_lines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   INTEGER NOT NULL,
    entry_id    INTEGER NOT NULL,
    line_no     INTEGER NOT NULL,
    account_id  INTEGER NOT NULL,
    debit_cents INTEGER NOT NULL DEFAULT 0,
    credit_cents INTEGER NOT NULL DEFAULT 0,
    memo        TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_gl_line_tenant_entry_no
    ON gl_entry_lines(tenant_id, entry_id, line_no);
CREATE INDEX IF NOT EXISTS idx_gl_line_tenant_account
    ON gl_entry_lines(tenant_id, account_id);

-- 报销单（切片 5b）：审核通过后生成总账凭证草稿，过账仍走 /api/gl。
-- 金额存整数分；申请人/审批人分离，企业租户下禁止自审。
"""

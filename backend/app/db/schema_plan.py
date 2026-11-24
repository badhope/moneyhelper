"""企业预算与资金计划建表 SQL（4.19.0）。

预算与资金计划都属于管理口径：不生成凭证、不划转资金、不改总账。
金额统一存整数分，期间统一 YYYY-MM。
"""

from __future__ import annotations

SQL = """CREATE TABLE IF NOT EXISTS enterprise_budget_plans (
    id         TEXT PRIMARY KEY,
    tenant_id  INTEGER NOT NULL,
    period     TEXT NOT NULL,
    name       TEXT NOT NULL DEFAULT '主预算',
    note       TEXT NOT NULL DEFAULT '',
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ent_budget_plan_name
    ON enterprise_budget_plans(tenant_id, period, name);
CREATE TABLE IF NOT EXISTS enterprise_budget_lines (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id      TEXT NOT NULL,
    tenant_id    INTEGER NOT NULL,
    account_code TEXT NOT NULL,
    account_name TEXT NOT NULL DEFAULT '',
    account_type TEXT NOT NULL DEFAULT '',
    amount_cents INTEGER NOT NULL DEFAULT 0,
    note         TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ent_budget_line_account
    ON enterprise_budget_lines(tenant_id, plan_id, account_code);
CREATE INDEX IF NOT EXISTS idx_ent_budget_line_plan
    ON enterprise_budget_lines(plan_id);

CREATE TABLE IF NOT EXISTS enterprise_cash_plans (
    id               TEXT PRIMARY KEY,
    tenant_id        INTEGER NOT NULL,
    period           TEXT NOT NULL,
    name             TEXT NOT NULL DEFAULT '资金计划',
    opening_cents    INTEGER NOT NULL DEFAULT 0,
    target_min_cents INTEGER NOT NULL DEFAULT 0,
    note             TEXT NOT NULL DEFAULT '',
    created_by       INTEGER,
    created_at       TEXT NOT NULL DEFAULT '',
    updated_at       TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ent_cash_plan_name
    ON enterprise_cash_plans(tenant_id, period, name);
CREATE TABLE IF NOT EXISTS enterprise_cash_plan_lines (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id       TEXT NOT NULL,
    tenant_id     INTEGER NOT NULL,
    expected_date TEXT NOT NULL,
    direction     TEXT NOT NULL,
    account_code  TEXT NOT NULL DEFAULT '1001',
    counterparty  TEXT NOT NULL DEFAULT '',
    amount_cents  INTEGER NOT NULL DEFAULT 0,
    certainty     TEXT NOT NULL DEFAULT 'medium',
    note          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ent_cash_plan_line_date
    ON enterprise_cash_plan_lines(tenant_id, plan_id, expected_date);
"""

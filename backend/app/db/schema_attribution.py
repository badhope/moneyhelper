"""收支归因确认表（4.17.1）。

归因本身不直接改账：规则/历史只产出候选，用户确认后才写回流水分类。
确认记录保留原分类、规则 id、命中维度与置信度，便于回溯“为什么改”。
"""

from __future__ import annotations

SQL = """
CREATE TABLE IF NOT EXISTS attribution_confirmations (
    tenant_id          INTEGER NOT NULL,
    user_id            INTEGER NOT NULL,
    transaction_id     INTEGER NOT NULL,
    original_category  TEXT NOT NULL DEFAULT '',
    confirmed_category TEXT NOT NULL DEFAULT '',
    source             TEXT NOT NULL DEFAULT 'rule',
    rule_id            TEXT NOT NULL DEFAULT '',
    confidence         REAL NOT NULL DEFAULT 0,
    matched_json       TEXT NOT NULL DEFAULT '[]',
    confirmed_at       TEXT NOT NULL DEFAULT '',
    updated_at         TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (tenant_id, user_id, transaction_id)
);
CREATE INDEX IF NOT EXISTS idx_attribution_confirmed_at
    ON attribution_confirmations(tenant_id, user_id, confirmed_at);

CREATE TABLE IF NOT EXISTS attribution_rules (
    tenant_id   INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    rule_id     TEXT NOT NULL,
    name        TEXT NOT NULL DEFAULT '',
    keyword     TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL DEFAULT '',
    direction   TEXT NOT NULL DEFAULT '',
    priority    INTEGER NOT NULL DEFAULT 0,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (tenant_id, user_id, rule_id)
);
CREATE INDEX IF NOT EXISTS idx_attribution_rules_enabled
    ON attribution_rules(tenant_id, user_id, enabled, priority);

CREATE TABLE IF NOT EXISTS attribution_rollbacks (
    id                 TEXT PRIMARY KEY,
    tenant_id          INTEGER NOT NULL,
    user_id            INTEGER NOT NULL,
    transaction_id     INTEGER NOT NULL,
    original_category  TEXT NOT NULL DEFAULT '',
    confirmed_category TEXT NOT NULL DEFAULT '',
    source             TEXT NOT NULL DEFAULT '',
    rule_id            TEXT NOT NULL DEFAULT '',
    reverted_at        TEXT NOT NULL DEFAULT '',
    created_at         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_attribution_rollbacks_at
    ON attribution_rollbacks(tenant_id, user_id, reverted_at);
"""

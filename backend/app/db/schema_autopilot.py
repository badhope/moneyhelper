"""AI 托管策略与执行决策（4.23.0）。

策略按用户与动作保存：手动、助理（先出计划再确认）、全自动。
决策表只记“这次是否执行、为什么”，不复制包体与账务明细。
"""

from __future__ import annotations

SQL = """
CREATE TABLE IF NOT EXISTS autopilot_policies (
    user_id INTEGER NOT NULL,
    action_key TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'manual',
    enabled INTEGER NOT NULL DEFAULT 1,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(user_id, action_key)
);

CREATE INDEX IF NOT EXISTS idx_autopilot_policies_user
    ON autopilot_policies(user_id, updated_at);

CREATE TABLE IF NOT EXISTS autopilot_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    action_key TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'manual',
    decision TEXT NOT NULL,
    summary_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_autopilot_decisions_user
    ON autopilot_decisions(user_id, created_at);
"""

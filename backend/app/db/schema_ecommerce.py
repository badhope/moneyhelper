"""电商测算场景（4.23.0）。

保存的是用户输入与当时的确定性结果，用于复盘和方案对比；
不覆盖旧版本，不做自动同步。
"""

from __future__ import annotations

SQL = """
CREATE TABLE IF NOT EXISTS ecommerce_scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    input_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ecommerce_scenarios_user
    ON ecommerce_scenarios(user_id, created_at);
"""

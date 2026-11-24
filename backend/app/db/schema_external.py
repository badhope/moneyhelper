"""外部投递通道与投递留痕（4.22.0）。

通道配置的敏感字段走 vault 加密后存 `secret_enc`；`config_json` 只放主机、
端口、收件人等非敏感参数。投递记录是“外部通道是否受理”的事实，不冒充
税局申报回执、银行支付回单或审计意见。
"""

from __future__ import annotations

SQL = """
CREATE TABLE IF NOT EXISTS external_channels (
    user_id INTEGER NOT NULL,
    channel_id TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}',
    secret_enc TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 0,
    last_test_at TEXT NOT NULL DEFAULT '',
    last_test_ok INTEGER,
    last_test_detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(user_id, channel_id)
);

CREATE INDEX IF NOT EXISTS idx_external_channels_user
    ON external_channels(user_id, updated_at);

CREATE TABLE IF NOT EXISTS external_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    channel_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    packet_id TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    idempotency_key TEXT NOT NULL,
    recipient TEXT NOT NULL DEFAULT '',
    request_summary TEXT NOT NULL DEFAULT '{}',
    receipt_json TEXT NOT NULL DEFAULT '{}',
    error_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, channel_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_external_deliveries_user
    ON external_deliveries(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_external_deliveries_packet
    ON external_deliveries(user_id, packet_id, created_at);
"""

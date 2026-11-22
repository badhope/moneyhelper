"""远程控制会话表：一次性配对令牌 + 设备令牌。

设计原则与 ZCode 的 Remote Control 一致：
- 链接本身是临时授权，不另建运行环境；
- 配对令牌短时有效、用后即焚；
- 设备令牌只存哈希，撤销立即失效；
- 会话到期自动拒绝，不留下长期后门。
"""

from __future__ import annotations

SCHEMA_REMOTE = """
CREATE TABLE IF NOT EXISTS remote_sessions (
    sid               TEXT PRIMARY KEY,
    user_id           INTEGER NOT NULL DEFAULT 0,
    label             TEXT NOT NULL DEFAULT '',
    pair_token_hash   TEXT NOT NULL DEFAULT '',
    pair_expires_at   TEXT NOT NULL,
    device_token_hash TEXT NOT NULL DEFAULT '',
    device_name       TEXT NOT NULL DEFAULT '',
    device_ua         TEXT NOT NULL DEFAULT '',
    device_ip         TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL,
    paired_at         TEXT NOT NULL DEFAULT '',
    last_seen_at      TEXT NOT NULL DEFAULT '',
    expires_at        TEXT NOT NULL,
    revoked_at        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_remote_sessions_user
    ON remote_sessions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_remote_sessions_expire
    ON remote_sessions(expires_at);
"""

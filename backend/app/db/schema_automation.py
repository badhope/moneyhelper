"""自动化运行审计表（4.17.0）。

一次工作流执行一行：手动补跑与 APScheduler 定时触发共用同一张表。
`steps_json` 保存每个真实步骤的返回值，前端只读展示，不在这里重复业务判断。
"""

SQL = """
-- 自动化运行台账：定时与手动补跑共用，幂等键为 (tenant_id, idempotency_key)。
CREATE TABLE IF NOT EXISTS automation_runs (
    id              TEXT PRIMARY KEY,
    tenant_id       INTEGER NOT NULL DEFAULT 0,
    user_id         INTEGER NOT NULL DEFAULT 0,
    workflow        TEXT NOT NULL,
    workflow_name   TEXT NOT NULL DEFAULT '',
    trigger         TEXT NOT NULL DEFAULT 'manual',   -- manual / schedule
    status          TEXT NOT NULL DEFAULT 'running',  -- running / done / partial / failed
    idempotency_key TEXT NOT NULL DEFAULT '',
    started_at      TEXT NOT NULL,
    finished_at     TEXT NOT NULL DEFAULT '',
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    steps_json      TEXT NOT NULL DEFAULT '[]',
    error           TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_automation_runs_tenant_time
    ON automation_runs(tenant_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_automation_runs_idempotency
    ON automation_runs(tenant_id, idempotency_key)
    WHERE idempotency_key <> '';

-- 死信告警：失败/部分失败的一次运行对应一条；acknowledged_at 为空表示未读。
CREATE TABLE IF NOT EXISTS automation_alerts (
    id              TEXT PRIMARY KEY,
    tenant_id       INTEGER NOT NULL DEFAULT 0,
    user_id         INTEGER NOT NULL DEFAULT 0,
    run_id          TEXT NOT NULL,
    workflow        TEXT NOT NULL,
    severity        TEXT NOT NULL DEFAULT 'error',   -- error / warning
    message         TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    acknowledged_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_automation_alerts_run
    ON automation_alerts(tenant_id, run_id);
CREATE INDEX IF NOT EXISTS idx_automation_alerts_tenant_time
    ON automation_alerts(tenant_id, created_at DESC);
"""

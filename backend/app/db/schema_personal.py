"""数据库表结构（DDL）·个人账本段。

从 schema_tables.py 拆出（原 8-269 行），内容逐字未改；三段按原序拼接成 SCHEMA。
"""

from __future__ import annotations

SCHEMA_PERSONAL = """
CREATE TABLE IF NOT EXISTS positions (
    symbol   TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    kind     TEXT NOT NULL DEFAULT '股票',
    industry TEXT NOT NULL DEFAULT '其他',
    shares   REAL NOT NULL,
    cost     REAL NOT NULL,
    last     REAL NOT NULL,
    buy_date TEXT,
    fee      REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS transactions (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    date     TEXT NOT NULL,
    item     TEXT NOT NULL,
    category TEXT NOT NULL,
    amount   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tx_month ON transactions(date);
CREATE TABLE IF NOT EXISTS subscriptions (
    name    TEXT PRIMARY KEY,
    monthly REAL NOT NULL,
    note    TEXT NOT NULL DEFAULT '',
    due_day TEXT NOT NULL DEFAULT ''   -- 每月几号扣款（'' 表示未设置）
);
CREATE TABLE IF NOT EXISTS debts (
    name     TEXT PRIMARY KEY,
    monthly  REAL NOT NULL,
    balance  REAL NOT NULL,
    rate     REAL NOT NULL,
    due_day  TEXT NOT NULL DEFAULT ''  -- 每月几号还款（'' 表示未设置）
);
CREATE TABLE IF NOT EXISTS settings (
    user_id INTEGER NOT NULL DEFAULT 0,
    key   TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);
CREATE TABLE IF NOT EXISTS budgets (
    user_id  INTEGER NOT NULL DEFAULT 0,
    month    TEXT NOT NULL,   -- YYYY-MM
    category TEXT NOT NULL,   -- __total 表示总预算，其余为分类预算
    amount   REAL NOT NULL,
    PRIMARY KEY (user_id, month, category)
);
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id     TEXT NOT NULL,
    question      TEXT NOT NULL,
    answer        TEXT NOT NULL,
    level         TEXT NOT NULL DEFAULT '',
    flags_json    TEXT NOT NULL DEFAULT '[]',
    created_at    TEXT NOT NULL,
    route         TEXT NOT NULL DEFAULT '',
    llm           TEXT NOT NULL DEFAULT '',
    route_reason  TEXT NOT NULL DEFAULT '',
    tools         TEXT NOT NULL DEFAULT '',
    actions       TEXT NOT NULL DEFAULT '[]',
    tokens_in     INTEGER NOT NULL DEFAULT 0,
    tokens_out    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_runs_thread ON runs(thread_id, id);
CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id  TEXT UNIQUE NOT NULL,
    title      TEXT NOT NULL DEFAULT '新会话',
    pinned     INTEGER NOT NULL DEFAULT 0,
    archived   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS goals (
    name       TEXT PRIMARY KEY,
    target     REAL NOT NULL,
    saved      REAL NOT NULL DEFAULT 0,
    deadline   TEXT NOT NULL DEFAULT '',   -- 目标月份 YYYY-MM（'' 未设）
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS watchlist (
    symbol     TEXT PRIMARY KEY,
    name       TEXT NOT NULL DEFAULT '',
    kind       TEXT NOT NULL DEFAULT '股票',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_memory (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    content    TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'fact', -- fact / preference / goal_related
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_actions (
    token      TEXT PRIMARY KEY,
    tool_name  TEXT NOT NULL,
    args       TEXT NOT NULL,
    summary    TEXT NOT NULL,
    lang       TEXT NOT NULL DEFAULT 'zh',
    status     TEXT NOT NULL DEFAULT 'pending',  -- pending / consumed / cancelled / expired
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
-- 部门模式呈批件（M3.5）：秘书产出的呈批件 + 老板审批状态。
-- 独立成表而不是塞进 runs：呈批件有订单明细、对账冲突与审批链，
-- 与问答历史是不同生命周期（待批/已批/驳回/追问）。
CREATE TABLE IF NOT EXISTS dept_reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id    TEXT NOT NULL UNIQUE,      -- 对外暴露的 ID
    question     TEXT NOT NULL,
    dispatch     TEXT NOT NULL DEFAULT '',  -- llm / rules
    verdict      TEXT NOT NULL DEFAULT '',
    report       TEXT NOT NULL,             -- 呈批件正文（Markdown）
    orders_json  TEXT NOT NULL DEFAULT '[]',
    conflicts_json TEXT NOT NULL DEFAULT '[]',
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending/approved/rejected/inquired
    decision_note TEXT NOT NULL DEFAULT '',        -- 驳回理由 / 追问内容
    decided_at   TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dept_reports_status ON dept_reports(status);
CREATE TABLE IF NOT EXISTS conversation_summary (
    thread_id  TEXT PRIMARY KEY,
    summary    TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'llm',  -- llm / heuristic / reset
    covered_to INTEGER NOT NULL DEFAULT 0,   -- 已纳入摘要的最新 runs.id
    updated_at TEXT NOT NULL
);
-- 经验库（P1 反思）：记录工具失败的「踩坑点」，下次反思时参考，避免重复犯错。
CREATE TABLE IF NOT EXISTS reflections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tool        TEXT NOT NULL,
    args_json   TEXT NOT NULL DEFAULT '{}',
    error       TEXT NOT NULL DEFAULT '',
    lesson      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    resolved_at TEXT NOT NULL DEFAULT ''     -- 非空表示已被「后来成功」标记解决
);
-- 审计追踪 Provenance：每个金额变动操作的完整来龙去脉
CREATE TABLE IF NOT EXISTS provenance_log (
    id           TEXT PRIMARY KEY,
    timestamp    TEXT NOT NULL,
    action       TEXT NOT NULL,
    entity_type  TEXT NOT NULL,
    entity_id    TEXT,
    before_json  TEXT,
    after_json   TEXT,
    source       TEXT NOT NULL DEFAULT 'api',
    username     TEXT NOT NULL DEFAULT 'system',
    metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_provenance_entity ON provenance_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_provenance_timestamp ON provenance_log(timestamp);
-- 审计日志（P2 金融级治理）：记录写操作与敏感读，支持追溯。
CREATE TABLE IF NOT EXISTS audit_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    action      TEXT NOT NULL,          -- WRITE / READ_SENSITIVE / AUTH
    method      TEXT NOT NULL,
    path        TEXT NOT NULL,
    status      INTEGER NOT NULL,
    actor       TEXT NOT NULL DEFAULT '', -- 稳定身份：user:<id> / 共享口令用户名 / local
    detail      TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    prev_hash   TEXT NOT NULL DEFAULT '', -- 上一条的 entry_hash（租户内链）
    entry_hash  TEXT NOT NULL DEFAULT ''  -- 本条规范化字段的 SHA-256
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_logs(ts DESC);
-- 附件（P2 能力扩展）：对话中引用本地文件，附文本内容供模型理解。
CREATE TABLE IF NOT EXISTS attachments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filename    TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'text',   -- text / csv / pdf
    size        INTEGER NOT NULL DEFAULT 0,
    content     TEXT NOT NULL DEFAULT '',       -- 提取后的文本内容（上限）
    indexed     INTEGER NOT NULL DEFAULT 0,     -- 1 = 加入知识库（问答时参与检索）
    created_at  TEXT NOT NULL
);
-- 撤销记录（P2 金融级治理）：流水 / 持仓 / 负债 / 订阅 / 目标写操作前的全量快照，
-- 供 undo 端点恢复原状。before_json 为空串 '{}' 表示实体此前不存在（新增前的快照）。
CREATE TABLE IF NOT EXISTS undo_records (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    entity         TEXT NOT NULL,     -- transaction | position | debt | subscription | goal
    entity_id      TEXT NOT NULL,     -- 实体主键值（position.symbol / transactions.id / debt.name 等）
    before_json    TEXT NOT NULL,     -- 旧行 JSON；空串 '{}' 表示实体此前不存在（INSERT 前的快照）
    reason         TEXT NOT NULL DEFAULT '',
    consumed_at    TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_undo_entity ON undo_records(entity, entity_id);
CREATE INDEX IF NOT EXISTS idx_undo_consumed ON undo_records(consumed_at);
-- 用户体系（P0 多租户）：bcrypt 哈希 + 下次登录修改密码标志 + 软删除
CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    username     TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    role         TEXT NOT NULL DEFAULT 'user',  -- admin | user
    disabled     INTEGER NOT NULL DEFAULT 0,
    last_login   TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    active_tenant_id INTEGER                   -- 切片 7b：用户显式选择的工作租户
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
-- 加密密钥封装（P0 安全加固）：Fernet 密钥由口令派生后加密存储在 DB，
-- 解密时调用方提供主口令 → 临时解密出 Fernet 密钥 → 用于加解密 ai_api_key 等敏感配置。
-- 这避免了在 DB 里明文落 ai_api_key / 邮件 smtp 密码等。
CREATE TABLE IF NOT EXISTS vault_keys (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key_name    TEXT UNIQUE NOT NULL,           -- 'app'（全局应用密钥）等
    enc_key     TEXT NOT NULL,                  -- 加密后的 Fernet key (b64)
    kdf_salt    TEXT NOT NULL,                  -- b64 salt
    kdf_iters   INTEGER NOT NULL,
    created_at  TEXT NOT NULL
);
-- 家庭成员表：家庭共享账本的核心实体
CREATE TABLE IF NOT EXISTS members (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL DEFAULT 0,
    username     TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    role         TEXT NOT NULL DEFAULT 'member',  -- owner/admin/member/viewer
    avatar_color TEXT NOT NULL DEFAULT '#b8891f',
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
-- 成员间借贷
CREATE TABLE IF NOT EXISTS member_loans (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    from_member_id INTEGER NOT NULL REFERENCES members(id),
    to_member_id   INTEGER NOT NULL REFERENCES members(id),
    amount         REAL NOT NULL,
    currency       TEXT NOT NULL DEFAULT 'CNY',
    note           TEXT NOT NULL DEFAULT '',
    settled        INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    settled_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_member_loans_from ON member_loans(from_member_id);
CREATE INDEX IF NOT EXISTS idx_member_loans_to ON member_loans(to_member_id);
-- 家庭议会（v4.8）：重大支出/资金调拨需多人表决，避免"一个人说了算"
CREATE TABLE IF NOT EXISTS family_motions (
    user_id      INTEGER NOT NULL DEFAULT 0,
    id           TEXT NOT NULL,
    title        TEXT NOT NULL,
    amount       REAL NOT NULL DEFAULT 0,
    category     TEXT NOT NULL DEFAULT '',
    note         TEXT NOT NULL DEFAULT '',
    proposer_id  INTEGER,
    status       TEXT NOT NULL DEFAULT 'voting',  -- voting/approved/rejected/withdrawn
    created_at   TEXT NOT NULL DEFAULT '',
    decided_at   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, id)
);
CREATE INDEX IF NOT EXISTS idx_family_motions_user ON family_motions(user_id, status);
CREATE TABLE IF NOT EXISTS family_votes (
    user_id      INTEGER NOT NULL DEFAULT 0,
    motion_id    TEXT NOT NULL,
    member_id    INTEGER NOT NULL,
    vote         TEXT NOT NULL,                   -- yes/no/abstain
    note         TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, motion_id, member_id)
);
-- 目标配置（再平衡）：每个标的的目标权重；symbol=CASH 表示现金目标
"""


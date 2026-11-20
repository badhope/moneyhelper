"""数据库表结构（DDL）·投资与连接段（含券商、行情、目标配置）。

从 schema_tables.py 拆出（原 271-507 行），内容逐字未改。
"""

from __future__ import annotations

SCHEMA_INVEST = """CREATE TABLE IF NOT EXISTS allocation_targets (
    user_id    INTEGER NOT NULL DEFAULT 0,
    symbol     TEXT NOT NULL,
    name       TEXT NOT NULL DEFAULT '',
    target_pct REAL NOT NULL,
    updated_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, symbol)
);
-- 定投计划：一句「每月 10 号定投 3000 中证500」落成可跟踪的计划
CREATE TABLE IF NOT EXISTS dca_plans (
    user_id     INTEGER NOT NULL DEFAULT 0,
    id          TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    name        TEXT NOT NULL DEFAULT '',
    amount      REAL NOT NULL,
    frequency   TEXT NOT NULL DEFAULT 'monthly',  -- monthly / weekly
    day         INTEGER NOT NULL DEFAULT 1,        -- 月：几号；周：星期几(1-7)
    start_date  TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, id)
);
-- 财报分析（v4.0）：上传/粘贴的三表 JSON 落库，可随时重新分析
CREATE TABLE IF NOT EXISTS financial_statements (
    user_id    INTEGER NOT NULL DEFAULT 0,
    id         TEXT NOT NULL,
    company    TEXT NOT NULL,
    currency   TEXT NOT NULL DEFAULT 'CNY',
    payload    TEXT NOT NULL,        -- 标准化三表 JSON（分析输入）
    report     TEXT NOT NULL DEFAULT '',  -- 最近一次报告文本快照
    created_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, id)
);
-- 团队模拟盘（v4.2）：事件溯源式账户。账户=开户参数（初始资金），
-- 持仓/现金/成本全部由 paper_trades 重放得出；paper_snapshots 仅作净值曲线存档。
CREATE TABLE IF NOT EXISTS paper_accounts (
    user_id      TEXT NOT NULL,
    account_id   TEXT NOT NULL,
    name         TEXT NOT NULL DEFAULT '',
    initial_cash REAL NOT NULL DEFAULT 100000,
    created_at   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, account_id)
);
CREATE TABLE IF NOT EXISTS paper_trades (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    account_id TEXT NOT NULL,
    date       TEXT NOT NULL,        -- ISO 时间（Asia/Shanghai）
    symbol     TEXT NOT NULL,
    name       TEXT NOT NULL DEFAULT '',
    side       TEXT NOT NULL,        -- buy / sell
    price      REAL NOT NULL,
    shares     REAL NOT NULL,
    fee        REAL NOT NULL DEFAULT 0,
    amount     REAL NOT NULL         -- 成交额（不含费）
);
CREATE INDEX IF NOT EXISTS idx_paper_trades_account ON paper_trades(user_id, account_id);
CREATE TABLE IF NOT EXISTS paper_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT NOT NULL,
    account_id   TEXT NOT NULL,
    date         TEXT NOT NULL,      -- YYYY-MM-DD
    equity       REAL NOT NULL,
    cash         REAL NOT NULL,
    market_value REAL NOT NULL
);

-- 净值快照（每日）：净资产序列 + 归因所需的分项。
-- 为什么必须有：没有历史快照就问不出「净值涨了是攒的还是涨的」——
-- 用手工记账差分只能看到净流入，看不到市场波动贡献。TWR/归因/趋势图
-- 全部依赖这张表；一天一行，写入幂等（同日覆盖）。
CREATE TABLE IF NOT EXISTS net_worth_snapshots (
    user_id       INTEGER NOT NULL DEFAULT 0,
    date          TEXT NOT NULL,               -- YYYY-MM-DD（Asia/Shanghai）
    total_assets  REAL NOT NULL DEFAULT 0,     -- 资产合计（含现金）
    total_liabilities REAL NOT NULL DEFAULT 0, -- 负债合计
    net_worth     REAL NOT NULL DEFAULT 0,
    cash          REAL NOT NULL DEFAULT 0,
    market_value  REAL NOT NULL DEFAULT 0,     -- 非现金持仓市值
    source        TEXT NOT NULL DEFAULT '',    -- quotes / snapshot（估值口径）
    created_at    TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, date)
);
CREATE INDEX IF NOT EXISTS idx_nws_user_date ON net_worth_snapshots(user_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_paper_snapshots_account ON paper_snapshots(user_id, account_id, date);
-- 连接中心（v4.4）：外部数据源 / 资金账户接入。凭据一律不落库：
-- account_ref 只存「后四位」这类辨识信息，meta_json 只存用户可见的展示字段。
CREATE TABLE IF NOT EXISTS connect_accounts (
    user_id      INTEGER NOT NULL DEFAULT 0,
    id           TEXT NOT NULL,
    connector_id TEXT NOT NULL,
    label        TEXT NOT NULL DEFAULT '',
    kind         TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'unconfigured',
    account_ref  TEXT NOT NULL DEFAULT '',
    meta_json    TEXT NOT NULL DEFAULT '{}',
    last_sync_at TEXT NOT NULL DEFAULT '',
    last_error   TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, id)
);
CREATE INDEX IF NOT EXISTS idx_connect_accounts_user ON connect_accounts(user_id, connector_id);
-- 一次性配对码：浏览器代登录 / 书签脚本回传的短时凭据（10 分钟，用后即焚）
CREATE TABLE IF NOT EXISTS connect_pairings (
    user_id      INTEGER NOT NULL DEFAULT 0,
    code         TEXT NOT NULL,
    connector_id TEXT NOT NULL,
    expires_at   TEXT NOT NULL DEFAULT '',
    used_at      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, code)
);
-- 同步任务：用户点「同步」或系统定时拉取的一次执行记录
CREATE TABLE IF NOT EXISTS connect_jobs (
    user_id      INTEGER NOT NULL DEFAULT 0,
    id           TEXT NOT NULL,
    connector_id TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'sync',
    status       TEXT NOT NULL DEFAULT 'queued',
    progress     REAL NOT NULL DEFAULT 0,
    message      TEXT NOT NULL DEFAULT '',
    result_json  TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL DEFAULT '',
    finished_at  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, id)
);
CREATE INDEX IF NOT EXISTS idx_connect_jobs_user ON connect_jobs(user_id, created_at);
-- 交易意图：可审计的下单指令。paper=模拟盘直接执行；live=生成交接单，用户在券商页面确认成交
CREATE TABLE IF NOT EXISTS connect_intents (
    user_id      INTEGER NOT NULL DEFAULT 0,
    id           TEXT NOT NULL,
    connector_id TEXT NOT NULL DEFAULT '',
    symbol       TEXT NOT NULL,
    name         TEXT NOT NULL DEFAULT '',
    side         TEXT NOT NULL,
    price        REAL NOT NULL,
    shares       REAL NOT NULL,
    amount       REAL NOT NULL,
    mode         TEXT NOT NULL DEFAULT 'paper',
    status       TEXT NOT NULL DEFAULT 'awaiting_confirm',
    note         TEXT NOT NULL DEFAULT '',
    result_json  TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL DEFAULT '',
    executed_at  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, id)
);
CREATE INDEX IF NOT EXISTS idx_connect_intents_user ON connect_intents(user_id, created_at);
-- 发票归档（v4.5）：OFD/PDF/文本解析结果。票面字段可空（解析不全时留待人工补录），
-- file_hash 用于防重复归档（同文件重复上传只保留一条）。
CREATE TABLE IF NOT EXISTS invoices (
    user_id        INTEGER NOT NULL DEFAULT 0,
    id             TEXT NOT NULL,
    file_name      TEXT NOT NULL DEFAULT '',
    file_hash      TEXT NOT NULL DEFAULT '',
    source_format  TEXT NOT NULL DEFAULT '',
    invoice_code   TEXT NOT NULL DEFAULT '',
    invoice_number TEXT NOT NULL DEFAULT '',
    invoice_date   TEXT NOT NULL DEFAULT '',
    buyer          TEXT NOT NULL DEFAULT '',
    seller         TEXT NOT NULL DEFAULT '',
    item           TEXT NOT NULL DEFAULT '',
    total_amount   REAL,
    tax_amount     REAL,
    tax_rate       TEXT NOT NULL DEFAULT '',
    kind           TEXT NOT NULL DEFAULT '',
    confidence     TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'parsed',
    note           TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, id)
);
CREATE INDEX IF NOT EXISTS idx_invoices_user ON invoices(user_id, invoice_date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_invoices_hash ON invoices(user_id, file_hash);
-- 持仓对账单导入记录（v4.5）：保留原始预览与结果，便于回溯"哪次导入改了什么"
CREATE TABLE IF NOT EXISTS brokerage_imports (
    user_id      INTEGER NOT NULL DEFAULT 0,
    id           TEXT NOT NULL,
    file_name    TEXT NOT NULL DEFAULT '',
    file_hash    TEXT NOT NULL DEFAULT '',
    account      TEXT NOT NULL DEFAULT '',
    position_count INTEGER NOT NULL DEFAULT 0,
    applied      INTEGER NOT NULL DEFAULT 0,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    created_at   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, id)
);
CREATE INDEX IF NOT EXISTS idx_brokerage_imports_user ON brokerage_imports(user_id, created_at);
-- 条件单（v4.5）：价格触发型指令。只生成待确认意图，不代下单。
CREATE TABLE IF NOT EXISTS conditional_orders (
    user_id      INTEGER NOT NULL DEFAULT 0,
    id           TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    name         TEXT NOT NULL DEFAULT '',
    side         TEXT NOT NULL,
    trigger_type TEXT NOT NULL DEFAULT 'price_below',
    trigger_value REAL NOT NULL,
    price        REAL NOT NULL,
    shares       REAL NOT NULL,
    mode         TEXT NOT NULL DEFAULT 'paper',
    status       TEXT NOT NULL DEFAULT 'watching',
    note         TEXT NOT NULL DEFAULT '',
    triggered_at TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, id)
);
CREATE INDEX IF NOT EXISTS idx_conditional_orders_user ON conditional_orders(user_id, status);
-- 风控设置（v4.5）：单行键值，与 settings 分表避免污染用户配置
CREATE TABLE IF NOT EXISTS trade_risk_settings (
    user_id            INTEGER NOT NULL DEFAULT 0,
    daily_limit        REAL NOT NULL DEFAULT 200000,
    deviation_pct      REAL NOT NULL DEFAULT 3.0,
    concentration_pct  REAL NOT NULL DEFAULT 30.0,
    auto_execute_paper INTEGER NOT NULL DEFAULT 1,
    updated_at         TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id)
);
-- 券商凭据（v4.7）：JSON 整体用 vault 加密，API 只返回字段名与是否已配置。
-- 绝不把 private_key / access_token / password 写入普通 meta_json。
CREATE TABLE IF NOT EXISTS broker_credentials (
    user_id      INTEGER NOT NULL DEFAULT 0,
    broker_id    TEXT NOT NULL,
    label        TEXT NOT NULL DEFAULT '',
    secret_enc   TEXT NOT NULL DEFAULT '',
    meta_json    TEXT NOT NULL DEFAULT '{}',
    enabled      INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, broker_id)
);
CREATE INDEX IF NOT EXISTS idx_broker_credentials_user ON broker_credentials(user_id);

-- 企业组织影子模型（切片 1）：只建立事实表，不改现有 user_id 鉴权与账本。
-- 说明：暂不声明外键，避免在 tenant 切换完成前把历史用户/本地租户 0 卡死；
-- 等 current_user_id -> tenant_id 切换时再补 FK 与行级权限。
"""


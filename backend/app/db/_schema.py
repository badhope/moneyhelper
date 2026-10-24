"""数据库 schema 与种子数据（从 _core.py 拆出）。

这些是纯常量，没有逻辑、没有全局状态：改表结构或示例数据时只需动这里，
不必在 600 行的连接/CRUD 文件里翻找。_core.py 在建表时引用 SCHEMA /
DEFAULT_SETTINGS，种子逻辑通过 SEED_* 常量取数。
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# 种子数据：一套典型中产家庭的示例（用户可在"记账"页改成自己的真实数据）
# --------------------------------------------------------------------------

SEED_POSITIONS = [
    {
        "symbol": "600519",
        "name": "贵州茅台",
        "kind": "股票",
        "industry": "白酒",
        "shares": 100,
        "cost": 1680.00,
        "last": 1521.00,
    },
    {
        "symbol": "510300",
        "name": "沪深300ETF",
        "kind": "ETF",
        "industry": "宽基指数",
        "shares": 8000,
        "cost": 3.85,
        "last": 4.06,
    },
    {
        "symbol": "110011",
        "name": "易方达中小盘混合",
        "kind": "基金",
        "industry": "主动权益",
        "shares": 12000,
        "cost": 4.10,
        "last": 3.58,
    },
    {
        "symbol": "CASH",
        "name": "活期现金",
        "kind": "现金",
        "industry": "现金",
        "shares": 1,
        "cost": 55000.00,
        "last": 55000.00,
    },
]

# day_in_month: 尽量落在本月已过去的日期（今日之前），保证"本月"口径成立
SEED_TRANSACTIONS = [
    (2, "工资入账", "收入", 24800.0),
    (3, "房租", "居住", -5200.0),
    (5, "外卖餐饮", "餐饮", -1860.0),
    (7, "视频会员（年付）", "订阅", -258.0),
    (9, "通勤地铁", "交通", -320.0),
    (11, "健身私教", "订阅", -1999.0),
    (13, "添置家电", "购物", -4300.0),
    (15, "基金定投", "投资", -3000.0),
    (17, "云盘会员", "订阅", -168.0),
    (19, "聚餐", "餐饮", -960.0),
    (20, "信用卡还款", "还款", -3200.0),
]

SEED_SUBSCRIPTIONS = [
    {"name": "云盘会员", "monthly": 14.0, "note": "可合并到家庭共享", "due_day": "1"},
    {
        "name": "健身私教",
        "monthly": 1999.0,
        "note": "占订阅支出绝大部分",
        "due_day": "5",
    },
    {"name": "流媒体", "monthly": 21.5, "note": "与年付会员功能重叠", "due_day": "28"},
]

SEED_DEBTS = [
    {
        "name": "房贷",
        "monthly": 6800.0,
        "balance": 1280000.0,
        "rate": 0.0345,
        "due_day": "15",
    },
    {
        "name": "信用卡分期",
        "monthly": 900.0,
        "balance": 7200.0,
        "rate": 0.13,
        "due_day": "10",
    },
]

SEED_SETTINGS = {
    "monthly_income": "24800",
    "emergency_target_months": "6",
    # 应急金覆盖所需的"必要月支出"口径：居住 + 餐饮 + 交通 三类
    "essential_categories": "居住,餐饮,交通",
    # 行情源：auto（东财优先，失败降级快照）| snapshot | eastmoney
    "quote_source_mode": "auto",
    # 定时晨报时间（HH:MM）
    "report_time": "08:00",
    # ---- 功能开关（设置中心可自定义）----
    "voice_input": "off",  # 问答语音输入（浏览器支持时）
    # 适老化：正文缩放（normal/large/xlarge）与高对比度（on/off）
    "text_scale": "normal",
    "high_contrast": "off",
    "show_export": "on",  # 回答导出/复制按钮
    "expand_process": "off",  # 分析过程默认展开
    "show_suggestions": "off",  # 问答页建议入口（R4 起输入区常驻快捷指令 chips，空态建议默认关）
    "auto_refresh": "off",  # 仪表盘定时自动刷新
    "auto_refresh_seconds": "300",  # 自动刷新间隔（秒）
    "compact_numbers": "on",  # 大金额缩写（万/亿）
    "color_scheme": "cn",  # 涨跌颜色：cn 红涨绿跌（A股惯例）| us 绿涨红跌（海外惯例）
    "default_tab": "chat",  # 默认首页：overview|holdings|market|ledger|chat（对话中枢为主，可在设置改回）
    "savings_goal": "20",  # 储蓄率目标（%）
    # ---- AI 回答（OpenAI 兼容端点，可配任意国产/海外模型；失败自动降级模板）----
    "ai_enabled": "on",  # 是否启用 AI 回答（AI 优先；三要素未配或调用失败时回退内置分析）
    "ai_base_url": "",  # 国产示例：DeepSeek https://api.deepseek.com/v1 · 豆包 https://ark.cn-beijing.volces.com/api/v3 · 通义 https://dashscope.aliyuncs.com/compatible-mode/v1
    "ai_api_key": "",  # 仅存本机数据库
    "ai_model": "",  # 对应端点模型：deepseek-chat / doubao 接入点 ID / qwen-plus
    # ---- 模型点亮：设置页可勾选启用哪些模型，逗号分隔的模型名（默认点亮前两个）----
    "enabled_models": "deepseek-chat,qwen-plus",
    # ---- Agent 行为（可配置化：工具轮次 / 规划展示 / 失败反思重试）----
    "agent_tool_turns": "5",  # 单轮问答里模型可调用工具的轮次上限（1-30，防死循环）
    "agent_plan": "on",  # 是否展示执行计划（supervisor 计划卡 / 推理轨迹）
    "agent_reflect": "on",  # 工具失败时是否提示模型反思修正后重试
    "custom_system_prompt": "",  # 自定义系统提示词（留空用 agents/supervisor/instructions.md）
    "knowledge_enabled": "on",  # 知识库检索开关
    "data_note": "seed",
}

# 版本化默认设置：新增键时对已有库补齐默认值
DEFAULT_SETTINGS = {k: v for k, v in SEED_SETTINGS.items()}

SCHEMA = """
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
    actions       TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_runs_thread ON runs(thread_id, id);
CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id  TEXT UNIQUE NOT NULL,
    title      TEXT NOT NULL DEFAULT '新会话',
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
    actor       TEXT NOT NULL DEFAULT '', -- 来源 IP / 用户标识
    detail      TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER NOT NULL DEFAULT 0
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
    created_at   TEXT NOT NULL
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
-- 目标配置（再平衡）：每个标的的目标权重；symbol=CASH 表示现金目标
CREATE TABLE IF NOT EXISTS allocation_targets (
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
"""

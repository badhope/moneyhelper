"""企业域建表 SQL · 报销、付款、银行流水与对账、授权影子日志。

从 schema_enterprise.py 按表组拆出；各段按原顺序拼回同一份 DDL。
"""

from __future__ import annotations

SQL = """CREATE TABLE IF NOT EXISTS expense_claims (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id          INTEGER NOT NULL,
    claim_no           TEXT NOT NULL,
    title              TEXT NOT NULL,
    applicant_user_id  INTEGER NOT NULL,
    department_id      INTEGER,
    amount_cents       INTEGER NOT NULL,
    category           TEXT NOT NULL DEFAULT '',
    expense_account_id INTEGER NOT NULL,
    credit_account_id  INTEGER NOT NULL,
    invoice_ref        TEXT NOT NULL DEFAULT '',
    attachment_name    TEXT NOT NULL DEFAULT '',
    status             TEXT NOT NULL DEFAULT 'draft',  -- draft/submitted/approved/rejected
    approved_by        INTEGER,
    approved_at        TEXT NOT NULL DEFAULT '',
    rejected_reason    TEXT NOT NULL DEFAULT '',
    gl_entry_id        INTEGER,
    created_at         TEXT NOT NULL DEFAULT '',
    updated_at         TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_expense_claim_tenant_no
    ON expense_claims(tenant_id, claim_no);
CREATE INDEX IF NOT EXISTS idx_expense_claim_tenant_status
    ON expense_claims(tenant_id, status, id DESC);

-- 付款（切片 6）：出纳登记，不重复生成总账凭证（凭证在报销审批时已生成）。
CREATE TABLE IF NOT EXISTS payments (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id      INTEGER NOT NULL,
    payment_no     TEXT NOT NULL,
    claim_id       INTEGER NOT NULL DEFAULT 0,  -- 0 = 非报销付款（切片 8 应付）
    payable_id     INTEGER,
    amount_cents   INTEGER NOT NULL,
    payee          TEXT NOT NULL DEFAULT '',
    bank_account_id INTEGER NOT NULL,
    method         TEXT NOT NULL DEFAULT 'bank',
    status         TEXT NOT NULL DEFAULT 'paid',  -- paid
    paid_at        TEXT NOT NULL DEFAULT '',
    gl_entry_id    INTEGER,                        -- 应付付款会生成付款凭证草稿
    created_by     INTEGER,
    note           TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT '',
    updated_at     TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_tenant_no
    ON payments(tenant_id, payment_no);
-- 付款唯一性按来源拆分的两个部分索引不在这里建：老库的 payments 表还没有
-- payable_id 列，executescript(SCHEMA) 会因列不存在直接失败。
-- 统一由 _migrate_add_columns() 在补列之后创建（新库同样走那里）。
CREATE INDEX IF NOT EXISTS idx_payment_tenant_date
    ON payments(tenant_id, paid_at DESC);

-- 银行流水（切片 6）：amount 为正数，direction 决定收支；匹配付款后进入 matched。
CREATE TABLE IF NOT EXISTS bank_transactions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id      INTEGER NOT NULL,
    bank_account_id INTEGER NOT NULL,
    txn_date       TEXT NOT NULL,
    direction      TEXT NOT NULL,              -- in / out
    amount_cents   INTEGER NOT NULL,
    counterparty   TEXT NOT NULL DEFAULT '',
    memo           TEXT NOT NULL DEFAULT '',
    bank_ref       TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'unmatched',  -- unmatched/matched/ignored
    payment_id     INTEGER,
    matched_by     INTEGER,
    matched_at     TEXT NOT NULL DEFAULT '',
    gl_entry_id    INTEGER,                    -- 由该流水自动生成的凭证（幂等标记）
    created_at     TEXT NOT NULL DEFAULT '',
    updated_at     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_bank_txn_tenant_status
    ON bank_transactions(tenant_id, status, txn_date DESC);
CREATE INDEX IF NOT EXISTS idx_bank_txn_tenant_account
    ON bank_transactions(tenant_id, bank_account_id, txn_date DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bank_txn_payment
    ON bank_transactions(tenant_id, payment_id) WHERE payment_id IS NOT NULL;

-- 对账签核（切片 6b）：按账户+会计期间记录对账单余额、账面余额与差额。
-- 差额不为 0 时不能关账；差异调整必须先通过总账凭证完成。
CREATE TABLE IF NOT EXISTS bank_reconciliations (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id              INTEGER NOT NULL,
    bank_account_id        INTEGER NOT NULL,
    period_id              INTEGER NOT NULL,
    statement_balance_cents INTEGER NOT NULL DEFAULT 0,
    book_balance_cents     INTEGER NOT NULL DEFAULT 0,
    difference_cents       INTEGER NOT NULL DEFAULT 0,
    status                 TEXT NOT NULL DEFAULT 'open',  -- open/closed
    note                   TEXT NOT NULL DEFAULT '',
    created_by             INTEGER,
    created_at             TEXT NOT NULL DEFAULT '',
    closed_by              INTEGER,
    closed_at              TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bank_recon_tenant_account_period
    ON bank_reconciliations(tenant_id, bank_account_id, period_id);

-- 权限影子决策（切片 7a）：并排记录"权限点字典判定"与"代码实际是否放行"。
-- 只追加、不参与任何放行判定；mismatch=1 表示两者不一致，
-- 是从影子模式切到 Casbin 拦截之前必须先修掉的清单。
CREATE TABLE IF NOT EXISTS authz_shadow_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     INTEGER NOT NULL,
    user_id       INTEGER,
    role          TEXT NOT NULL DEFAULT '',
    subject       TEXT NOT NULL DEFAULT '',
    permission_id TEXT NOT NULL DEFAULT '',
    decision      TEXT NOT NULL DEFAULT 'deny',   -- allow/deny（Casbin 影子判定）
    allowed       INTEGER NOT NULL DEFAULT 0,     -- 代码实际是否放行
    mismatch      INTEGER NOT NULL DEFAULT 0,     -- 1 = 两者不一致
    reason        TEXT NOT NULL DEFAULT '',
    method        TEXT NOT NULL DEFAULT '',
    path          TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_authz_shadow_tenant_id
    ON authz_shadow_log(tenant_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_authz_shadow_mismatch
    ON authz_shadow_log(mismatch, id DESC);

-- 供应商（切片 8）：采购/应付的最小主数据。
"""

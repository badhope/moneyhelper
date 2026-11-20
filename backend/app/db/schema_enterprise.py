"""数据库表结构（DDL）·企业与总账段（多租户、凭证、科目、银行）。

从 schema_tables.py 拆出（原 509-809 行），内容逐字未改。
"""

from __future__ import annotations

SCHEMA_ENTERPRISE = """CREATE TABLE IF NOT EXISTS tenants (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'personal',  -- local/personal/enterprise
    owner_user_id INTEGER,
    status        TEXT NOT NULL DEFAULT 'active',
    created_at    TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS org_departments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id  INTEGER NOT NULL,
    name       TEXT NOT NULL,
    parent_id  INTEGER,
    code       TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_org_dept_tenant_name
    ON org_departments(tenant_id, name);
CREATE INDEX IF NOT EXISTS idx_org_dept_tenant_parent
    ON org_departments(tenant_id, parent_id);
CREATE TABLE IF NOT EXISTS org_positions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     INTEGER NOT NULL,
    department_id INTEGER,
    name          TEXT NOT NULL,
    code          TEXT NOT NULL DEFAULT '',
    role_hint     TEXT NOT NULL DEFAULT '',  -- accountant/approver/cashier/...（仅建议，不是权限）
    status        TEXT NOT NULL DEFAULT 'active',
    created_at    TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_org_pos_tenant_name
    ON org_positions(tenant_id, name);
CREATE INDEX IF NOT EXISTS idx_org_pos_tenant_dept
    ON org_positions(tenant_id, department_id);
CREATE TABLE IF NOT EXISTS org_memberships (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    role          TEXT NOT NULL DEFAULT 'member',  -- owner/admin/accountant/approver/viewer/member
    department_id INTEGER,
    position_id   INTEGER,
    status        TEXT NOT NULL DEFAULT 'active',
    created_at    TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_org_member_tenant_user
    ON org_memberships(tenant_id, user_id);
CREATE INDEX IF NOT EXISTS idx_org_member_tenant_status
    ON org_memberships(tenant_id, status);

-- 复式总账（切片 4）：金额一律用整数“分”，避免浮点累计误差。
-- 暂不声明外键：科目/期间/凭证都由应用层按 tenant_id 校验，便于后续
-- 与现有单式账本双写时逐步收敛。
CREATE TABLE IF NOT EXISTS gl_accounts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id  INTEGER NOT NULL,
    code       TEXT NOT NULL,
    name       TEXT NOT NULL,
    type       TEXT NOT NULL,              -- asset/liability/equity/income/expense
    parent_id  INTEGER,
    is_active  INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_gl_account_tenant_code
    ON gl_accounts(tenant_id, code);
CREATE TABLE IF NOT EXISTS gl_periods (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id  INTEGER NOT NULL,
    year       INTEGER NOT NULL,
    month      INTEGER NOT NULL,
    start_date TEXT NOT NULL,
    end_date   TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'open',  -- open/closed
    created_at TEXT NOT NULL DEFAULT '',
    closed_at  TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_gl_period_tenant_ym
    ON gl_periods(tenant_id, year, month);
CREATE TABLE IF NOT EXISTS gl_entries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id    INTEGER NOT NULL,
    entry_no     TEXT NOT NULL,
    entry_date   TEXT NOT NULL,
    period_id    INTEGER NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'draft',  -- draft/posted
    source       TEXT NOT NULL DEFAULT 'manual', -- manual/reversal
    reversal_of  INTEGER,                        -- 反冲时指向原凭证
    created_by   INTEGER,
    created_at   TEXT NOT NULL DEFAULT '',
    posted_at    TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_gl_entry_tenant_no
    ON gl_entries(tenant_id, entry_no);
CREATE INDEX IF NOT EXISTS idx_gl_entry_tenant_period
    ON gl_entries(tenant_id, period_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_gl_entry_reversal
    ON gl_entries(tenant_id, reversal_of) WHERE reversal_of IS NOT NULL;
CREATE TABLE IF NOT EXISTS gl_entry_lines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   INTEGER NOT NULL,
    entry_id    INTEGER NOT NULL,
    line_no     INTEGER NOT NULL,
    account_id  INTEGER NOT NULL,
    debit_cents INTEGER NOT NULL DEFAULT 0,
    credit_cents INTEGER NOT NULL DEFAULT 0,
    memo        TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_gl_line_tenant_entry_no
    ON gl_entry_lines(tenant_id, entry_id, line_no);
CREATE INDEX IF NOT EXISTS idx_gl_line_tenant_account
    ON gl_entry_lines(tenant_id, account_id);

-- 报销单（切片 5b）：审核通过后生成总账凭证草稿，过账仍走 /api/gl。
-- 金额存整数分；申请人/审批人分离，企业租户下禁止自审。
CREATE TABLE IF NOT EXISTS expense_claims (
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
CREATE TABLE IF NOT EXISTS vendors (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id  INTEGER NOT NULL,
    code       TEXT NOT NULL,
    name       TEXT NOT NULL,
    tax_no     TEXT NOT NULL DEFAULT '',
    contact    TEXT NOT NULL DEFAULT '',
    phone      TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_vendor_tenant_code
    ON vendors(tenant_id, code);

-- 采购单（切片 8）：审核只代表采购获批，不直接生成总账。
CREATE TABLE IF NOT EXISTS purchase_orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     INTEGER NOT NULL,
    po_no         TEXT NOT NULL,
    vendor_id     INTEGER NOT NULL,
    order_date    TEXT NOT NULL,
    expected_date TEXT NOT NULL DEFAULT '',
    amount_cents  INTEGER NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'draft',  -- draft/submitted/approved/cancelled
    approved_by   INTEGER,
    approved_at   TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT '',
    updated_at    TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_po_tenant_no
    ON purchase_orders(tenant_id, po_no);
CREATE INDEX IF NOT EXISTS idx_po_tenant_status
    ON purchase_orders(tenant_id, status, id DESC);

-- 应付单（切片 8）：审核通过生成「借费用/资产、贷应付」凭证草稿；
-- 付款时再生成「借应付、贷银行」凭证草稿，过账仍由会计确认。
CREATE TABLE IF NOT EXISTS payables (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id           INTEGER NOT NULL,
    payable_no          TEXT NOT NULL,
    vendor_id           INTEGER NOT NULL,
    po_id               INTEGER,
    invoice_no          TEXT NOT NULL DEFAULT '',
    invoice_date        TEXT NOT NULL,
    due_date            TEXT NOT NULL DEFAULT '',
    amount_cents        INTEGER NOT NULL,
    tax_cents           INTEGER NOT NULL DEFAULT 0,
    expense_account_id  INTEGER NOT NULL,
    payable_account_id  INTEGER NOT NULL,
    status              TEXT NOT NULL DEFAULT 'draft',  -- draft/submitted/approved/paid
    gl_entry_id         INTEGER,
    payment_id          INTEGER,
    approved_by         INTEGER,
    approved_at         TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT '',
    updated_at          TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_payable_tenant_no
    ON payables(tenant_id, payable_no);
CREATE INDEX IF NOT EXISTS idx_payable_tenant_status
    ON payables(tenant_id, status, id DESC);
"""

"""企业域建表 SQL · 组织与租户（tenants / 部门 / 岗位 / 成员）。

从 schema_enterprise.py 按表组拆出；各段按原顺序拼回同一份 DDL。
"""

from __future__ import annotations

SQL = """CREATE TABLE IF NOT EXISTS tenants (
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
"""

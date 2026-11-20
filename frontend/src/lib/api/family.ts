/** API 域：家庭、成员、借贷与企业组织（租户 / 部门 / 岗位 / 成员）、全局租户切换。
 *
 * 从 api.ts 拆出（原 549-807 行），api.ts 以 `export *` 汇总，调用方路径不变。
 */

import {
  api,
} from "./client";

// ---------------------------------------------------------------------------

export interface FamilyMember {
  id: number;
  username: string;
  display_name: string;
  role: "owner" | "admin" | "member" | "viewer";
  avatar_color: string;
  created_at: string;
}

export interface MemberLoan {
  id: number;
  from_member_id: number;
  to_member_id: number;
  amount: number;
  currency: string;
  note: string;
  settled: number;
  created_at: string;
  settled_at?: string | null;
  from_name?: string;
  to_name?: string;
}

export interface FamilySummary {
  household_income: number;
  household_expense: number;
  household_net: number;
  members: {
    id: number;
    display_name: string;
    role: string;
    avatar_color: string;
    income: number;
    expense: number;
    balance: number;
    pct: number;
    transaction_count: number;
  }[];
  outstanding_loans?: MemberLoan[];
  top_categories?: { category: string; amount: number }[];
}

export const listMembers = () =>
  api<{ members: FamilyMember[] }>("/api/members").then((r) => r.members);
export const addMember = (body: { display_name: string; role?: string; username?: string }) =>
  api<{ ok: boolean; member: FamilyMember }>("/api/members", {
    method: "POST",
    body: JSON.stringify(body),
  });
export const deleteMember = (id: number) =>
  api<{ ok: boolean; deleted: number }>(`/api/members/${id}`, { method: "DELETE" });
export const listMemberLoans = () =>
  api<{ loans: MemberLoan[] }>("/api/members/loans").then((r) => r.loans);
export const createMemberLoan = (body: {
  from_member_id: number;
  to_member_id: number;
  amount: number;
  note?: string;
}) =>
  api<{ ok: boolean; id: number }>("/api/members/loans", {
    method: "POST",
    body: JSON.stringify(body),
  });
export const settleMemberLoan = (id: number) =>
  api<{ ok: boolean }>(`/api/members/loans/${id}/settle`, { method: "POST" });
export const deleteMemberLoan = (id: number) =>
  api<{ ok: boolean }>(`/api/members/loans/${id}`, { method: "DELETE" });

// ---------------------------------------------------------------------------
// 企业组织（切片 1-3）：租户、部门、岗位、成员
// ---------------------------------------------------------------------------

export interface OrgTenant {
  id: number;
  name: string;
  kind: string; // local / personal / enterprise
  status: string;
  role?: string;
  /** 是否为当前正在工作的租户（切片 7b 全局切换） */
  active?: boolean;
}

export interface OrgDepartment {
  id: number;
  tenant_id: number;
  name: string;
  parent_id: number | null;
  code: string;
  status: string;
  created_at: string;
}

export interface OrgPosition {
  id: number;
  tenant_id: number;
  department_id: number | null;
  name: string;
  code: string;
  role_hint: string;
  status: string;
  created_at: string;
}

export interface OrgMember {
  id: number;
  tenant_id: number;
  user_id: number;
  role: string;
  department_id: number | null;
  position_id: number | null;
  status: string;
  created_at: string;
  username?: string;
  display_name?: string;
  disabled?: number;
}

export interface OrgOverview {
  tenant: OrgTenant | null;
  departments: OrgDepartment[];
  positions: OrgPosition[];
  members: OrgMember[];
  counts: {
    departments: number;
    positions: number;
    members: number;
    active_members: number;
  };
}

export const orgQuery = (tenantId?: number) =>
  tenantId == null ? "" : `?tenant_id=${encodeURIComponent(String(tenantId))}`;

export const listOrgTenants = () =>
  api<{ tenants: OrgTenant[] }>("/api/org/tenants").then((r) => r.tenants);

// ---------------------------------------------------------------------------
// 全局租户切换（切片 7b）
// ---------------------------------------------------------------------------

export interface ActiveTenantInfo {
  active_tenant_id: number;
  /** 是否为用户显式选择（false = 走默认映射） */
  explicit?: boolean;
  tenant: OrgTenant | null;
  scope_note?: string;
}

export const getActiveTenant = () => api<ActiveTenantInfo>("/api/org/active-tenant");

/** 当前用户在当前工作租户里拥有的权限点（切片 7a：前端按它隐藏写操作入口）。 */
export interface MyCapabilities {
  tenant_id: number;
  role: string;
  permissions: string[];
}

export const getMyCapabilities = () => api<MyCapabilities>("/api/org/capabilities");

export const switchActiveTenant = (tenantId: number) =>
  api<{
    ok: boolean;
    active_tenant_id: number;
    tenant: OrgTenant | null;
    tenants: OrgTenant[];
  }>("/api/org/active-tenant", {
    method: "POST",
    body: JSON.stringify({ tenant_id: tenantId }),
  });

export const getOrgOverview = (tenantId?: number) =>
  api<OrgOverview>(`/api/org/overview${orgQuery(tenantId)}`);

export const createOrgDepartment = (
  body: { name: string; code?: string; parent_id?: number | null },
  tenantId?: number,
) =>
  api<{ ok: boolean; department: OrgDepartment }>(
    `/api/org/departments${orgQuery(tenantId)}`,
    { method: "POST", body: JSON.stringify(body) },
  );

export const updateOrgDepartment = (
  id: number,
  body: Record<string, unknown>,
  tenantId?: number,
) =>
  api<{ ok: boolean; department: OrgDepartment }>(
    `/api/org/departments/${id}${orgQuery(tenantId)}`,
    { method: "PATCH", body: JSON.stringify(body) },
  );

export const deleteOrgDepartment = (id: number, tenantId?: number) =>
  api<{ ok: boolean }>(`/api/org/departments/${id}${orgQuery(tenantId)}`, {
    method: "DELETE",
  });

export const createOrgPosition = (
  body: {
    name: string;
    code?: string;
    department_id?: number | null;
    role_hint?: string;
  },
  tenantId?: number,
) =>
  api<{ ok: boolean; position: OrgPosition }>(
    `/api/org/positions${orgQuery(tenantId)}`,
    { method: "POST", body: JSON.stringify(body) },
  );

export const updateOrgPosition = (
  id: number,
  body: Record<string, unknown>,
  tenantId?: number,
) =>
  api<{ ok: boolean; position: OrgPosition }>(
    `/api/org/positions/${id}${orgQuery(tenantId)}`,
    { method: "PATCH", body: JSON.stringify(body) },
  );

export const deleteOrgPosition = (id: number, tenantId?: number) =>
  api<{ ok: boolean }>(`/api/org/positions/${id}${orgQuery(tenantId)}`, {
    method: "DELETE",
  });

export const addOrgMember = (
  body: {
    user_id: number;
    role?: string;
    department_id?: number | null;
    position_id?: number | null;
  },
  tenantId?: number,
) =>
  api<{ ok: boolean; member: OrgMember }>(`/api/org/members${orgQuery(tenantId)}`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateOrgMember = (
  userId: number,
  body: Record<string, unknown>,
  tenantId?: number,
) =>
  api<{ ok: boolean; member: OrgMember }>(
    `/api/org/members/${userId}${orgQuery(tenantId)}`,
    { method: "PATCH", body: JSON.stringify(body) },
  );

export const removeOrgMember = (userId: number, tenantId?: number) =>
  api<{ ok: boolean }>(`/api/org/members/${userId}${orgQuery(tenantId)}`, {
    method: "DELETE",
  });

// ---------------------------------------------------------------------------

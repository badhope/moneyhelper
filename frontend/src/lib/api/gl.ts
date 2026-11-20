/** API 域：复式总账与报销单。
 *
 * 从 api.ts 拆出（原 808-1041 行），api.ts 以 `export *` 汇总，调用方路径不变。
 */

import {
  api,
} from "./client";
import { orgQuery } from "./family";

// ---------------------------------------------------------------------------

export interface GlAccount {
  id: number;
  tenant_id: number;
  code: string;
  name: string;
  type: string;
  parent_id: number | null;
  is_active: boolean;
  normal_balance: string;
  created_at: string;
}

export interface GlPeriod {
  id: number;
  tenant_id: number;
  year: number;
  month: number;
  start_date: string;
  end_date: string;
  status: string;
  created_at: string;
  closed_at: string;
  posted_entries?: number;
  draft_entries?: number;
}

export interface GlEntryLine {
  id: number;
  tenant_id: number;
  entry_id: number;
  line_no: number;
  account_id: number;
  debit_cents: number;
  credit_cents: number;
  debit: number;
  credit: number;
  memo: string;
}

export interface GlEntry {
  id: number;
  tenant_id: number;
  entry_no: string;
  entry_date: string;
  period_id: number;
  description: string;
  status: string;
  source: string;
  reversal_of: number | null;
  created_by: number | null;
  created_at: string;
  posted_at: string;
  debit?: number;
  credit?: number;
  debit_cents?: number;
  credit_cents?: number;
  lines?: GlEntryLine[];
}

export interface GlTrialItem {
  account_id: number;
  code: string;
  name: string;
  type: string;
  normal_balance: string;
  debit: number;
  credit: number;
  balance: number;
  debit_cents: number;
  credit_cents: number;
}

export interface GlTrialBalance {
  period: GlPeriod;
  items: GlTrialItem[];
  total_debit: number;
  total_credit: number;
  total_debit_cents: number;
  total_credit_cents: number;
  balanced: boolean;
}

export const listGlAccounts = () =>
  api<{ accounts: GlAccount[] }>("/api/gl/accounts").then((r) => r.accounts);

export const createGlAccount = (body: {
  code: string;
  name: string;
  type: string;
  parent_id?: number | null;
}) =>
  api<{ ok: boolean; account: GlAccount }>("/api/gl/accounts", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const listGlPeriods = () =>
  api<{ periods: GlPeriod[] }>("/api/gl/periods").then((r) => r.periods);

export const createGlPeriod = (body: { year: number; month: number }) =>
  api<{ ok: boolean; period: GlPeriod }>("/api/gl/periods", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const closeGlPeriod = (id: number) =>
  api<{ ok: boolean; period: GlPeriod }>(`/api/gl/periods/${id}/close`, {
    method: "POST",
  });

export const listGlEntries = (periodId?: number, limit = 200) =>
  api<{ entries: GlEntry[] }>(
    `/api/gl/entries?limit=${limit}${periodId ? `&period_id=${periodId}` : ""}`,
  ).then((r) => r.entries);

export const createGlEntry = (body: {
  entry_date: string;
  description: string;
  lines: { account_id: number; debit: number; credit: number; memo?: string }[];
}) =>
  api<{ ok: boolean; entry: GlEntry }>("/api/gl/entries", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const postGlEntry = (id: number) =>
  api<{ ok: boolean; entry: GlEntry }>(`/api/gl/entries/${id}/post`, {
    method: "POST",
  });

export const deleteGlEntry = (id: number) =>
  api<{ ok: boolean }>(`/api/gl/entries/${id}`, { method: "DELETE" });

export const reverseGlEntry = (id: number, body: { entry_date?: string; description?: string } = {}) =>
  api<{ ok: boolean; entry: GlEntry }>(`/api/gl/entries/${id}/reverse`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getGlTrialBalance = (periodId: number) =>
  api<GlTrialBalance>(`/api/gl/trial-balance?period_id=${periodId}`);

// ---------------------------------------------------------------------------
// 报销单（切片 5b）
// ---------------------------------------------------------------------------

export interface ExpenseClaim {
  id: number;
  tenant_id: number;
  claim_no: string;
  title: string;
  applicant_user_id: number;
  applicant_name?: string;
  department_id: number | null;
  amount: number;
  amount_cents: number;
  category: string;
  expense_account_id: number;
  expense_account_code?: string;
  expense_account_name?: string;
  credit_account_id: number;
  credit_account_code?: string;
  credit_account_name?: string;
  invoice_ref: string;
  attachment_name: string;
  status: string; // draft / submitted / approving / approved / rejected
  approved_by: number | null;
  approver_name?: string;
  approved_at: string;
  rejected_reason: string;
  gl_entry_id: number | null;
  gl_entry_no?: string;
  gl_status?: string;
  created_at: string;
  updated_at: string;
}

export const listExpenseClaims = (tenantId?: number, status?: string) => {
  const q = new URLSearchParams();
  if (tenantId != null) q.set("tenant_id", String(tenantId));
  if (status) q.set("status", status);
  const suffix = q.toString() ? `?${q.toString()}` : "";
  return api<{ claims: ExpenseClaim[] }>(`/api/expenses${suffix}`).then(
    (r) => r.claims,
  );
};

export const createExpenseClaim = (
  body: {
    title: string;
    amount: number;
    category?: string;
    expense_account_id: number;
    credit_account_id: number;
    invoice_ref?: string;
    attachment_name?: string;
  },
  tenantId?: number,
) =>
  api<{ ok: boolean; claim: ExpenseClaim }>(
    `/api/expenses${orgQuery(tenantId)}`,
    { method: "POST", body: JSON.stringify(body) },
  );

export const submitExpenseClaim = (id: number, tenantId?: number) =>
  api<{ ok: boolean; claim: ExpenseClaim }>(
    `/api/expenses/${id}/submit${orgQuery(tenantId)}`,
    { method: "POST" },
  );

export const approveExpenseClaim = (
  id: number,
  body: { entry_date?: string } = {},
  tenantId?: number,
) =>
  api<{ ok: boolean; claim: ExpenseClaim }>(
    `/api/expenses/${id}/approve${orgQuery(tenantId)}`,
    { method: "POST", body: JSON.stringify(body) },
  );

export const rejectExpenseClaim = (
  id: number,
  reason: string,
  tenantId?: number,
) =>
  api<{ ok: boolean; claim: ExpenseClaim }>(
    `/api/expenses/${id}/reject${orgQuery(tenantId)}`,
    { method: "POST", body: JSON.stringify({ reason }) },
  );

// ---------------------------------------------------------------------------

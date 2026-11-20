/** API 域：付款与银行流水。
 *
 * 从 api.ts 拆出（原 1042-1229 行），api.ts 以 `export *` 汇总，调用方路径不变。
 */

import {
  api,
  SLOW_REQUEST_TIMEOUT_MS,
} from "./client";
import { orgQuery } from "./family";

// ---------------------------------------------------------------------------

export interface Payment {
  id: number;
  tenant_id: number;
  payment_no: string;
  claim_id: number;
  claim_no?: string;
  claim_title?: string;
  payable_id?: number | null;
  payable_no?: string;
  invoice_no?: string;
  gl_entry_id?: number | null;
  gl_entry_no?: string;
  gl_status?: string;
  amount_cents: number;
  amount: number;
  payee: string;
  bank_account_id: number;
  bank_account_code?: string;
  bank_account_name?: string;
  method: string;
  status: string;
  paid_at: string;
  note: string;
}

export interface BankTransaction {
  id: number;
  tenant_id: number;
  bank_account_id: number;
  bank_account_code?: string;
  bank_account_name?: string;
  txn_date: string;
  direction: "in" | "out";
  amount_cents: number;
  amount: number;
  counterparty: string;
  memo: string;
  bank_ref: string;
  status: string; // unmatched / matched / ignored
  payment_id: number | null;
  payment_no?: string;
  matched_at: string;
}

export interface BankSummary {
  payments_count: number;
  payments_total: number;
  payments_total_cents: number;
  bank_in_total: number;
  bank_out_total: number;
  unmatched_count: number;
  unmatched_out_total: number;
  matched_count: number;
  balanced: boolean;
}

export const listPayments = (tenantId?: number) =>
  api<{ payments: Payment[] }>(`/api/payments${orgQuery(tenantId)}`).then(
    (r) => r.payments,
  );

export const createPayment = (
  body: { claim_id: number; bank_account_id: number; note?: string },
  tenantId?: number,
) =>
  api<{ ok: boolean; payment: Payment }>(`/api/payments${orgQuery(tenantId)}`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const listBankTransactions = (
  tenantId?: number,
  status?: string,
  bankAccountId?: number,
) => {
  const q = new URLSearchParams();
  if (tenantId != null) q.set("tenant_id", String(tenantId));
  if (status) q.set("status", status);
  if (bankAccountId != null) q.set("bank_account_id", String(bankAccountId));
  const suffix = q.toString() ? `?${q.toString()}` : "";
  return api<{ transactions: BankTransaction[] }>(
    `/api/bank/transactions${suffix}`,
  ).then((r) => r.transactions);
};

export const createBankTransaction = (
  body: {
    bank_account_id: number;
    txn_date: string;
    direction: string;
    amount: number;
    counterparty?: string;
    memo?: string;
    bank_ref?: string;
  },
  tenantId?: number,
) =>
  api<{ ok: boolean; transaction: BankTransaction }>(
    `/api/bank/transactions${orgQuery(tenantId)}`,
    { method: "POST", body: JSON.stringify(body) },
  );

export const importBankCsv = (
  body: { bank_account_id: number; csv: string },
  tenantId?: number,
) =>
  api<{ ok: boolean; imported: number }>(
    `/api/bank/import${orgQuery(tenantId)}`,
    { method: "POST", body: JSON.stringify(body) },
    // 导入时自动生成凭证要逐行写库，几千行远超 20s
    { timeoutMs: SLOW_REQUEST_TIMEOUT_MS },
  );

export const matchBankTransaction = (
  id: number,
  paymentId: number,
  tenantId?: number,
) =>
  api<{ ok: boolean; transaction: BankTransaction }>(
    `/api/bank/transactions/${id}/match${orgQuery(tenantId)}`,
    { method: "POST", body: JSON.stringify({ payment_id: paymentId }) },
  );

export const unmatchBankTransaction = (id: number, tenantId?: number) =>
  api<{ ok: boolean; transaction: BankTransaction }>(
    `/api/bank/transactions/${id}/unmatch${orgQuery(tenantId)}`,
    { method: "POST" },
  );

export const getBankSummary = (tenantId?: number, bankAccountId?: number) => {
  const q = new URLSearchParams();
  if (tenantId != null) q.set("tenant_id", String(tenantId));
  if (bankAccountId != null) q.set("bank_account_id", String(bankAccountId));
  const suffix = q.toString() ? `?${q.toString()}` : "";
  return api<BankSummary>(`/api/bank/summary${suffix}`);
};

export interface BankReconciliation {
  id: number;
  tenant_id: number;
  bank_account_id: number;
  bank_account_code?: string;
  bank_account_name?: string;
  period_id: number;
  year?: number;
  month?: number;
  start_date?: string;
  end_date?: string;
  statement_balance: number;
  book_balance: number;
  difference: number;
  status: string;
  note: string;
  created_by: number;
  created_at: string;
  closed_by: number | null;
  closed_at: string;
}

export const listBankReconciliations = (tenantId?: number) =>
  api<{ reconciliations: BankReconciliation[] }>(
    `/api/bank/reconciliations${orgQuery(tenantId)}`,
  ).then((r) => r.reconciliations);

export const createBankReconciliation = (
  body: {
    bank_account_id: number;
    period_id: number;
    statement_balance: number;
    note?: string;
  },
  tenantId?: number,
) =>
  api<{ ok: boolean; reconciliation: BankReconciliation }>(
    `/api/bank/reconciliations${orgQuery(tenantId)}`,
    { method: "POST", body: JSON.stringify(body) },
  );

export const closeBankReconciliation = (id: number, tenantId?: number) =>
  api<{ ok: boolean; reconciliation: BankReconciliation }>(
    `/api/bank/reconciliations/${id}/close${orgQuery(tenantId)}`,
    { method: "POST" },
  );

// ---------------------------------------------------------------------------

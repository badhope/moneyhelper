/** API 域：采购与应付。
 *
 * 从 api.ts 拆出（原 1230-1387 行），api.ts 以 `export *` 汇总，调用方路径不变。
 */

import {
  api,
} from "./client";
import { orgQuery } from "./family";

// ---------------------------------------------------------------------------

export interface Vendor {
  id: number;
  tenant_id: number;
  code: string;
  name: string;
  tax_no: string;
  contact: string;
  phone: string;
  status: string;
  created_at: string;
}

export interface PurchaseOrder {
  id: number;
  tenant_id: number;
  po_no: string;
  vendor_id: number;
  vendor_code?: string;
  vendor_name?: string;
  order_date: string;
  expected_date: string;
  amount_cents: number;
  amount: number;
  description: string;
  status: string; // draft / submitted / approved / cancelled
  approved_by: number | null;
  approved_at: string;
  created_at: string;
  updated_at: string;
}

export interface Payable {
  id: number;
  tenant_id: number;
  payable_no: string;
  vendor_id: number;
  vendor_code?: string;
  vendor_name?: string;
  po_id: number | null;
  po_no?: string;
  invoice_no: string;
  invoice_date: string;
  due_date: string;
  amount_cents: number;
  amount: number;
  tax_cents: number;
  tax: number;
  expense_account_id: number;
  payable_account_id: number;
  status: string; // draft / submitted / approving / approved / paid
  gl_entry_id: number | null;
  gl_entry_no?: string;
  gl_status?: string;
  payment_id: number | null;
  payment_no?: string;
  approved_by: number | null;
  approved_at: string;
  created_at: string;
  updated_at: string;
}

export const listVendors = (tenantId?: number) =>
  api<{ vendors: Vendor[] }>(`/api/procurement/vendors${orgQuery(tenantId)}`).then(
    (r) => r.vendors,
  );

export const createVendor = (
  body: { code: string; name: string; tax_no?: string; contact?: string; phone?: string },
  tenantId?: number,
) =>
  api<{ ok: boolean; vendor: Vendor }>(
    `/api/procurement/vendors${orgQuery(tenantId)}`,
    { method: "POST", body: JSON.stringify(body) },
  );

export const listPurchaseOrders = (tenantId?: number) =>
  api<{ orders: PurchaseOrder[] }>(
    `/api/procurement/orders${orgQuery(tenantId)}`,
  ).then((r) => r.orders);

export const createPurchaseOrder = (
  body: {
    vendor_id: number;
    order_date: string;
    expected_date?: string;
    amount: number;
    description?: string;
  },
  tenantId?: number,
) =>
  api<{ ok: boolean; order: PurchaseOrder }>(
    `/api/procurement/orders${orgQuery(tenantId)}`,
    { method: "POST", body: JSON.stringify(body) },
  );

export const submitPurchaseOrder = (id: number, tenantId?: number) =>
  api<{ ok: boolean; order: PurchaseOrder }>(
    `/api/procurement/orders/${id}/submit${orgQuery(tenantId)}`,
    { method: "POST" },
  );

export const approvePurchaseOrder = (id: number, tenantId?: number) =>
  api<{ ok: boolean; order: PurchaseOrder }>(
    `/api/procurement/orders/${id}/approve${orgQuery(tenantId)}`,
    { method: "POST" },
  );

export const listPayables = (tenantId?: number) =>
  api<{ payables: Payable[] }>(
    `/api/procurement/payables${orgQuery(tenantId)}`,
  ).then((r) => r.payables);

export const createPayable = (
  body: {
    vendor_id: number;
    po_id?: number | null;
    invoice_no?: string;
    invoice_date: string;
    due_date?: string;
    amount: number;
    tax?: number;
    expense_account_id: number;
    payable_account_id: number;
  },
  tenantId?: number,
) =>
  api<{ ok: boolean; payable: Payable }>(
    `/api/procurement/payables${orgQuery(tenantId)}`,
    { method: "POST", body: JSON.stringify(body) },
  );

export const submitPayable = (id: number, tenantId?: number) =>
  api<{ ok: boolean; payable: Payable }>(
    `/api/procurement/payables/${id}/submit${orgQuery(tenantId)}`,
    { method: "POST" },
  );

export const approvePayable = (id: number, tenantId?: number) =>
  api<{ ok: boolean; payable: Payable }>(
    `/api/procurement/payables/${id}/approve${orgQuery(tenantId)}`,
    { method: "POST" },
  );

export const payPayable = (
  id: number,
  body: { bank_account_id: number; note?: string },
  tenantId?: number,
) =>
  api<{ ok: boolean; payable: Payable }>(
    `/api/procurement/payables/${id}/pay${orgQuery(tenantId)}`,
    { method: "POST", body: JSON.stringify(body) },
  );

// ---------------------------------------------------------------------------
// 长任务（切片 10）：分段执行 + 产物落盘

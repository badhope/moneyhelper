/** 外部协同前置包 hooks（4.20.0）。 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export interface ExternalCheck {
  id: string;
  status: "ok" | "review" | "manual" | "error" | "blocked";
  detail: string;
}

export interface TaxPacket {
  packet_id: string;
  kind: "tax_filing_worksheet";
  period: string;
  generated_at: string;
  status: "ready" | "review" | "blocked" | "missing";
  submission_status: "not_submitted";
  period_status: string;
  closed_at: string;
  posted_entries: number;
  draft_entries: number;
  summary: {
    income: number;
    expense: number;
    profit: number;
    cash_in: number;
    cash_out: number;
    cash_net: number;
    tax_accrued: number;
    tax_paid: number;
    tax_net: number;
    debit: number;
    credit: number;
  };
  account_summary: {
    account_code: string;
    account_name: string;
    debit: number;
    credit: number;
    balance: number;
  }[];
  checks: ExternalCheck[];
  boundary: string;
}

export interface PaymentInstruction {
  seq: number;
  expected_date: string;
  account_code: string;
  counterparty: string;
  amount: number;
  amount_cents: number;
  certainty: string;
  note: string;
  review: string;
}

export interface PaymentPacket {
  packet_id: string;
  kind: "payment_instruction";
  period: string;
  generated_at: string;
  status: "ready" | "review" | "blocked" | "missing";
  execution_status: "draft_only";
  can_execute: false;
  total: number;
  total_cents: number;
  count: number;
  opening: number;
  target_min: number;
  instructions: PaymentInstruction[];
  checks: ExternalCheck[];
  boundary: string;
}

export interface ConsolidationEntity {
  tenant_id: number;
  name: string;
  ownership_pct: number;
  method: string;
  status: string;
  included: boolean;
}

export interface ConsolidationPacket {
  packet_id: string;
  kind: "consolidation_audit_pack";
  period: string;
  generated_at: string;
  status: "ready" | "review" | "blocked" | "missing";
  audit_status: "not_audited";
  basis: "management";
  group: { id: string; name: string; [key: string]: unknown };
  entities: ConsolidationEntity[];
  summary: {
    reported?: Record<string, number>;
    included?: Record<string, number>;
    consolidated?: Record<string, number>;
    eliminations?: Record<string, number>;
  };
  totals: { debit_cents: number; credit_cents: number };
  balanced: boolean;
  warnings: string[];
  source_hash: string;
  checks: ExternalCheck[];
  boundary: string;
}

export function useTaxPacket(period: string) {
  return useQuery({
    queryKey: ["external", "tax", period],
    queryFn: () => api<TaxPacket>(`/api/external/tax-packet?period=${encodeURIComponent(period)}`),
    enabled: Boolean(period),
  });
}

export function usePaymentPacket(period: string) {
  return useQuery({
    queryKey: ["external", "payment", period],
    queryFn: () => api<PaymentPacket>(`/api/external/payment-packet?period=${encodeURIComponent(period)}`),
    enabled: Boolean(period),
  });
}

export function useConsolidationPacket(groupId: string | null, period: string) {
  return useQuery({
    queryKey: ["external", "consolidation", groupId, period],
    queryFn: () =>
      api<ConsolidationPacket>(
        `/api/external/consolidation-packet?group_id=${encodeURIComponent(groupId ?? "")}&period=${encodeURIComponent(period)}`,
      ),
    enabled: Boolean(groupId && period),
  });
}

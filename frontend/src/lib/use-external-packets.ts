/** 外部协同前置包 hooks（4.20.0）。 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
  source_hash: string;
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
  source_hash: string;
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


export interface HandoffRecord {
  packet_id: string;
  kind: "tax" | "payment" | "consolidation";
  period: string;
  group_id: string;
  source_hash: string;
  packet_status: string;
  note: string;
  archived_at: string;
  archived_by: string;
  handed_at: string;
  handed_note: string;
  state: "archived" | "handed_over";
  last_activity?: string;
}

export interface HandoffLedger {
  records: HandoffRecord[];
  total: number;
  archived_count: number;
  handed_count: number;
  boundary: string;
}

export function useHandoffLedger(limit = 20) {
  return useQuery({
    queryKey: ["external", "handoffs", limit],
    queryFn: () => api<HandoffLedger>(`/api/external/handoffs?limit=${limit}`),
  });
}

export function useArchiveHandoff() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { kind: HandoffRecord["kind"]; period: string; group_id?: string; note?: string }) =>
      api<{ record: HandoffRecord; created: boolean }>("/api/external/handoffs", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["external", "handoffs"] }),
  });
}

export function useAckHandoff() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { packet_id: string; note?: string }) =>
      api<{ record: HandoffRecord; updated: boolean }>("/api/external/handoffs/ack", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["external", "handoffs"] }),
  });
}

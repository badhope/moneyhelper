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
  delivery_count?: number;
  delivery_status?: "pending" | "accepted" | "failed" | "";
  delivery_channel?: string;
  delivery_at?: string;
}

export interface HandoffLedger {
  records: HandoffRecord[];
  total: number;
  archived_count: number;
  handed_count: number;
  delivered_count?: number;
  boundary: string;
}

export interface ExternalChannel {
  id?: string;
  channel_id?: string;
  label: string;
  transport: "smtp" | "https";
  kinds: HandoffRecord["kind"][];
  secret_fields: string[];
  config_fields: string[];
  config: Record<string, unknown>;
  enabled: boolean;
  configured: boolean;
  ready: boolean;
  missing: string[];
  last_test_at: string;
  last_test_ok: boolean | null;
  last_test_detail: string;
  updated_at?: string;
}

export interface ExternalDelivery {
  id: number;
  channel_id: string;
  kind: HandoffRecord["kind"];
  packet_id: string;
  source_hash: string;
  status: "pending" | "accepted" | "failed";
  recipient: string;
  request_summary: Record<string, unknown>;
  receipt: Record<string, unknown>;
  error: string;
  created_at: string;
  updated_at: string;
}

export interface ExternalChannelsResult {
  channels: ExternalChannel[];
  deliveries: ExternalDelivery[];
  stats: { accepted: number; failed: number; pending: number };
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

export function useExternalChannels() {
  return useQuery({
    queryKey: ["external", "channels"],
    queryFn: () => api<ExternalChannelsResult>("/api/external/channels"),
  });
}

export function useSaveExternalChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { channel_id: string; label?: string; config: Record<string, unknown>; secret?: Record<string, string>; enabled: boolean }) =>
      api<{ channel: ExternalChannel }>(`/api/external/channels/${encodeURIComponent(input.channel_id)}`, {
        method: "PUT",
        body: JSON.stringify({
          label: input.label,
          config: input.config,
          secret: input.secret && Object.keys(input.secret).length > 0 ? input.secret : undefined,
          enabled: input.enabled,
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["external", "channels"] });
      queryClient.invalidateQueries({ queryKey: ["external", "handoffs"] });
    },
  });
}

export function useTestExternalChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { channel_id: string }) =>
      api<{ ok: boolean; detail: string; receipt: Record<string, unknown> }>(
        `/api/external/channels/${encodeURIComponent(input.channel_id)}/test`,
        { method: "POST", body: JSON.stringify({}) },
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["external", "channels"] }),
  });
}

export function useDeleteExternalChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (channelId: string) =>
      api<{ deleted: boolean }>(`/api/external/channels/${encodeURIComponent(channelId)}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["external", "channels"] }),
  });
}

export function useDeliverPacket() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { channel_id: string; kind: HandoffRecord["kind"]; period: string; group_id?: string; note?: string }) =>
      api<{ duplicate: boolean; delivery: ExternalDelivery }>("/api/external/deliver", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["external", "channels"] });
      queryClient.invalidateQueries({ queryKey: ["external", "handoffs"] });
    },
  });
}

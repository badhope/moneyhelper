/** 多主体管理合并 hooks（4.18.0）。 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { StatementAnalysis } from "@/lib/use-research";

export interface ConsolidationGroup {
  id: string;
  name: string;
  owner_user_id: number;
  status: string;
  entity_count: number;
  created_at: string;
  updated_at?: string;
}

export interface ConsolidationEntity {
  tenant_id: number;
  tenant_name: string;
  tenant_kind?: string;
  tenant_status?: string;
  ownership_pct: number;
  method: "full" | "proportional";
  factor?: number;
  status?: "ok" | "missing" | "no_posted" | "no_access";
  period_id?: number | null;
  period_status?: string;
  posted_entries?: number;
  draft_entries?: number;
  warning?: string;
  statement?: StatementSummary | null;
  included?: StatementSummary | null;
  balanced?: boolean;
  trial_balance?: { debit_cents: number; credit_cents: number };
}

export interface StatementSummary {
  total_assets: number;
  total_liabilities: number;
  total_equity: number;
  revenue: number;
  net_profit: number;
}

export interface ConsolidationPeriod {
  period: string;
  year: number;
  month: number;
  entities: number;
}

export interface ConsolidationAccount {
  code: string;
  name: string;
  type: string;
}

export interface AdjustmentLine {
  id?: string;
  account_code: string;
  account_name: string;
  account_type: string;
  debit_cents: number;
  credit_cents: number;
  memo?: string;
}

export interface AdjustmentVoucher {
  voucher_id: string;
  period: string;
  description: string;
  created_at: string;
  debit_cents: number;
  credit_cents: number;
  lines: AdjustmentLine[];
}

export interface ConsolidationDetail {
  group: ConsolidationGroup;
  entities: ConsolidationEntity[];
  periods: ConsolidationPeriod[];
  accounts: ConsolidationAccount[];
  account_conflicts: ConsolidationAccount[];
  candidates: {
    id: number;
    name: string;
    kind: string;
    status: string;
    role: string;
  }[];
  boundary: string;
}

export interface ConsolidationReport {
  group: ConsolidationGroup;
  period: string;
  periods: ConsolidationPeriod[];
  entities: ConsolidationEntity[];
  adjustments: AdjustmentVoucher[];
  accounts: ConsolidationAccount[];
  items: {
    account_id: number;
    code: string;
    name: string;
    type: string;
    debit_cents: number;
    credit_cents: number;
    balance: number;
  }[];
  payload: Record<string, unknown>;
  analysis: StatementAnalysis;
  summary: {
    reported: StatementSummary;
    included: StatementSummary;
    consolidated: StatementSummary;
    eliminations: { debit_cents: number; credit_cents: number; vouchers: number };
  };
  balanced: boolean;
  totals: { debit_cents: number; credit_cents: number };
  warnings: string[];
  boundary: string;
  scope_note: string;
}

export function useConsolidationGroups() {
  return useQuery({
    queryKey: ["consolidation", "groups"],
    queryFn: () => api<{ groups: ConsolidationGroup[]; count: number; boundary: string }>(
      "/api/consolidation/groups",
    ),
  });
}

export function useConsolidationDetail(groupId: string | null) {
  return useQuery({
    queryKey: ["consolidation", "detail", groupId],
    queryFn: () => api<ConsolidationDetail>(`/api/consolidation/groups/${groupId}`),
    enabled: Boolean(groupId),
  });
}

export function useConsolidationReport(groupId: string | null, period: string | null) {
  return useQuery({
    queryKey: ["consolidation", "report", groupId, period],
    queryFn: () =>
      api<ConsolidationReport>(
        `/api/consolidation/groups/${groupId}/report?period=${encodeURIComponent(period ?? "")}`,
      ),
    enabled: Boolean(groupId && period),
    retry: 0,
  });
}

export function useConsolidationAdjustments(groupId: string | null, period: string | null) {
  return useQuery({
    queryKey: ["consolidation", "adjustments", groupId, period],
    queryFn: () =>
      api<{ adjustments: AdjustmentVoucher[]; count: number; boundary: string }>(
        `/api/consolidation/groups/${groupId}/adjustments?period=${encodeURIComponent(period ?? "")}`,
      ),
    enabled: Boolean(groupId && period),
  });
}

function invalidate(qc: ReturnType<typeof useQueryClient>) {
  return qc.invalidateQueries({ queryKey: ["consolidation"] });
}

export function useCreateConsolidationGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      api<{ ok: boolean; group: ConsolidationGroup }>("/api/consolidation/groups", {
        method: "POST",
        body: JSON.stringify({ name }),
      }),
    onSuccess: () => invalidate(qc),
    retry: 0,
  });
}

export function useDeleteConsolidationGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (groupId: string) =>
      api<{ ok: boolean }>(`/api/consolidation/groups/${groupId}`, { method: "DELETE" }),
    onSuccess: () => invalidate(qc),
    retry: 0,
  });
}

export function useAddConsolidationEntity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: {
      groupId: string;
      tenantId: number;
      ownershipPct: number;
      method: "full" | "proportional";
    }) =>
      api<{ ok: boolean; entity: ConsolidationEntity }>(
        `/api/consolidation/groups/${args.groupId}/entities`,
        {
          method: "POST",
          body: JSON.stringify({
            tenant_id: args.tenantId,
            ownership_pct: args.ownershipPct,
            method: args.method,
          }),
        },
      ),
    onSuccess: () => invalidate(qc),
    retry: 0,
  });
}

export function useCreateConsolidationEntity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: {
      groupId: string;
      name: string;
      ownershipPct: number;
      method: "full" | "proportional";
    }) =>
      api<{ ok: boolean; entity: ConsolidationEntity }>(
        `/api/consolidation/groups/${args.groupId}/entities/new`,
        {
          method: "POST",
          body: JSON.stringify({
            name: args.name,
            ownership_pct: args.ownershipPct,
            method: args.method,
          }),
        },
      ),
    onSuccess: () => invalidate(qc),
    retry: 0,
  });
}

export function useRemoveConsolidationEntity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { groupId: string; tenantId: number }) =>
      api<{ ok: boolean }>(
        `/api/consolidation/groups/${args.groupId}/entities/${args.tenantId}`,
        { method: "DELETE" },
      ),
    onSuccess: () => invalidate(qc),
    retry: 0,
  });
}

export function useCreateConsolidationAdjustment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: {
      groupId: string;
      period: string;
      description: string;
      debitCode: string;
      creditCode: string;
      amount: number;
    }) =>
      api<{ ok: boolean; adjustment: AdjustmentVoucher }>(
        `/api/consolidation/groups/${args.groupId}/adjustments`,
        {
          method: "POST",
          body: JSON.stringify({
            period: args.period,
            description: args.description,
            lines: [
              { account_code: args.debitCode, debit_cents: Math.round(args.amount * 100), credit_cents: 0 },
              { account_code: args.creditCode, debit_cents: 0, credit_cents: Math.round(args.amount * 100) },
            ],
          }),
        },
      ),
    onSuccess: () => invalidate(qc),
    retry: 0,
  });
}

export function useDeleteConsolidationAdjustment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { groupId: string; voucherId: string }) =>
      api<{ ok: boolean }>(
        `/api/consolidation/groups/${args.groupId}/adjustments/${args.voucherId}`,
        { method: "DELETE" },
      ),
    onSuccess: () => invalidate(qc),
    retry: 0,
  });
}

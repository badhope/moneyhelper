/** 企业预算与资金计划 hooks（4.19.0）。 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export interface PlanAccount {
  code: string;
  name: string;
  type?: string;
}

export interface BudgetLine {
  account_code: string;
  account_name?: string;
  account_type?: string;
  amount: number;
  note?: string;
}

export interface BudgetReportRow extends BudgetLine {
  budget: number;
  actual: number;
  variance: number;
  pct: number | null;
  status: "within" | "over" | "under" | "unbudgeted";
  unbudgeted: boolean;
}

export interface BudgetReport {
  period: string;
  name: string;
  exists: boolean;
  period_status: string;
  posted_entries: number;
  draft_entries: number;
  rows: BudgetReportRow[];
  totals: {
    budget_income: number;
    actual_income: number;
    income_variance: number;
    budget_expense: number;
    actual_expense: number;
    expense_variance: number;
  };
  warnings: string[];
  boundary: string;
}

export interface CashLine {
  expected_date: string;
  direction: "in" | "out";
  account_code: string;
  counterparty?: string;
  amount: number;
  certainty?: "high" | "medium" | "low";
  note?: string;
}

export interface CashSeries {
  date: string;
  planned_in: number;
  planned_out: number;
  planned_net: number;
  planned_balance: number;
  actual_net: number;
  actual_balance: number;
}

export interface CashReport {
  period: string;
  name: string;
  exists: boolean;
  as_of: string;
  opening: number;
  target_min: number;
  projected_end: number;
  actual_to_date: number;
  planned_to_date: number;
  variance_to_date: number;
  series: CashSeries[];
  warnings: string[];
  boundary: string;
}

export function usePlanPeriods() {
  return useQuery({
    queryKey: ["plan", "periods"],
    queryFn: () => api<{ periods: string[] }>("/api/plan/periods"),
  });
}

export function useBudgetPlan(period: string | null) {
  return useQuery({
    queryKey: ["plan", "budget", period],
    queryFn: () =>
      api<{
        period: string;
        exists: boolean;
        plan: { id: string; note: string } | null;
        lines: BudgetLine[];
        accounts: PlanAccount[];
        periods: string[];
        boundary: string;
      }>(`/api/plan/budget?period=${encodeURIComponent(period ?? "")}`),
    enabled: Boolean(period),
    retry: 0,
  });
}

export function useBudgetReport(period: string | null) {
  return useQuery({
    queryKey: ["plan", "budget-report", period],
    queryFn: () => api<BudgetReport>(`/api/plan/budget/report?period=${encodeURIComponent(period ?? "")}`),
    enabled: Boolean(period),
    retry: 0,
  });
}

export function useCashPlan(period: string | null) {
  return useQuery({
    queryKey: ["plan", "cash", period],
    queryFn: () =>
      api<{
        period: string;
        exists: boolean;
        plan: { id: string; opening: number; target_min: number; note: string } | null;
        lines: CashLine[];
        accounts: PlanAccount[];
        periods: string[];
        boundary: string;
      }>(`/api/plan/cash?period=${encodeURIComponent(period ?? "")}`),
    enabled: Boolean(period),
    retry: 0,
  });
}

export function useCashReport(period: string | null) {
  return useQuery({
    queryKey: ["plan", "cash-report", period],
    queryFn: () => api<CashReport>(`/api/plan/cash/report?period=${encodeURIComponent(period ?? "")}`),
    enabled: Boolean(period),
    retry: 0,
  });
}

function invalidate(qc: ReturnType<typeof useQueryClient>) {
  return qc.invalidateQueries({ queryKey: ["plan"] });
}

export function useSaveBudget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { period: string; lines: BudgetLine[]; note: string }) =>
      api<{ ok: boolean }>("/api/plan/budget", {
        method: "PUT",
        body: JSON.stringify(args),
      }),
    onSuccess: () => invalidate(qc),
    retry: 0,
  });
}

export function useSaveCash() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: {
      period: string;
      lines: CashLine[];
      opening: number;
      target_min: number;
      note: string;
    }) =>
      api<{ ok: boolean }>("/api/plan/cash", {
        method: "PUT",
        body: JSON.stringify(args),
      }),
    onSuccess: () => invalidate(qc),
    retry: 0,
  });
}

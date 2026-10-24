/** 投资策略 API hooks：风险指标 / 再平衡 / 估值分位 / 定投 / FIRE。
 *
 * 与后端 routes/strategy.py 一一对应。所有接口都可能在行情不可用时
 * 返回 available=false —— 这不是错误，前端要展示原因而不是报错。
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

// ---------------------------------------------------------------------------
// 类型契约
// ---------------------------------------------------------------------------

export interface RiskMetrics {
  observations: number;
  total_return_pct: number | null;
  annualized_return_pct: number | null;
  annualized_volatility_pct: number | null;
  sharpe: number | null;
  sortino: number | null;
  max_drawdown_pct: number | null;
  calmar: number | null;
  var_95_pct: number | null;
  beta: number | null;
  alpha_pct: number | null;
  benchmark_return_pct: number | null;
  excess_return_pct: number | null;
  win_rate_pct: number | null;
  best_day_pct: number | null;
  worst_day_pct: number | null;
  notes: string[];
}

export interface RiskResponse {
  available: boolean;
  reason?: string | null;
  basis?: "backtest";
  basis_note?: string;
  benchmark?: string;
  benchmark_name?: string;
  equity_curve?: number[];
  benchmark_curve?: number[] | null;
  metrics?: RiskMetrics;
  diagnostics?: { requested: number; resolved: number; missing: string[] };
  generated_at?: string;
}

export interface DriftItem {
  symbol: string;
  name: string;
  current_pct: number;
  target_pct: number;
  drift_pct: number;
  current_value: number;
  target_value: number;
  action: "buy" | "sell" | "hold";
  amount: number;
  approx_shares: number | null;
  price: number | null;
}

export interface RebalancePlan {
  total_value: number;
  band_pct: number;
  needs_rebalance: boolean;
  max_drift_pct: number;
  target_sum_pct: number;
  items: DriftItem[];
  notes: string[];
}

export interface AllocationTarget {
  symbol: string;
  name: string;
  target_pct: number;
  updated_at?: string;
}

export interface AllocationResponse {
  available: boolean;
  targets: AllocationTarget[];
  plan: RebalancePlan;
  band_pct: number;
}

export interface ValuationItem {
  symbol: string;
  name: string;
  current: number;
  low: number;
  high: number;
  percentile: number;
  zone: "cheap" | "low" | "fair" | "high" | "expensive";
  zone_label: string;
  drawdown_pct: number;
  lookback_days: number;
  observations: number;
  shares?: number;
  market_value?: number;
}

export interface ValuationResponse {
  available: boolean;
  reason?: string | null;
  lookback_days: number;
  items: ValuationItem[];
  zones?: { key: string; label: string; max: number }[];
}

export interface DcaStats {
  invested: number;
  shares: number;
  avg_cost: number | null;
  value: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  periods: number;
  last_buy_date: string | null;
  current_price?: number;
}

export interface DcaPlan {
  id: string;
  symbol: string;
  name: string;
  amount: number;
  frequency: "monthly" | "weekly";
  day: number;
  start_date: string;
  note: string;
  active: boolean;
  created_at: string;
  stats: DcaStats;
  next_run: string | null;
  quote_available: boolean;
}

export interface FireResponse {
  available: boolean;
  monthly_income: number;
  monthly_expense: number;
  annual_expense: number;
  target_principal: number;
  current_net_worth: number;
  progress_pct: number | null;
  savings_rate_pct: number;
  annual_saving: number;
  expected_return_pct: number;
  withdrawal_rate_pct: number;
  years_to_fire: number | null;
  reachable?: boolean;
}

// ---------------------------------------------------------------------------
// Fetchers
// ---------------------------------------------------------------------------

export const fetchRisk = (benchmark = "sh000300") =>
  api<RiskResponse>(`/api/strategy/risk?benchmark=${encodeURIComponent(benchmark)}`);

export const fetchAllocation = (band = 5) =>
  api<AllocationResponse>(`/api/strategy/allocation?band=${band}`);

export const saveAllocation = (targets: { symbol: string; name: string; target_pct: number }[]) =>
  api<{ ok: boolean; targets: AllocationTarget[]; total_pct: number; warning: string | null }>(
    "/api/strategy/allocation",
    { method: "PUT", body: JSON.stringify({ targets }) },
  );

export const fetchValuation = () => api<ValuationResponse>("/api/strategy/valuation");

export const fetchDca = () => api<{ items: DcaPlan[]; available: boolean }>("/api/strategy/dca");

export const saveDca = (payload: Partial<DcaPlan>) =>
  api<{ ok: boolean; plan: DcaPlan }>("/api/strategy/dca", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const deleteDca = (id: string) =>
  api<{ ok: boolean }>(`/api/strategy/dca/${encodeURIComponent(id)}`, { method: "DELETE" });

export const fetchFire = () => api<FireResponse>("/api/strategy/fire");

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useRisk(benchmark = "sh000300") {
  return useQuery({
    queryKey: ["strategy", "risk", benchmark],
    queryFn: () => fetchRisk(benchmark),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
}

export function useAllocation(band = 5) {
  return useQuery({
    queryKey: ["strategy", "allocation", band],
    queryFn: () => fetchAllocation(band),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}

export function useSaveAllocation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: saveAllocation,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["strategy"] });
    },
  });
}

export function useValuation() {
  return useQuery({
    queryKey: ["strategy", "valuation"],
    queryFn: fetchValuation,
    staleTime: 10 * 60_000,
    refetchOnWindowFocus: false,
  });
}

export function useDcaPlans() {
  return useQuery({
    queryKey: ["strategy", "dca"],
    queryFn: fetchDca,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
}

export function useSaveDca() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: saveDca,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["strategy", "dca"] });
    },
  });
}

export function useDeleteDca() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteDca,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["strategy", "dca"] });
    },
  });
}

export function useFire() {
  return useQuery({
    queryKey: ["strategy", "fire"],
    queryFn: fetchFire,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
}

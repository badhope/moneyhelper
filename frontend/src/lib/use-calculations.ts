/** 财务计算类 API hooks：净值 / 体检 / 收益 / 目标进度 —— 基于 TanStack Query v5。 */

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

// ---------------------------------------------------------------------------
// 类型契约（对齐 backend/app/routes/calculations.py 响应结构）
// ---------------------------------------------------------------------------

/** GET /api/calculations/net-worth 响应 */
export interface NetWorthBreakdown {
  date: string;
  total_assets: number;
  total_liabilities: number;
  net_worth: number;
  /** 明细为 {名称: 金额} dict（与后端 NetWorthSnapshot 一致） */
  asset_breakdown: Record<string, number>;
  liability_breakdown: Record<string, number>;
  /** 可选：{负债名称: 年利率}，后端路由附加字段，用于展示利率 */
  liability_rates?: Record<string, number>;
}

/** GET /api/calculations/health 响应 */
export interface HealthScoreResult {
  score: number;
  grade: "A" | "B" | "C" | "D" | "F";
  breakdown: Record<string, { score: number; max: number; label: string; detail: string }>;
}

/** 收益率指标（含错误退化） */
export interface ReturnMetric {
  value: number;
  pct: number;
  start_value?: number;
  end_value?: number;
  net_inflows?: number;
}

/** GET /api/calculations/returns 响应 */
export interface ReturnsResult {
  period_months: number;
  transaction_count: number;
  xirr: ReturnMetric | { error: string };
  twr: ReturnMetric | { error: string };
  simple_return: ReturnMetric | { error: string } | null;
}

/** GET /api/calculations/goals/progress 单项目标（对齐后端字段） */
export interface GoalProgressItem {
  name: string;
  target_amount: number;
  current_amount: number;
  monthly_contribution: number;
  months_remaining: number | null;
  on_track: boolean;
  required_monthly: number;
  progress_pct: number;
}

// ---------------------------------------------------------------------------
// Fetch 函数
// ---------------------------------------------------------------------------

export function fetchNetWorth(): Promise<NetWorthBreakdown> {
  return api<NetWorthBreakdown>("/api/calculations/net-worth");
}

export function fetchHealthScore(): Promise<HealthScoreResult> {
  return api<HealthScoreResult>("/api/calculations/health");
}

export function fetchReturns(months = 6): Promise<ReturnsResult> {
  return api<ReturnsResult>(`/api/calculations/returns?months=${months}`);
}

export function fetchGoalProgress(): Promise<GoalProgressItem[]> {
  return api<{ goals: GoalProgressItem[] }>("/api/calculations/goals/progress").then((r) => r.goals);
}

// ---------------------------------------------------------------------------
// React Hooks
// ---------------------------------------------------------------------------

export function useNetWorth() {
  return useQuery({
    queryKey: ["calcs", "net-worth"],
    queryFn: fetchNetWorth,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}

export function useHealthScore() {
  return useQuery({
    queryKey: ["calcs", "health"],
    queryFn: fetchHealthScore,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}

export function useReturns(months = 6) {
  return useQuery({
    queryKey: ["calcs", "returns", months],
    queryFn: () => fetchReturns(months),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}

export function useGoalProgress() {
  return useQuery({
    queryKey: ["calcs", "goals-progress"],
    queryFn: fetchGoalProgress,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}


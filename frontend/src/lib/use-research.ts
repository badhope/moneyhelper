/** 投研 / 财报 API hooks（v4.0 财务工作台）。

 * 与后端 routes/research.py + routes/statements.py 一一对应。
 * 行情不可用时接口返回 available=false —— 前端展示原因而非报错。
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

// ---------------------------------------------------------------------------
// 类型契约
// ---------------------------------------------------------------------------

export interface TechnicalSignal {
  date: string;
  code: string;
  side: "bull" | "bear" | "neutral";
  text: string;
}

export interface TechnicalSnapshot {
  close: number;
  ma: Record<string, number | null>;
  dif: number | null;
  dea: number | null;
  hist: number | null;
  rsi: number | null;
  boll: { mid: number | null; upper: number | null; lower: number | null };
  kdj: { k: number | null; d: number | null; j: number | null };
}

export interface TechnicalResult {
  point_count: number;
  last: TechnicalSnapshot;
  signals: TechnicalSignal[];
  bias: "bull" | "bear" | "neutral";
  bull_count: number;
  bear_count: number;
  series: {
    dates: string[];
    close: (number | null)[];
    ohlc: [number, number, number, number][];
    ma5: (number | null)[];
    ma10: (number | null)[];
    ma20: (number | null)[];
    ma60: (number | null)[];
    dif: (number | null)[];
    dea: (number | null)[];
    hist: (number | null)[];
    rsi: (number | null)[];
    boll_upper: (number | null)[];
    boll_mid: (number | null)[];
    boll_lower: (number | null)[];
    volume: (number | null)[];
  };
}

export interface QuoteNow {
  symbol: string;
  name: string;
  price: number;
  change: number | null;
  change_pct: number | null;
  source: string;
}

export interface AnalyzeResponse {
  available: boolean;
  symbol: string;
  name?: string;
  quote?: QuoteNow | null;
  technical?: TechnicalResult;
  trend_text?: string;
  reason?: string;
  disclaimer?: string;
}

export interface BacktestResult {
  strategy: "ma_cross" | "dca";
  params: Record<string, unknown>;
  total_return_pct: number | null;
  annualized_return_pct: number | null;
  max_drawdown_pct: number | null;
  sharpe: number | null;
  trade_count?: number;
  rounds?: number;
  win_rate_pct?: number | null;
  profit_factor?: number | null;
  avg_win_pct?: number | null;
  avg_loss_pct?: number | null;
  benchmark_return_pct: number | null;
  final_equity?: number;
  benchmark_equity?: number;
  total_invested?: number;
  final_value?: number;
  curve: {
    dates: string[];
    strategy: number[];
    benchmark: number[];
  };
  trades?: { date: string; side: string; price: number; amount: number }[];
}

export interface BacktestResponse {
  available: boolean;
  symbol: string;
  strategy: string;
  result?: BacktestResult;
  text?: string;
  reason?: string;
  disclaimer?: string;
}

export interface ForecastResult {
  horizon: number;
  last_close: number;
  bias: "up" | "down" | "neutral";
  slope_pct: number | null;
  vol_annual_pct: number | null;
  mean_reversion_pct: number | null;
  dates: string[];
  close: (number | null)[];
  trend_line: (number | null)[];
  median: (number | null)[];
  p5: (number | null)[];
  p95: (number | null)[];
  note: string;
  disclaimer: string;
}

export interface ForecastResponse {
  available: boolean;
  symbol: string;
  period: string;
  forecast?: ForecastResult;
  text?: string;
  reason?: string;
  disclaimer?: string;
}

export interface StatementMetricRow {
  period: string;
  metrics: Record<string, number | null>;
}

export interface StatementAlert {
  code: string;
  level: "bad" | "warn";
  text: string;
}

export interface StatementAnalysis {
  company: string;
  currency: string;
  period_count: number;
  periods: StatementMetricRow[];
  latest: Record<string, number | null>;
  trends: {
    periods: string[];
    revenue: (number | null)[];
    net_profit: (number | null)[];
    gross_margin: (number | null)[];
    net_margin: (number | null)[];
    roe: (number | null)[];
    debt_ratio: (number | null)[];
    ocf: (number | null)[];
    current_ratio: (number | null)[];
    asset_turnover: (number | null)[];
    cashflow_stack?: {
      operating: (number | null)[];
      investing: (number | null)[];
      financing: (number | null)[];
    };
  };
  dupont: {
    net_margin_pct: number | null;
    asset_turnover: number | null;
    equity_multiplier: number | null;
    roe_pct: number | null;
    complete: boolean;
  };
  alerts: StatementAlert[];
  report_text: string;
  id?: string;
  created_at?: string;
}

export interface StatementListItem {
  id: string;
  company: string;
  currency: string;
  created_at: string;
  summary: string;
}

// ---------------------------------------------------------------------------
// 投研 hooks
// ---------------------------------------------------------------------------

export function useResearchAnalyze(symbol: string | null, period: "daily" | "weekly" | "monthly" = "daily") {
  return useQuery({
    queryKey: ["research-analyze", symbol, period],
    queryFn: () =>
      api<AnalyzeResponse>(
        `/api/research/analyze?symbol=${encodeURIComponent(symbol ?? "")}&period=${period}`,
      ),
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });
}

/** 回测策略全集：必须与后端 /api/research/backtest 的 STRATEGIES 一致 */
export type BacktestStrategy = "ma_cross" | "dca" | "grid" | "trend" | "vol_target";

/** 回测参数是否可用（与后端 /api/research/backtest 的校验口径一致）。
 *
 * fast >= slow 时后端返回 400：快线周期不小于慢线，「多头排列」判据反向，
 * 跑出来的是一份格式完整但语义相反的报告。这种请求不该发出去。
 * 单独导出是为了可测——纯函数，不需要挂 QueryClient。
 */
export function isBacktestParamsValid(
  strategy: BacktestStrategy,
  params: { fast?: number; slow?: number; invest_amount?: number; freq_days?: number },
): boolean {
  if (strategy !== "ma_cross") return true;
  const fast = params.fast ?? 5;
  const slow = params.slow ?? 20;
  return fast >= 2 && slow >= 2 && fast < slow;
}

export function useResearchBacktest(
  symbol: string | null,
  strategy: BacktestStrategy,
  params?: { fast?: number; slow?: number; invest_amount?: number; freq_days?: number },
) {
  const p = params ?? {};
  // 参数非法时不发请求：保持上一次结果，等用户改回合法值再重新回测。
  const maParamsInvalid = !isBacktestParamsValid(strategy, p);
  return useQuery({
    queryKey: ["research-backtest", symbol, strategy, p.fast ?? 5, p.slow ?? 20, p.invest_amount ?? 1000, p.freq_days ?? 5],
    queryFn: () => {
      const qs = new URLSearchParams({ symbol: symbol ?? "", strategy });
      if (p.fast != null && strategy === "ma_cross") qs.set("fast", String(p.fast));
      if (p.slow != null && strategy === "ma_cross") qs.set("slow", String(p.slow));
      if (p.invest_amount != null && strategy === "dca") qs.set("invest_amount", String(p.invest_amount));
      if (p.freq_days != null && strategy === "dca") qs.set("freq_days", String(p.freq_days));
      return api<BacktestResponse>(`/api/research/backtest?${qs.toString()}`);
    },
    enabled: !!symbol && !maParamsInvalid,
    staleTime: 10 * 60 * 1000,
    retry: 1,
  });
}

export function useResearchForecast(symbol: string | null, period: "daily" | "weekly" | "monthly" = "daily", days = 20) {
  return useQuery({
    queryKey: ["research-forecast", symbol, period, days],
    queryFn: () =>
      api<ForecastResponse>(
        `/api/research/forecast?symbol=${encodeURIComponent(symbol ?? "")}&period=${period}&days=${days}`,
      ),
    enabled: !!symbol,
    staleTime: 10 * 60 * 1000,
    retry: 1,
  });
}

// ---------------------------------------------------------------------------
// 财报 hooks
// ---------------------------------------------------------------------------

export function useStatementAnalyze() {
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api<StatementAnalysis>("/api/statements/analyze", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
  });
}

export function useStatementSave() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api<StatementAnalysis & { id: string }>("/api/statements", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["statements-list"] });
    },
  });
}

export function useStatementList() {
  return useQuery({
    queryKey: ["statements-list"],
    queryFn: () => api<{ items: StatementListItem[]; total: number }>("/api/statements"),
    staleTime: 60 * 1000,
  });
}

export function useStatementDelete() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api<{ deleted: string }>(`/api/statements/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["statements-list"] });
    },
  });
}

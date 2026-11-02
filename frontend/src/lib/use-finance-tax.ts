/** 计算引擎 API hooks（v4.5）：税负 / 个税 / 工资 / 月结 / 现金流 / 订阅 / 异常。
 *
 * 全部为确定性后端计算，前端只做参数收集与展示。
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export interface VatResult {
  method: string;
  output_vat: number;
  input_vat: number;
  vat_payable: number;
  surcharge: number;
  total: number;
  surcharge_detail?: { city_construction: number; education: number; local_education: number };
  note: string;
}

export interface CitResult {
  accounting_profit: number;
  taxable_income: number;
  loss_used: number;
  rate: number;
  category: string;
  tax_payable: number;
  net_profit: number;
  effective_rate: number;
  note: string;
}

export interface IitResult {
  months: number;
  cumulative_income: number;
  taxable_income: number;
  cumulative_tax: number;
  already_withheld: number;
  current_withholding: number;
  effective_rate: number;
}

export interface PayrollResult {
  gross: number;
  employee: Record<string, number>;
  employer: Record<string, number>;
  employee_total: number;
  employer_total: number;
  taxable_income: number;
  income_tax: number;
  net_pay: number;
  employer_cost: number;
  notes: string[];
  disclaimer: string;
}

export interface MonthEndItem {
  id: string;
  title: string;
  detail: string;
  done: boolean;
}

export interface MonthEndResult {
  month: string;
  items: MonthEndItem[];
  done: number;
  total: number;
  progress_pct: number;
  disclaimer: string;
}

export interface ForecastScenario {
  monthly_net: number;
  rows: { offset_month: number; month_net: number; balance: number }[];
  ending_balance: number;
  goes_negative: boolean;
}

export interface ForecastResult {
  available: boolean;
  reason?: string;
  basis?: string;
  opening_balance?: number;
  monthly?: { month: string; income: number; expense: number; net: number }[];
  stats?: { active_months: number; p20: number; median: number; p80: number; mean: number; stdev: number };
  scenarios?: Record<"pessimistic" | "base" | "optimistic", ForecastScenario>;
  excluded_large?: { date: string; item: string; amount: number }[];
  warnings?: string[];
  disclaimer?: string;
}

export interface SubscriptionItem {
  name: string;
  period: "monthly" | "quarterly" | "yearly";
  amount: number;
  monthly_equivalent: number;
  samples: number;
  median_interval_days: number;
  last_charged: string;
  next_expected: string;
  days_until_next: number;
  price_hike: boolean;
  previous_amount: number | null;
}

export interface SubscriptionResult {
  items: SubscriptionItem[];
  count: number;
  monthly_total: number;
  annual_total: number;
  hikes: SubscriptionItem[];
}

export interface AnomalyItem {
  item: string;
  category: string;
  date: string;
  amount: number;
  median: number;
  score: number;
  multiple: number | null;
  samples: number;
  suggestion: string;
}

export interface AnomalyResult {
  items: AnomalyItem[];
  count: number;
  method: string;
  lookback_days: number;
}

function post<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, { method: "POST", body: JSON.stringify(body) });
}

export function useCalcVat() {
  return useMutation({ mutationFn: (body: Record<string, unknown>) => post<VatResult>("/api/finance/tax/vat", body) });
}

export function useCalcCit() {
  return useMutation({ mutationFn: (body: Record<string, unknown>) => post<CitResult>("/api/finance/tax/cit", body) });
}

export function useCalcIit() {
  return useMutation({ mutationFn: (body: Record<string, unknown>) => post<IitResult>("/api/finance/tax/iit", body) });
}

export function useCalcPayroll() {
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => post<PayrollResult>("/api/finance/tax/payroll", body),
  });
}

export function useMonthEnd(month: string) {
  return useQuery({
    queryKey: ["/api/finance/month-end", month],
    queryFn: () => api<MonthEndResult>(`/api/finance/month-end/${encodeURIComponent(month)}`),
    enabled: /^\d{4}-\d{2}$/.test(month),
    staleTime: 30_000,
  });
}

export function useForecast(monthsAhead = 3) {
  return useQuery({
    queryKey: ["/api/finance/cashflow/forecast", monthsAhead],
    queryFn: () =>
      api<ForecastResult>(`/api/finance/cashflow/forecast?months_ahead=${monthsAhead}`),
    staleTime: 60_000,
  });
}

export function useDetectedSubscriptions() {
  return useQuery({
    queryKey: ["/api/finance/subscriptions/detect"],
    queryFn: () => api<SubscriptionResult>("/api/finance/subscriptions/detect"),
    staleTime: 60_000,
  });
}

export function useAnomalies(lookbackDays = 180) {
  return useQuery({
    queryKey: ["/api/finance/anomalies", lookbackDays],
    queryFn: () => api<AnomalyResult>(`/api/finance/anomalies?lookback_days=${lookbackDays}`),
    staleTime: 60_000,
  });
}

/** 月结勾选状态保存在本机（清单是模板，进度按人本地维护）。 */
export function useMonthEndProgress(month: string) {
  const key = `mh.monthEnd.${month}`;
  const qc = useQueryClient();
  const read = (): string[] => {
    try {
      const raw = localStorage.getItem(key);
      return raw ? (JSON.parse(raw) as string[]) : [];
    } catch {
      return [];
    }
  };
  const write = (ids: string[]) => {
    try {
      localStorage.setItem(key, JSON.stringify(ids));
    } catch {
      /* ignore */
    }
    void qc.invalidateQueries({ queryKey: ["/api/finance/month-end", month] });
  };
  return { read, write };
}

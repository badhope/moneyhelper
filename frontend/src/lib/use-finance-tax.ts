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
  /** 累计口径应预扣税额（months>1 时覆盖整个期间，不是单月） */
  income_tax: number;
  /** 当月应预扣税额：months>1 且未传已预扣时，与 income_tax 不同 */
  current_month_tax?: number;
  /** 单月实发 */
  net_pay: number;
  /** months 个月的合计实发（months=1 时等于 net_pay） */
  period_net_pay?: number;
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

export interface TimelineMonth {
  month: string;
  status: "open" | "closed" | "missing";
  closed_at: string;
  income: number;
  expense: number;
  profit: number;
  cash_in: number;
  cash_out: number;
  cash_net: number;
  tax_accrued: number;
  tax_paid: number;
  tax_net: number;
  posted_entries: number;
  draft_entries: number;
  source: "gl_posted" | "none";
}

export interface TimelineResult {
  months: TimelineMonth[];
  range: { from: string; to: string };
  period_count: number;
  missing_count: number;
  source: string;
  boundary: string;
}

export interface TimelineEntryLine {
  line_no: number;
  account_code: string;
  account_name: string;
  account_type: string;
  debit: number;
  credit: number;
  memo: string;
}

export interface TimelineEntry {
  id: number;
  entry_no: string;
  entry_date: string;
  description: string;
  source: string;
  posted_at: string;
  lines: TimelineEntryLine[];
}

export interface TimelineMonthDetail {
  month: string;
  status: "open" | "closed" | "missing";
  closed_at: string;
  entries: TimelineEntry[];
  posted_entries: number;
  draft_entries: number;
  totals: { debit: number; credit: number };
  boundary: string;
}

export interface AttributionCandidate {
  category: string;
  source: "custom_rule" | "rule" | "history" | "existing" | "fallback";
  confidence: number;
  rule_id: string;
  matched: string[];
  reason: string;
}

export interface AttributionRow {
  transaction_id: number;
  date: string;
  item: string;
  amount: number;
  direction: "收入" | "支出";
  current_category: string;
  candidate: AttributionCandidate;
  alternatives: { category: string; source: string; confidence: number; count?: number }[];
  needs_review: boolean;
}

export interface AttributionResult {
  transactions: AttributionRow[];
  pending: number;
  resolved: number;
  total: number;
  coverage: number;
  categories: string[];
  source: string;
  boundary: string;
  scan_limit: number;
  custom_rule_hits: Record<string, number>;
}

export interface AttributionRule {
  rule_id: string;
  name: string;
  keyword: string;
  category: string;
  direction: "" | "收入" | "支出";
  priority: number;
  merchant?: string;
  min_amount_cents?: number;
  max_amount_cents?: number;
  member_id?: number | null;
  enabled: number;
  confirmed: number;
  reverted: number;
  created_at: string;
  updated_at: string;
}

export interface AttributionRulesResult {
  rules: AttributionRule[];
  count: number;
  enabled: number;
  max_rules: number;
  categories: string[];
  boundary: string;
}

export interface ConfirmedAttribution {
  transaction_id: number;
  original_category: string;
  confirmed_category: string;
  source: string;
  rule_id: string;
  confidence: number;
  confirmed_at: string;
  date: string;
  item: string;
  amount: number;
}

export interface AttributionStats {
  confirmed_total: number;
  reverted_total: number;
  by_source: Record<string, number>;
  by_rule: { source: string; rule_id: string; n: number }[];
  reverted_by_rule: { rule_id: string; n: number }[];
  boundary: string;
}

function post<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, { method: "POST", body: JSON.stringify(body) });
}

function put<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, { method: "PUT", body: JSON.stringify(body) });
}

function del<T>(path: string): Promise<T> {
  return api<T>(path, { method: "DELETE" });
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

/** 财税时序：只读总账已过账凭证，12 个月时间轴。 */
export function useFinanceTimeline(months = 12) {
  return useQuery({
    queryKey: ["/api/finance/timeline", months],
    queryFn: () => api<TimelineResult>(`/api/finance/timeline?months=${months}`),
    staleTime: 60_000,
  });
}

export function useFinanceTimelineMonth(month: string | null) {
  return useQuery({
    queryKey: ["/api/finance/timeline", "month", month],
    queryFn: () => api<TimelineMonthDetail>(`/api/finance/timeline/${month}`),
    enabled: Boolean(month),
    retry: 0,
  });
}

export function useAttributionCandidates(limit = 50) {
  return useQuery({
    queryKey: ["/api/finance/attribution/candidates", limit],
    queryFn: () => api<AttributionResult>(`/api/finance/attribution/candidates?limit=${limit}`),
    staleTime: 30_000,
  });
}

export function useConfirmAttribution() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      post<{ ok: boolean; transaction_id: number; category: string; previous_category: string }>(
        "/api/finance/attribution/confirm",
        body,
      ),
    onSuccess: () => invalidateAttribution(qc),
  });
}

export function useAttributionRules() {
  return useQuery({
    queryKey: ["/api/finance/attribution/rules"],
    queryFn: () => api<AttributionRulesResult>("/api/finance/attribution/rules"),
    staleTime: 30_000,
  });
}

export function useConfirmedAttributions(limit = 20) {
  return useQuery({
    queryKey: ["/api/finance/attribution/confirmed", limit],
    queryFn: () =>
      api<{ items: ConfirmedAttribution[]; count: number }>(
        `/api/finance/attribution/confirmed?limit=${limit}`,
      ),
    staleTime: 30_000,
  });
}

export function useAttributionStats() {
  return useQuery({
    queryKey: ["/api/finance/attribution/stats"],
    queryFn: () => api<AttributionStats>("/api/finance/attribution/stats"),
    staleTime: 30_000,
  });
}

function invalidateAttribution(qc: ReturnType<typeof useQueryClient>) {
  // 不能只传 queryKey 前缀数组：React Query 按元素相等做前缀匹配，
  // "/api/finance/attribution" 不等于 "/api/finance/attribution/rules"。
  void qc.invalidateQueries({
    predicate: (q) => String(q.queryKey[0] ?? "").startsWith("/api/finance/attribution"),
  });
  void qc.invalidateQueries({ queryKey: ["dashboard"] });
}

export function useConfirmAttributionBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (items: Record<string, unknown>[]) =>
      post<{ ok: boolean; confirmed: number }>("/api/finance/attribution/confirm-batch", {
        items,
      }),
    onSuccess: () => invalidateAttribution(qc),
  });
}

export function useRollbackAttribution() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (transactionId: number) =>
      post<{ ok: boolean; transaction_id: number; restored_category: string }>(
        "/api/finance/attribution/rollback",
        { transaction_id: transactionId },
      ),
    onSuccess: () => invalidateAttribution(qc),
  });
}

export function useCreateAttributionRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      post<{ ok: boolean; rule: AttributionRule }>("/api/finance/attribution/rules", body),
    onSuccess: () => invalidateAttribution(qc),
  });
}

export function useUpdateAttributionRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ ruleId, body }: { ruleId: string; body: Record<string, unknown> }) =>
      put<{ ok: boolean; rule: AttributionRule }>(
        `/api/finance/attribution/rules/${ruleId}`,
        body,
      ),
    onSuccess: () => invalidateAttribution(qc),
  });
}

export function useDeleteAttributionRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ruleId: string) =>
      del<{ ok: boolean; rule_id: string }>(`/api/finance/attribution/rules/${ruleId}`),
    onSuccess: () => invalidateAttribution(qc),
  });
}

export function useTestAttributionRule() {
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      post<{ matched: boolean; candidate: AttributionCandidate | null; rules_checked: number }>(
        "/api/finance/attribution/rules/test",
        body,
      ),
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

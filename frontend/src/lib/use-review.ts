/** 数字身份证 + 月度结账复盘：只读本地账本，数字由后端确定性计算。 */

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ControlTier } from "@/lib/use-connect";

export interface IdentityRiskItem {
  code: string;
  level: string;
  text: string;
}

export interface IdentityCardData {
  generated_at: string;
  fingerprint: string;
  profile: {
    display_name: string;
    mode: "real" | "demo" | "seed";
    mode_label: string;
    base_currency: string;
    storage: string;
  };
  financials: {
    assets: number;
    cash: number;
    invested: number;
    liabilities: number;
    net_worth: number;
    monthly_income: number;
    monthly_expense: number;
    monthly_net: number;
    savings_rate: number;
    expected_monthly_income: number;
    emergency_months: number;
    emergency_target_months: number;
    dti_pct: number;
    risk_flags: number;
  };
  coverage: {
    positions: number;
    transactions: number;
    active_months: number;
    subscriptions: number;
    debts: number;
    goals: number;
    connections: number;
    budget_set: boolean;
    accounts_by_control: Record<ControlTier, number>;
  };
  risk: {
    count: number;
    items: IdentityRiskItem[];
    concentration_breaches: number;
  };
  permissions: {
    local_only: boolean;
    revocable: boolean;
    account_connections: number;
    controls: Record<ControlTier, number>;
    ai_can: string[];
    ai_cannot: string[];
  };
  provenance: {
    ledger: string;
    quotes: string;
    last_transaction: string;
    last_connection_sync: string;
    demo: boolean;
    seeded: boolean;
  };
  boundaries: string[];
}

export interface ReviewAction {
  code: string;
  title: string;
  detail: string;
  amount: number | null;
}

export interface ReviewCheck {
  id: string;
  label: string;
  ok: boolean;
}

export interface MonthlyReviewData {
  month: string;
  generated_at: string;
  fingerprint: string;
  status: "in_progress" | "closed";
  period: { start: string; end: string; as_of: string; days_in_period: number };
  headline: string;
  verdict: string;
  savings_target: number;
  cashflow: {
    income: number;
    expense: number;
    net: number;
    savings_rate: number;
    essential: number;
    transaction_count: number;
    uncategorized: number;
    by_category: { category: string; amount: number }[];
    top_categories: { category: string; amount: number; share_pct: number }[];
    previous: {
      month: string;
      income: number;
      expense: number;
      net: number;
      savings_rate: number;
      income_delta_pct: number | null;
      expense_delta_pct: number | null;
      net_delta: number;
    };
  };
  budget: {
    total: number;
    spent: number;
    pct: number;
    over: boolean;
    over_categories: { category: string; budget: number; spent: number; pct: number; over: boolean }[];
    categories: { category: string; budget: number; spent: number; pct: number; over: boolean }[];
  };
  categories: { category: string; amount: number; share_pct: number }[];
  subscriptions: {
    count: number;
    monthly_total: number;
    annual_total: number;
    top: { name: string; monthly: number }[];
  };
  debts: { count: number; balance: number; monthly: number; dti_pct: number };
  goals: { count: number; done: number; behind: number; gap: number };
  anomalies: {
    count: number;
    total: number;
    items: { item: string; category: string; date: string; amount: number; median: number; multiple: number | null }[];
  };
  coverage: {
    transactions: number;
    days_with_transactions: number;
    days_in_period: number;
    coverage_pct: number;
    uncategorized: number;
    budget_set: boolean;
  };
  closing: {
    checks: ReviewCheck[];
    passed: number;
    total: number;
    completeness_pct: number;
    ready: boolean;
    note: string;
  };
  actions: ReviewAction[];
  disclaimer: string;
}

async function getIdentityCard(lang: string): Promise<IdentityCardData> {
  return api<IdentityCardData>(`/api/identity/card?lang=${lang}`);
}

async function getMonthlyReview(month: string, lang: string): Promise<MonthlyReviewData> {
  return api<MonthlyReviewData>(`/api/review/monthly/${month}?lang=${lang}`);
}

export function useIdentityCard(lang: string) {
  return useQuery({
    queryKey: ["identity-card", lang],
    queryFn: () => getIdentityCard(lang),
    staleTime: 15_000,
    retry: 1,
  });
}

export function useMonthlyReview(month: string, lang: string) {
  return useQuery({
    queryKey: ["monthly-review", month, lang],
    queryFn: () => getMonthlyReview(month, lang),
    staleTime: 5_000,
    retry: 1,
    enabled: /^\d{4}-\d{2}$/.test(month),
  });
}

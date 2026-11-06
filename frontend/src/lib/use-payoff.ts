/** 债务清偿规划数据层：GET 取计划、POST 取两方法对比。
 *
 * 为什么 compare 单独一个 query 而不是同一请求都返回：
 * 对比要跑两遍完整模拟（雪崩 + 雪球），用户改额外还款额时每 400ms 都要跑；
 * 计划本身只需要一遍。分开后改数字只重跑当前方法，对比结果按同样参数缓存，
 * 两边参数一致时直接从缓存读，不会出现「对比块显示的是上一次的数字」。
 *
 * 两个 query 的 key 都带上 params，参数一变立刻视为过期——不使用手工
 * 「先清空再重取」的写法，避免中间态显示上一个参数的结果。
 */

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export interface PayoffDebt {
  name: string;
  balance: number;
  rate: number;
  min_payment: number;
}

export interface PayoffMilestone {
  month: number;
  name: string;
  date: string;
}

export interface PayoffPlan {
  available: true;
  method: "avalanche" | "snowball" | "custom";
  order: string[];
  monthly_budget: number;
  extra_payment: number;
  months: number;
  years: number;
  total_interest: number;
  total_paid: number;
  debt_free_date: string | null;
  /** 只付最低月供的对照利息；基线还不完时为 null */
  baseline_interest: number | null;
  /** 相比基线的可省利息；基线不可算或本方案不可行时为 null */
  interest_saved: number | null;
  /** 基线（只付最低）是否能还清 */
  baseline_available: boolean;
  milestones: PayoffMilestone[];
  warnings: string[];
  notes: string[];
  warning_codes?: { code: string; amount?: number }[];
  note_codes?: { code: string; amount?: number }[];
  schedule_months: number;
  debts: PayoffDebt[];
}

export interface PayoffUnavailable {
  available: false;
  reason: string;
  debts: PayoffDebt[];
}

export interface PayoffCompare {
  avalanche: Omit<PayoffPlan, "debts" | "available">;
  snowball: Omit<PayoffPlan, "debts" | "available">;
  /** 一方不可行时为 null（不做减法，见引擎 compare_methods） */
  interest_diff: number | null;
  comparable: boolean;
  verdict: string;
  verdict_code?: { code: string; amount?: number };
}

/** POST 在「没有可规划负债」时也返回 available:false，前端必须能降级。 */
export interface PayoffCompareUnavailable {
  available: false;
  reason: string;
  debts: PayoffDebt[];
}

export function usePayoffPlan(extraPayment: number, method: "avalanche" | "snowball") {
  const plan = useQuery({
    queryKey: ["/api/finance/debts/payoff", extraPayment, method],
    queryFn: () =>
      api<PayoffPlan | PayoffUnavailable>(
        `/api/finance/debts/payoff?extra_payment=${extraPayment}&method=${method}`,
      ),
    staleTime: 30_000,
    // 改参数时保留上一份结果：否则每次防抖后 isPending 变真、整页换成骨架屏，
    // 输入框被卸载 → 用户必须重新点一下才能继续输入（实测失焦）。
    placeholderData: keepPreviousData,
  });

  const compare = useQuery({
    queryKey: ["/api/finance/debts/payoff", "compare", extraPayment],
    queryFn: () =>
      api<PayoffCompare>("/api/finance/debts/payoff", {
        method: "POST",
        body: JSON.stringify({ extra_payment: extraPayment, compare: true }),
      }),
    staleTime: 30_000,
    // 对比只是附加信息：失败时不要让整页降级（主计划仍可用）
    retry: false,
  });

  return { ...plan, compare };
}

/** 服务端状态层：TanStack Query 统一缓存 dashboard / bootstrap / sessions。
 *
 * 替代旧的 useSyncExternalStore 手写 store：
 * - 自动去重并发请求（同 key 只发一次）
 * - 变更类请求后 invalidateQueries 自动重拉，不再手写 seq 防竞态
 * - 首屏保持"乐观渲染"语义：useQuery 默认 stale-while-revalidate，
 *   data 为空时调用方照旧显示占位/继续渲染（与旧 inited 立即 true 行为一致）
 *
 * 对外 API：
 * - useDashboard() / useBootstrap() / useSessions() —— 字段级 hooks（替代 store.useApp 取字段）
 * - store.bump() / refreshXxx() —— 变更后的刷新入口（行为不变）
 */

import {
  QueryClient,
  useQuery,
  type QueryClient as TQClient,
} from "@tanstack/react-query";
import { api } from "./api";
import { useI18n } from "./i18n";
import type { BootstrapData, DashboardData, SessionItem, SessionUsage } from "./types";

export const queryKeys = {
  dashboard: ["dashboard"] as const,
  bootstrap: ["bootstrap"] as const,
  sessions: ["sessions"] as const,
  sessionUsage: ["session-usage"] as const,
};

let client: TQClient | null = null;

/** 供 Provider 之外的模块级函数（如 api.ts 里的 mutation）取 client；
 *  正常路径下 main.tsx 已通过 setQueryClient 注入 Provider 的 client，
 *  此处惰性兜底仅用于单测/脚本等非 React 环境。 */
export function getQueryClient(): TQClient {
  if (!client) {
    client = new QueryClient();
  }
  return client;
}

export function setQueryClient(c: TQClient): void {
  client = c;
}

function fetchDashboard(lang: string): Promise<DashboardData> {
  return api<DashboardData>(`/api/dashboard?lang=${lang}`);
}

function fetchBootstrap(): Promise<BootstrapData> {
  return api<BootstrapData>("/api/bootstrap");
}

function fetchSessions(): Promise<SessionItem[]> {
  return api<{ sessions: SessionItem[] }>("/api/sessions").then((r) => r.sessions ?? []);
}

export function useDashboard() {
  // lang 进入 queryKey：切换语言自动重新拉取（flags/来源标签跟随语言），无需手动刷新
  const { lang } = useI18n();
  const l = lang?.startsWith("en") ? "en" : "zh";
  const q = useQuery({ queryKey: [...queryKeys.dashboard, l], queryFn: () => fetchDashboard(l) });
  return {
    dashboard: q.data ?? null,
    loading: q.isPending,
    error: q.isError ? (q.error instanceof Error ? q.error.message : String(q.error)) : null,
    refresh: q.refetch,
  };
}

export function useBootstrap() {
  const q = useQuery({ queryKey: queryKeys.bootstrap, queryFn: fetchBootstrap });
  return { bootstrap: q.data ?? null };
}

export function useSessions() {
  const q = useQuery({ queryKey: queryKeys.sessions, queryFn: fetchSessions });
  return { sessions: q.data ?? [], loading: q.isPending };
}

/**
 * 会话 token 用量（harness 上下文仪表）。
 *
 * 计量数据只在有模型时产生，所以失败一律静默返回 null——不能因为
 * 「用量接口不可用」就让对话页出现错误条。
 */
export function useSessionUsage(threadId: string | null | undefined) {
  const q = useQuery({
    queryKey: [...queryKeys.sessionUsage, threadId ?? ""],
    queryFn: () => api<SessionUsage>(`/api/sessions/by-thread/${threadId}/usage`),
    enabled: Boolean(threadId),
    retry: false,
    staleTime: 5_000,
  });
  return { usage: q.data ?? null };
}

/**
 * 一次写操作会让所有「同一份数据的派生视图」变旧。这里是单一失效入口：
 * 漏掉任何一个 key，用户就会在同一屏看到两套矛盾数字（记一笔账后
 * 顶部总资产更新、净值卡/健康分/收益卡仍是旧值）。
 *
 * 因此按「前缀」而不是逐个枚举具体查询，新增派生查询只要复用这些前缀
 * 就自动被覆盖；同时保留 refreshAll 给需要强刷的场景。
 */
const DERIVED_PREFIXES: readonly (readonly unknown[])[] = [
  queryKeys.dashboard,
  queryKeys.sessions,
  queryKeys.sessionUsage,
  ["budgets"],
  ["trend"],
  ["calcs"],          // net-worth / health / returns / goals-progress
  ["subscriptions"],
  ["evaluate"],
  ["goals"],
  ["connect"],
  ["paper"],
];

export function invalidateBump(): void {
  const c = getQueryClient();
  for (const key of DERIVED_PREFIXES) {
    void c.invalidateQueries({ queryKey: key as unknown[] });
  }
}

/** 强刷：写操作后需要「立刻看到新数字」时用（invalidate 只是标记 stale）。 */
export async function refetchAllFinancial(): Promise<void> {
  const c = getQueryClient();
  await Promise.all(
    DERIVED_PREFIXES.map((key) => c.refetchQueries({ queryKey: key as unknown[] })),
  );
}

/** 兼容旧 `store` 对象形状：内部转发到 TanStack Query，调用方 import { store } 不用改。 */
export const store = {
  bump: invalidateBump,
  refreshDashboard: () => getQueryClient().invalidateQueries({ queryKey: queryKeys.dashboard }),
  refreshBootstrap: () => getQueryClient().invalidateQueries({ queryKey: queryKeys.bootstrap }),
  refreshSessions: () => getQueryClient().invalidateQueries({ queryKey: queryKeys.sessions }),
};

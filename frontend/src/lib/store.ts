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

/** 数据变更后统一失效（记账 / 设置 / 问答完成时调用；语义同旧 bump()）。
 *  顺带失效 budgets / trend，避免 Dashboard 里 useQuery 的独立数据变旧。 */
export function invalidateBump(): void {
  const c = getQueryClient();
  void c.invalidateQueries({ queryKey: queryKeys.dashboard });
  void c.invalidateQueries({ queryKey: queryKeys.sessions });
  void c.invalidateQueries({ queryKey: ["budgets"] });
  void c.invalidateQueries({ queryKey: ["trend"] });
}

/** 兼容旧 `store` 对象形状：内部转发到 TanStack Query，调用方 import { store } 不用改。 */
export const store = {
  bump: invalidateBump,
  refreshDashboard: () => getQueryClient().invalidateQueries({ queryKey: queryKeys.dashboard }),
  refreshBootstrap: () => getQueryClient().invalidateQueries({ queryKey: queryKeys.bootstrap }),
  refreshSessions: () => getQueryClient().invalidateQueries({ queryKey: queryKeys.sessions }),
};

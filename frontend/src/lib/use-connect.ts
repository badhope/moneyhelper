/** 连接中心 API hooks：目录 / 连接 / 配对 / 同步 / 收件箱 / 行情 / 交易意图。
 *
 * 对应后端 routes/connect.py。所有外部数据源都允许降级：
 * items 为空 + note 有值不是错误，页面要显示原因而不是报错。
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

// ---------------------------------------------------------------------------
// 类型契约
// ---------------------------------------------------------------------------

export type ConnectorKind = "public_api" | "deep_link" | "browser_login" | "file_import";
export type Automation = "auto" | "semi" | "manual";

export interface Connection {
  id: string;
  connector_id: string;
  label: string;
  kind: ConnectorKind;
  status: "unconfigured" | "connected" | "expiring" | "error" | "disabled";
  account_ref: string;
  meta: Record<string, unknown>;
  last_sync_at: string;
  last_error: string;
  created_at: string;
  updated_at: string;
}

export interface Connector {
  id: string;
  name: string;
  vendor: string;
  category: string;
  kind: ConnectorKind;
  automation: Automation;
  capabilities: string[];
  login_url: string;
  data_url: string;
  docs_url: string;
  note: string;
  requires_login: boolean;
  supports_auto_sync: boolean;
  supports_trade: boolean;
  fields: string[];
  connections: Connection[];
}

export interface CatalogResponse {
  groups: { key: string; label: string; items: Connector[] }[];
  counts: { total: number; auto: number; semi: number; manual: number; trade: number };
  kinds: ConnectorKind[];
  automation: Automation[];
  connections: Connection[];
  kinds_label: Record<string, string>;
}

export interface SourceStatusItem {
  id: string;
  ok: boolean;
  detail: string;
}

export interface IndexQuoteItem {
  symbol: string;
  name: string;
  price: number;
  change: number | null;
  change_pct: number | null;
}

export interface MoverItem {
  symbol: string;
  name: string;
  price: number | null;
  change_pct: number | null;
  amount: number | null;
  turnover_pct?: number | null;
}

export interface FundNavItem {
  code: string;
  name: string;
  nav: number;
  acc_nav: number | null;
  change_pct: number | null;
  date: string;
  source: string;
}

export interface Pairing {
  code: string;
  connector_id: string;
  connector_name: string;
  expires_at: string;
  ttl_minutes: number;
  login_url: string;
}

export interface SyncResult {
  id?: string;
  status?: string;
  message?: string;
  ok?: boolean;
  login_url?: string;
  pairing?: Pairing;
  bookmarklet?: string;
  ingest_endpoint?: string;
  [key: string]: unknown;
}

export interface TradeIntent {
  id: string;
  connector_id: string;
  symbol: string;
  name: string;
  side: "buy" | "sell";
  price: number;
  shares: number;
  amount: number;
  mode: "paper" | "live";
  status: "draft" | "awaiting_confirm" | "executed" | "rejected" | "expired";
  note: string;
  result: Record<string, unknown>;
  created_at: string;
  executed_at: string;
}

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

export function useCatalog() {
  return useQuery({
    queryKey: ["/api/connect/catalog"],
    queryFn: () => api<CatalogResponse>("/api/connect/catalog"),
    staleTime: 30_000,
  });
}

export function useSourceStatus() {
  return useQuery({
    queryKey: ["/api/connect/sources/status"],
    queryFn: () => api<{ items: SourceStatusItem[]; checked_at: string }>("/api/connect/sources/status"),
    staleTime: 60_000,
  });
}

export function useIndices() {
  return useQuery({
    queryKey: ["/api/connect/indices"],
    queryFn: () =>
      api<{ items: IndexQuoteItem[]; source: string; note: string }>("/api/connect/indices"),
    staleTime: 30_000,
  });
}

export function useMovers(kind: string) {
  return useQuery({
    queryKey: ["/api/connect/movers", kind],
    queryFn: () =>
      api<{ items: MoverItem[]; source: string; note: string }>(
        `/api/connect/movers?kind=${encodeURIComponent(kind)}&limit=15`,
      ),
    staleTime: 60_000,
  });
}

export function useFundNav(codes: string) {
  return useQuery({
    queryKey: ["/api/connect/fund/nav", codes],
    queryFn: () =>
      api<{ items: FundNavItem[]; missing: string[]; note: string }>(
        `/api/connect/fund/nav?codes=${encodeURIComponent(codes)}`,
      ),
    enabled: codes.trim().length > 0,
    staleTime: 300_000,
  });
}

export function useIntents() {
  return useQuery({
    queryKey: ["/api/connect/intents"],
    queryFn: () => api<{ items: TradeIntent[] }>("/api/connect/intents").then((r) => r.items ?? []),
    staleTime: 10_000,
  });
}

export function useJobs() {
  return useQuery({
    queryKey: ["/api/connect/jobs"],
    queryFn: () =>
      api<{ items: SyncResult[] }>("/api/connect/jobs").then((r) => r.items ?? []),
    staleTime: 10_000,
  });
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

function useInvalidate() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["/api/connect/catalog"] });
    void qc.invalidateQueries({ queryKey: ["/api/connect/jobs"] });
    void qc.invalidateQueries({ queryKey: ["/api/connect/intents"] });
  };
}

export function useCreateConnection() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { connector_id: string; label?: string; account_ref?: string; meta?: Record<string, unknown> }) =>
      api<Connection>("/api/connect/connections", { method: "POST", body: JSON.stringify(body) }),
    onSettled: invalidate,
  });
}

export function useUpdateConnection() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, ...patch }: { id: string } & Partial<Pick<Connection, "status" | "label" | "account_ref">>) =>
      api<Connection>(`/api/connect/connections/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
    onSettled: invalidate,
  });
}

export function useDeleteConnection() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => api(`/api/connect/connections/${id}`, { method: "DELETE" }),
    onSettled: invalidate,
  });
}

export function useSyncConnection() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) =>
      api<SyncResult>(`/api/connect/connections/${id}/sync`, {
        method: "POST",
        body: JSON.stringify({ lang: navigator.language.startsWith("zh") ? "zh" : "en" }),
      }),
    onSettled: invalidate,
  });
}

export function useSyncAll() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: () => api<{ items: SyncResult[]; count: number }>("/api/connect/sync-all", { method: "POST" }),
    onSettled: invalidate,
  });
}

export function useBookmarklet() {
  return useMutation({
    mutationFn: ({ cid, lang }: { cid: string; lang: string }) =>
      api<{ pairing: Pairing; bookmarklet: string; ingest_endpoint: string; how_to: string }>(
        `/api/connect/pairing/${cid}/bookmarklet?lang=${lang === "en" ? "en" : "zh"}`,
      ),
  });
}

export function useScanInbox() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: () =>
      api<{ ok: boolean; imported: number; message: string; files: Record<string, unknown>[] }>(
        "/api/connect/inbox/scan",
        { method: "POST" },
      ),
    onSettled: invalidate,
  });
}

export function useInboxInfo() {
  return useQuery({
    queryKey: ["/api/connect/inbox"],
    queryFn: () =>
      api<{ path: string; pending: { name: string; size: number }[]; done: string[] }>("/api/connect/inbox"),
    staleTime: 15_000,
  });
}

export function useCreateIntent() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: {
      connector_id?: string;
      symbol: string;
      name?: string;
      side: "buy" | "sell";
      price: number;
      shares: number;
      mode: "paper" | "live";
      note?: string;
    }) => api<TradeIntent>("/api/connect/intents", { method: "POST", body: JSON.stringify(body) }),
    onSettled: invalidate,
  });
}

export function useExecuteIntent() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, accountId }: { id: string; accountId?: string }) =>
      api<{ ok: boolean; error?: string; intent: TradeIntent; handoff?: Record<string, unknown>; fee?: number }>(
        `/api/connect/intents/${id}/execute`,
        { method: "POST", body: JSON.stringify({ account_id: accountId ?? "" }) },
      ),
    onSettled: invalidate,
  });
}

export function useRejectIntent() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) =>
      api<TradeIntent>(`/api/connect/intents/${id}/reject`, { method: "POST", body: JSON.stringify({}) }),
    onSettled: invalidate,
  });
}

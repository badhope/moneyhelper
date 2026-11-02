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

// ---------------------------------------------------------------------------
// v4.5 深化：市场温度 / 个股档案 / 预交易风控 / 条件单 / 发票 / 持仓对账
// ---------------------------------------------------------------------------

export interface Breadth {
  available: boolean;
  reason?: string;
  up?: number;
  down?: number;
  flat?: number;
  total?: number;
  limit_up?: number;
  limit_down?: number;
  strong?: number;
  up_ratio_pct?: number;
  temperature?: number;
  mood?: "hot" | "warm" | "neutral" | "cool" | "cold";
  checked_at?: string;
}

export interface StockProfile {
  symbol: string;
  name: string;
  price: number;
  change_pct: number | null;
  pe_ttm: number | null;
  pb: number | null;
  total_mv_yi: number | null;
  float_mv_yi: number | null;
  turnover_pct: number | null;
  volume_ratio: number | null;
  amplitude_pct: number | null;
  limit_up: number | null;
  limit_down: number | null;
  valuation: { pe_ttm: number | null; pb: number | null; total_mv_yi: number | null; float_mv_yi: number | null; pe_note: string };
  activity: { turnover_pct: number | null; volume_ratio: number | null; amplitude_pct: number | null; amount_wan: number | null };
  source: string;
}

export interface RiskSettings {
  daily_limit: number;
  deviation_pct: number;
  concentration_pct: number;
  auto_execute_paper: number;
  updated_at?: string;
}

export interface RiskCheckItem {
  id: string;
  ok: boolean;
  level: "block" | "warn" | "info";
  detail: string;
}

export interface RiskCheckResult {
  ok: boolean;
  amount: number;
  blocking: RiskCheckItem[];
  warnings: RiskCheckItem[];
  checks: RiskCheckItem[];
  summary: string;
  quote?: { price: number | null; prev_close: number | null; name: string };
  available_cash?: number;
  portfolio_value?: number;
  daily_used?: number;
}

export interface ConditionalOrder {
  id: string;
  symbol: string;
  name: string;
  side: "buy" | "sell";
  trigger_type: "price_below" | "price_above" | "pct_change_below" | "pct_change_above";
  trigger_value: number;
  price: number;
  shares: number;
  mode: "paper" | "live";
  status: "watching" | "triggered" | "cancelled" | "expired";
  note: string;
  triggered_at: string;
  created_at: string;
}

export interface InvoiceRecord {
  id: string;
  file_name: string;
  source_format: string;
  invoice_code: string;
  invoice_number: string;
  invoice_date: string;
  buyer: string;
  seller: string;
  item: string;
  total_amount: number | null;
  tax_amount: number | null;
  tax_rate: string;
  kind: string;
  confidence: string;
  status: string;
  created_at: string;
}

export interface InvoiceSummary {
  count: number;
  total_amount: number;
  total_tax: number;
  pending: number;
  by_month: { month: string; amount: number }[];
}

export function useBreadth() {
  return useQuery({
    queryKey: ["/api/connect/market/breadth"],
    queryFn: () => api<Breadth>("/api/connect/market/breadth"),
    staleTime: 60_000,
  });
}

export function useStockProfile(symbol: string | null) {
  return useQuery({
    queryKey: ["/api/connect/stock/profile", symbol],
    queryFn: () => api<StockProfile>(`/api/connect/stock/${encodeURIComponent(symbol ?? "")}/profile`),
    enabled: Boolean(symbol && /^\d{6}$/.test(symbol)),
    staleTime: 20_000,
    retry: false,
  });
}

export function useRiskSettings() {
  return useQuery({
    queryKey: ["/api/connect/risk/settings"],
    queryFn: () => api<RiskSettings>("/api/connect/risk/settings"),
    staleTime: 60_000,
  });
}

export function useSaveRiskSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<RiskSettings>) =>
      api<RiskSettings>("/api/connect/risk/settings", { method: "PUT", body: JSON.stringify(body) }),
    onSettled: () => void qc.invalidateQueries({ queryKey: ["/api/connect/risk/settings"] }),
  });
}

export function useRiskCheck() {
  return useMutation({
    mutationFn: (body: { symbol: string; side: string; price: number; shares: number }) =>
      api<RiskCheckResult>("/api/connect/risk/check", { method: "POST", body: JSON.stringify(body) }),
  });
}

export function useConditionals() {
  return useQuery({
    queryKey: ["/api/connect/conditionals"],
    queryFn: () =>
      api<{ items: ConditionalOrder[] }>("/api/connect/conditionals").then((r) => r.items ?? []),
    staleTime: 30_000,
  });
}

export function useCreateConditional() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      symbol: string;
      side: "buy" | "sell";
      trigger_type: string;
      trigger_value: number;
      price: number;
      shares: number;
      mode: "paper" | "live";
      name?: string;
    }) => api<ConditionalOrder>("/api/connect/conditionals", { method: "POST", body: JSON.stringify(body) }),
    onSettled: () => void qc.invalidateQueries({ queryKey: ["/api/connect/conditionals"] }),
  });
}

export function useEvaluateConditionals() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api<{ checked: number; triggered: unknown[]; quotes_available: number }>(
        "/api/connect/conditionals/evaluate",
        { method: "POST" },
      ),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["/api/connect/conditionals"] });
      void qc.invalidateQueries({ queryKey: ["/api/connect/intents"] });
    },
  });
}

export function useDeleteConditional() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api(`/api/connect/conditionals/${id}`, { method: "DELETE" }),
    onSettled: () => void qc.invalidateQueries({ queryKey: ["/api/connect/conditionals"] }),
  });
}

export function useInvoices() {
  return useQuery({
    queryKey: ["/api/connect/invoices"],
    queryFn: () =>
      api<{ items: InvoiceRecord[]; summary: InvoiceSummary }>("/api/connect/invoices"),
    staleTime: 30_000,
  });
}

export function useUploadInvoiceText() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { text: string; file_name?: string }) =>
      api<{ ok: boolean; invoice: InvoiceRecord; parsed: Record<string, unknown>; duplicate: boolean }>(
        "/api/connect/invoices/text",
        { method: "POST", body: JSON.stringify(body) },
      ),
    onSettled: () => void qc.invalidateQueries({ queryKey: ["/api/connect/invoices"] }),
  });
}

export function useDeleteInvoice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api(`/api/connect/invoices/${id}`, { method: "DELETE" }),
    onSettled: () => void qc.invalidateQueries({ queryKey: ["/api/connect/invoices"] }),
  });
}

export interface HoldingsImportResult {
  ok: boolean;
  account: string;
  positions: {
    symbol: string;
    name: string;
    shares: number;
    cost: number;
    last: number;
    kind: string;
    market_value: number | null;
    pnl: number | null;
  }[];
  count: number;
  skipped: number;
  warnings: string[];
  applied?: number;
  errors?: string[];
}

export function useImportHoldings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { content: string; apply?: boolean; file_name?: string }) =>
      api<HoldingsImportResult>("/api/connect/import/holdings", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

// ---------------------------------------------------------------------------
// v4.6 攻坚：发票图片识别 / PDF 对账单 / 规则归类 / 券商执行层
// ---------------------------------------------------------------------------

export interface VisionStatus {
  qr: { available: boolean; decoders: string[] };
  ocr: { available: boolean; engines: string[]; note: string };
  pdf_tables: { available: boolean; note: string };
  hint: string;
}

export interface BrokerAdapterInfo {
  id: string;
  name: string;
  available: boolean;
  supports_trading: boolean;
  problems?: string[];
  note: string;
}

export interface ExecuteStatus {
  guardrails: {
    trading_enabled: boolean;
    dry_run: boolean;
    broker: string;
    max_order_amount: number;
    max_daily_amount: number;
    max_position_ratio: number;
    confirmation_ttl_seconds: number;
  };
  adapters: BrokerAdapterInfo[];
  current: BrokerAdapterInfo | null;
  note: string;
}

export interface CategorizeResult {
  results: Record<string, unknown>[];
  total: number;
  fallback: number;
  fallback_pct: number;
  by_category: Record<string, number>;
  by_rule: Record<string, number>;
  rule_count: number;
  hint: string;
}

export interface StatementPreview {
  ok: boolean;
  rows: { date: string; item: string; amount: number; category: string }[];
  count: number;
  method: string;
  pages: number;
  warnings: string[];
  imported?: number;
  duplicated?: number;
}

export function useVisionStatus() {
  return useQuery({
    queryKey: ["/api/connect/invoices/vision/status"],
    queryFn: () => api<VisionStatus>("/api/connect/invoices/vision/status"),
    staleTime: 120_000,
  });
}

export function useExecuteStatus() {
  return useQuery({
    queryKey: ["/api/execute/status"],
    queryFn: () => api<ExecuteStatus>("/api/execute/status"),
    staleTime: 30_000,
  });
}

export function useUploadInvoiceImage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.append("file", file);
      // FormData 由浏览器自带 boundary；api() 已处理不覆盖 Content-Type
      return api<{
        ok: boolean;
        method: string;
        invoice?: Record<string, unknown>;
        parsed?: Record<string, unknown>;
        warnings?: string[];
        install_hint?: string;
        duplicate?: boolean;
      }>("/api/connect/invoices/image", { method: "POST", body });
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["/api/connect/invoices"] }),
  });
}

export function useUploadStatementPdf() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ file, apply }: { file: File; apply: boolean }) => {
      const body = new FormData();
      body.append("file", file);
      if (apply) body.append("apply", "true");
      return api<StatementPreview>("/api/connect/import/statement-pdf", { method: "POST", body });
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["dashboard"] }),
  });
}

export function useCategorizePreview() {
  return useMutation({
    mutationFn: (rows: Record<string, unknown>[]) =>
      api<CategorizeResult>("/api/connect/categorize/preview", {
        method: "POST",
        body: JSON.stringify({ rows }),
      }),
  });
}

export function useApplyCategorize() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api<{ ok: boolean; changed: number; total: number; errors: string[] }>(
        "/api/connect/categorize/apply",
        { method: "POST", body: JSON.stringify({}) },
      ),
    onSettled: () => void qc.invalidateQueries({ queryKey: ["dashboard"] }),
  });
}

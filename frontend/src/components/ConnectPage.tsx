/** 连接中心：把「外部平台」变成「一条连接」。
 *
 * 页面结构（按用户实际动手顺序）：
 *   1. 顶部：能自动接的（公开源）直接连；需要登录的给配对码与官方入口
 *   2. 行情直连：指数 / 涨跌榜 / 基金净值，全部免登录实时拉
 *   3. 连接器目录：按分类分组，每个平台标明「怎么连、你能少做多少事」
 *   4. 账单收件箱：官方导出 CSV 丢进去，自动解析入账
 *   5. 交易指令：模拟盘直接成交；实盘生成交接单跳券商
 *
 * 设计原则：所有外部失败都显示原因与替代路径，不显示 0 也不留空白。
 */

import { useMemo, useState } from "react";
import {
  ArrowRight,
  BadgeCheck,
  Banknote,
  CheckCircle2,
  ClipboardCopy,
  Cloud,
  ExternalLink,
  FileSpreadsheet,
  FolderOpen,
  Globe2,
  Inbox,
  Landmark,
  Link2,
  Loader2,
  Plug,
  RefreshCw,
  ScanLine,
  ShieldCheck,
  Sparkles,
  Trash2,
  TrendingUp,
  Unplug,
  Wallet,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { PillTabs } from "@/components/ui/pill-tabs";
import { Segmented } from "@/components/ui/segmented";
import {
  BreadthCard,
  BrokerConfigCard,
  ConditionalCard,
  ExecuteStatusCard,
  HoldingsImportCard,
  InvoiceCard,
  PdfStatementCard,
  PretradeCard,
  RecategorizeCard,
  RiskSettingsCard,
  StockProfileCard,
} from "@/components/ConnectDeepPanels";
import { useI18n } from "@/lib/i18n";
import { copyText } from "@/lib/clipboard";
import { useToast } from "@/lib/toast";
import { fmtMoney, fmtPct, pnlClass } from "@/lib/format";
import { cn, errMsg } from "@/lib/utils";
import {
  useBookmarklet,
  useCatalog,
  useCreateConnection,
  useCreateIntent,
  useDeleteConnection,
  useExecuteIntent,
  useFundNav,
  useIndices,
  useInboxInfo,
  useIntents,
  useMovers,
  useRejectIntent,
  useScanInbox,
  useSourceStatus,
  useSyncAll,
  useSyncConnection,
  type Connector,
  type Connection,
  type ControlTier,
  type MoverItem,
  type TradeIntent,
} from "@/lib/use-connect";

const KIND_ICON: Record<string, typeof Globe2> = {
  public_api: Globe2,
  deep_link: ExternalLink,
  browser_login: Link2,
  file_import: FileSpreadsheet,
};

const CATEGORY_ICON: Record<string, typeof Wallet> = {
  market: TrendingUp,
  broker: Banknote,
  fund: Sparkles,
  bank: Landmark,
  pay: Wallet,
  invoice: FileSpreadsheet,
  company: Cloud,
};

const STATUS_STYLE: Record<string, string> = {
  connected: "ok",
  unconfigured: "muted",
  expiring: "warn",
  error: "danger",
  disabled: "muted",
};

/** 控制级别的视觉语义：只读是中性，导入/回传是蓝色，逐笔确认是琥珀色。
 *  没有任何“全自动转账”级别——不存在的权限不画成绿色。 */
const CONTROL_STYLE: Record<ControlTier, string> = {
  read: "border-border bg-muted/40 text-muted-foreground",
  import: "border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300",
  handoff: "border-indigo-500/30 bg-indigo-500/10 text-indigo-700 dark:text-indigo-300",
  manual: "border-border bg-muted/40 text-muted-foreground",
  confirm: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
};

function ConnectorCard({
  item,
  onCreate,
  onSync,
  onDelete,
  onPair,
  busy,
}: {
  item: Connector;
  onCreate: (item: Connector) => void;
  onSync: (conn: Connection) => void;
  onDelete: (conn: Connection) => void;
  onPair: (item: Connector) => void;
  busy: boolean;
}) {
  const { t } = useI18n();
  const Icon = CATEGORY_ICON[item.category] ?? Plug;
  const Kind = KIND_ICON[item.kind] ?? Globe2;
  const auto = item.automation === "auto";

  return (
    <div className="flex h-full flex-col rounded-[var(--radius)] border border-border/70 bg-card p-3">
      <div className="flex items-start gap-2">
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-[13.5px] font-semibold">{item.name}</span>
            <Badge variant={auto ? "ok" : item.automation === "semi" ? "warn" : "muted"} className="shrink-0 px-1.5 py-0 text-[10px]">
              {t(`connect.auto.${item.automation}`)}
            </Badge>
            <span
              className={cn(
                "shrink-0 rounded-full border px-1.5 py-0 text-[10px]",
                CONTROL_STYLE[item.control],
              )}
              title={t(`connect.controlHint.${item.control}`)}
            >
              {t(`connect.control.${item.control}`)}
            </span>
          </div>
          <div className="mt-0.5 flex items-center gap-1 text-[11px] text-muted-foreground">
            <Kind className="h-3 w-3" />
            {t(`connect.kind.${item.kind}`)}
            {item.supports_trade ? (
              <span className="ml-1 inline-flex items-center gap-0.5 text-amber-600 dark:text-amber-400">
                <ShieldCheck className="h-3 w-3" />
                {t("connect.tradeCapable")}
              </span>
            ) : null}
          </div>
        </div>
      </div>

      <p className="mt-2 line-clamp-2 text-[11.5px] leading-relaxed text-muted-foreground">{item.note}</p>

      <div className="mt-2 flex flex-wrap gap-1">
        {item.capabilities.map((c) => (
          <span key={c} className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
            {t(`connect.cap.${c}`)}
          </span>
        ))}
      </div>

      {item.connections.length > 0 && (
        <div className="mt-2 space-y-1.5 border-t border-border/60 pt-2">
          {item.connections.map((conn) => (
            <div key={conn.id} className="flex items-center gap-1.5 text-[11.5px]">
              <span className="min-w-0 flex-1 truncate">
                {conn.label}
                {conn.account_ref ? <span className="text-muted-foreground"> · {conn.account_ref}</span> : null}
              </span>
              <Badge variant={STATUS_STYLE[conn.status] as "ok" | "muted" | "warn" | "danger"} className="px-1.5 py-0 text-[10px]">
                {t(`connect.status.${conn.status}`)}
              </Badge>
              <button
                type="button"
                aria-label={t("connect.sync")}
                disabled={busy}
                onClick={() => onSync(conn)}
                className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50"
              >
                <RefreshCw className={cn("h-3.5 w-3.5", busy && "animate-spin")} />
              </button>
              <button
                type="button"
                aria-label={t("connect.remove")}
                onClick={() => onDelete(conn)}
                className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-down"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
          {item.connections.some((c) => c.last_error) && (
            <div className="truncate text-[10.5px] text-down">
              {item.connections.find((c) => c.last_error)?.last_error}
            </div>
          )}
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-1.5 pt-1">
        <Button size="sm" variant={auto ? "default" : "outline"} disabled={busy} onClick={() => onCreate(item)}>
          {auto ? t("connect.connect") : t("connect.addAccount")}
        </Button>
        {item.kind === "browser_login" && (
          <Button size="sm" variant="ghost" onClick={() => onPair(item)}>
            <Link2 className="mr-1 h-3.5 w-3.5" />
            {t("connect.pair")}
          </Button>
        )}
        {(item.login_url || item.data_url) && (
          <a
            href={item.login_url || item.data_url}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-0.5 text-[11.5px] text-primary hover:underline"
          >
            {t("connect.openSite")}
            <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
    </div>
  );
}

const CONTROL_TIERS: ControlTier[] = ["read", "import", "handoff", "manual", "confirm"];

/** 账号接入的总说明：能接什么、接到什么程度、哪些动作永远不会交给模型。
 *  这张卡不是权限开关，权限仍由连接器 kind/supports_trade 决定；它只把真实边界说清楚。 */
function AccountGatewayCard({
  counts,
  total,
}: {
  counts?: Record<ControlTier, number>;
  total: number;
}) {
  const { t } = useI18n();
  const icon: Record<ControlTier, typeof ShieldCheck> = {
    read: ShieldCheck,
    import: FileSpreadsheet,
    handoff: Link2,
    manual: ExternalLink,
    confirm: CheckCircle2,
  };
  const tint: Record<ControlTier, string> = {
    read: "text-emerald-600 dark:text-emerald-400",
    import: "text-sky-600 dark:text-sky-400",
    handoff: "text-indigo-600 dark:text-indigo-400",
    manual: "text-muted-foreground",
    confirm: "text-amber-600 dark:text-amber-400",
  };
  return (
    <Card className="border-primary/25 bg-primary/[0.025] p-[var(--card-pad)]">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-[13px] font-semibold">
            <ShieldCheck className="h-4 w-4 text-primary" />
            {t("connect.accountTitle")}
          </div>
          <p className="mt-1 max-w-3xl text-[11.5px] leading-relaxed text-muted-foreground">
            {t("connect.accountDesc")}
          </p>
        </div>
        <span className="rounded-full border border-border bg-card px-2 py-0.5 text-[10px] text-muted-foreground">
          {t("connect.accountBadge")}
        </span>
      </div>

      <div className="mt-2.5 grid grid-cols-2 gap-1.5 sm:grid-cols-5">
        {CONTROL_TIERS.map((tier) => {
          const Icon = icon[tier];
          const n = counts?.[tier] ?? 0;
          return (
            <div key={tier} className="rounded-lg border border-border/70 bg-card px-2 py-1.5">
              <div className="flex items-center gap-1 text-[10.5px] font-medium">
                <Icon className={cn("h-3 w-3", tint[tier])} />
                <span>{t(`connect.control.${tier}`)}</span>
                <span className="ml-auto tabular-nums text-muted-foreground">{n}</span>
              </div>
              <div className="mt-0.5 truncate text-[9.5px] text-muted-foreground/80">
                {t(`connect.controlHint.${tier}`)}
              </div>
            </div>
          );
        })}
      </div>

      <p className="mt-2 border-t border-border/60 pt-2 text-[10.5px] leading-relaxed text-muted-foreground">
        {t("connect.accountSafety", { total })}
      </p>
    </Card>
  );
}

function IntentRow({
  intent,
  onExecute,
  onReject,
  busy,
}: {
  intent: TradeIntent;
  onExecute: (i: TradeIntent) => void;
  onReject: (i: TradeIntent) => void;
  busy: boolean;
}) {
  const { t } = useI18n();
  const done = intent.status === "executed";
  const rejected = intent.status === "rejected";
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-border/50 py-2 text-[12px] last:border-0">
      <span className={cn("rounded px-1.5 py-0.5 text-[10px]", intent.side === "buy" ? "bg-red-500/10 text-up" : "bg-emerald-500/10 text-down")}>
        {t(intent.side === "buy" ? "connect.buy" : "connect.sell")}
      </span>
      <span className="font-medium">{intent.name || intent.symbol}</span>
      <span className="text-muted-foreground">{intent.symbol}</span>
      <span className="tabular-nums">{fmtMoney(intent.price)} × {intent.shares}</span>
      <span className="tabular-nums text-muted-foreground">{fmtMoney(intent.amount)}</span>
      <Badge variant={intent.mode === "live" ? "warn" : "muted"} className="px-1.5 py-0 text-[10px]">
        {intent.mode === "live" ? t("connect.modeLive") : t("connect.modePaper")}
      </Badge>
      <Badge variant={done ? "ok" : rejected ? "danger" : "outline"} className="px-1.5 py-0 text-[10px]">
        {t(`connect.intent.${intent.status}`)}
      </Badge>
      <span className="ml-auto flex items-center gap-1.5">
        {!done && !rejected && (
          <>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => onExecute(intent)}>
              {intent.mode === "live" ? t("connect.handoff") : t("connect.execute")}
            </Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => onReject(intent)}>
              {t("connect.cancel")}
            </Button>
          </>
        )}
        {done && intent.result?.handoff_url ? (
          <a className="text-[11.5px] text-primary hover:underline" href={String(intent.result.handoff_url)} target="_blank" rel="noreferrer noopener">
            {t("connect.openBroker")}
          </a>
        ) : null}
      </span>
    </div>
  );
}

/** 涨跌幅可视化：以 0 为中心向两侧生长的横条，长度按当前榜单最大绝对值归一。
 *  表格只给数字，扫不出"谁强谁弱"；横条能让人在几秒内完成强弱排序感知。 */
function MoverBars({ items }: { items: MoverItem[] }) {
  const { t } = useI18n();
  const maxAbs = Math.max(1, ...items.map((m) => Math.abs(m.change_pct ?? 0)));
  return (
    <div className="space-y-1">
      {items.map((m) => {
        const pct = m.change_pct ?? 0;
        const width = Math.min(50, (Math.abs(pct) / maxAbs) * 50);
        return (
          <div
            key={m.symbol}
            className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-md px-1.5 py-1.5 transition-colors hover:bg-muted/30"
          >
            <div className="flex min-w-0 items-center gap-2">
              <span className={cn("h-7 w-1 shrink-0 rounded-full bg-current", pnlClass(pct))} />
              <div className="min-w-0">
                <div className="flex min-w-0 items-baseline gap-1.5">
                  <span className="truncate text-[12.5px] font-medium">{m.name}</span>
                  <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">{m.symbol}</span>
                </div>
                <div className="truncate text-[10.5px] text-muted-foreground">
                  {t("connect.colPrice")} <span className="tabular-nums text-foreground/80">{m.price ?? "-"}</span>
                  {m.amount != null && (
                    <> · {t("connect.colAmount")} <span className="tabular-nums">{fmtMoney(m.amount, false, true)}</span></>
                  )}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <div className="relative h-2 w-16 overflow-hidden rounded-full bg-muted sm:w-32">
                <span className="absolute inset-y-0 left-1/2 w-px bg-border" />
                <span
                  className={cn("absolute inset-y-0 rounded-full bg-current", pnlClass(pct))}
                  style={{ left: pct >= 0 ? "50%" : undefined, right: pct < 0 ? "50%" : undefined, width: `${width}%` }}
                />
              </div>
              <span className={cn("w-14 text-right text-[11.5px] tabular-nums", pnlClass(pct))}>{fmtPct(pct, true)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function ConnectPage() {
  const { t, lang } = useI18n();
  const { toast } = useToast();
  const catalogQuery = useCatalog();
  const statusQuery = useSourceStatus();
  const inboxQuery = useInboxInfo();
  const intentsQuery = useIntents();
  const indicesQuery = useIndices();

  const [tab, setTab] = useState<"sources" | "connectors" | "inbox" | "orders" | "research" | "trade" | "invoice">("sources");
  const [moverKind, setMoverKind] = useState<"gainers" | "losers" | "turnover">("gainers");
  const moversQuery = useMovers(moverKind);
  const [fundCodes, setFundCodes] = useState("110011");
  const fundQuery = useFundNav(fundCodes);

  const [pendingDeleteConn, setPendingDeleteConn] = useState<Connection | null>(null);
  const [pairInfo, setPairInfo] = useState<{ title: string; code?: string; bookmarklet?: string; login_url?: string; how_to?: string } | null>(null);
  const [draft, setDraft] = useState({
    symbol: "",
    name: "",
    side: "buy" as "buy" | "sell",
    price: "",
    shares: "",
    mode: "paper" as "paper" | "live",
    connector_id: "",
  });

  const createConn = useCreateConnection();
  const deleteConn = useDeleteConnection();
  const syncConn = useSyncConnection();
  const syncAll = useSyncAll();
  const scanInbox = useScanInbox();
  const createIntent = useCreateIntent();
  const executeIntent = useExecuteIntent();
  const rejectIntent = useRejectIntent();
  const bookmarklet = useBookmarklet();

  const catalog = catalogQuery.data;
  const busy = createConn.isPending || syncConn.isPending || syncAll.isPending || deleteConn.isPending;

  const connectedCount = catalog?.connections.length ?? 0;
  const autoCount = catalog?.counts.auto ?? 0;
  const total = catalog?.counts.total ?? 0;

  const sourceStatus = statusQuery.data?.items ?? [];
  const sourceOk = sourceStatus.filter((s) => s.ok).length;

  const openIntents = useMemo(
    () => (intentsQuery.data ?? []).filter((i) => i.status !== "executed" && i.status !== "rejected"),
    [intentsQuery.data],
  );

  const doCreate = async (item: Connector) => {
    try {
      await createConn.mutateAsync({ connector_id: item.id, label: item.name });
      toast(t("connect.created", { name: item.name }), "ok");
      if (item.automation === "auto") {
        // 公开源建好即同步一次，用户不用再点
        void syncAll.mutateAsync().catch(() => undefined);
      }
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };

  const doSync = async (conn: Connection) => {
    try {
      const res = await syncConn.mutateAsync(conn.id);
      if (res?.pairing) {
        setPairInfo({
          title: conn.label,
          code: res.pairing.code,
          bookmarklet: res.bookmarklet,
          login_url: res.login_url || res.pairing.login_url,
          how_to: String(res.message ?? ""),
        });
        toast(t("connect.pairReady"), "ok");
      } else if (res?.ok === false) {
        toast(String(res.message ?? t("connect.syncFail")), "error");
      } else {
        toast(t("connect.syncOk"), "ok");
      }
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };

  const doPair = async (item: Connector) => {
    try {
      const res = await bookmarklet.mutateAsync({ cid: item.id, lang });
      setPairInfo({
        title: item.name,
        code: res.pairing.code,
        bookmarklet: res.bookmarklet,
        login_url: res.pairing.login_url,
        how_to: res.how_to,
      });
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };

  const doDelete = async (conn: Connection) => {
    try {
      await deleteConn.mutateAsync(conn.id);
      toast(t("connect.removed"), "ok");
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };

  const doScan = async () => {
    try {
      const res = await scanInbox.mutateAsync();
      toast(res.message || t("connect.inboxScanned", { n: res.imported }), res.imported > 0 ? "ok" : "info");
      void inboxQuery.refetch();
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };

  const doCreateIntent = async () => {
    const price = Number(draft.price);
    const shares = Number(draft.shares);
    if (!draft.symbol.trim() || !price || !shares) {
      toast(t("connect.fillRequired"), "error");
      return;
    }
    try {
      await createIntent.mutateAsync({
        connector_id: draft.connector_id || undefined,
        symbol: draft.symbol.trim(),
        name: draft.name.trim(),
        side: draft.side,
        price,
        shares,
        mode: draft.mode,
      });
      toast(t("connect.intentCreated"), "ok");
      setDraft({ ...draft, symbol: "", name: "", price: "", shares: "" });
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };

  const doExecute = async (intent: TradeIntent) => {
    try {
      const res = await executeIntent.mutateAsync({ id: intent.id });
      if (!res.ok) {
        toast(res.error || t("connect.execFail"), "error");
        return;
      }
      if (res.handoff) {
        toast(t("connect.handoffReady"), "ok");
        const url = String(res.handoff.handoff_url || "");
        if (url) window.open(url, "_blank", "noopener,noreferrer");
      } else {
        toast(t("connect.execOk", { fee: res.fee != null ? fmtMoney(res.fee) : "-" }), "ok");
      }
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };

  const doReject = async (intent: TradeIntent) => {
    try {
      await rejectIntent.mutateAsync(intent.id);
      toast(t("connect.intentRejected"), "info");
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };

  if (catalogQuery.isPending) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-20 w-full rounded-[var(--radius)]" />
        <Skeleton className="h-40 w-full rounded-[var(--radius)]" />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* 顶部：一句话说明能自动到什么程度 */}
      <Card className="p-[var(--card-pad)]">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5 text-[13.5px] font-semibold">
              <Plug className="h-4 w-4 text-primary" />
              {t("connect.title")}
            </div>
            <p className="mt-1 max-w-3xl text-[12px] leading-relaxed text-muted-foreground">
              {t("connect.intro")}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="rounded-lg bg-muted/40 px-2.5 py-1.5 text-[11px]">
              <span className="text-muted-foreground">{t("connect.statSources")}</span>{" "}
              <span className="font-semibold tabular-nums">{sourceOk}/{sourceStatus.length || 3}</span>
            </div>
            <div className="rounded-lg bg-muted/40 px-2.5 py-1.5 text-[11px]">
              <span className="text-muted-foreground">{t("connect.statConnected")}</span>{" "}
              <span className="font-semibold tabular-nums">{connectedCount}/{total}</span>
            </div>
            <div className="rounded-lg bg-muted/40 px-2.5 py-1.5 text-[11px]">
              <span className="text-muted-foreground">{t("connect.statAuto")}</span>{" "}
              <span className="font-semibold tabular-nums">{autoCount}</span>
            </div>
            <Button size="sm" variant="outline" onClick={() => setTab("connectors")}>
              <Plug className="mr-1 h-3.5 w-3.5" />
              {t("connect.openAccounts")}
            </Button>
            <Button size="sm" variant="outline" disabled={syncAll.isPending} onClick={() => void syncAll.mutateAsync().then(() => toast(t("connect.syncOk"), "ok")).catch((e) => toast(errMsg(e), "error"))}>
              <RefreshCw className={cn("mr-1 h-3.5 w-3.5", syncAll.isPending && "animate-spin")} />
              {t("connect.syncAll")}
            </Button>
          </div>
        </div>

        <div className="mt-3">
          <PillTabs
            value={tab}
            onChange={setTab}
            size="sm"
            options={[
              { value: "sources", label: t("connect.tabSources") },
              { value: "connectors", label: t("connect.tabConnectors") },
              { value: "inbox", label: t("connect.tabInbox") },
              { value: "orders", label: t("connect.tabOrders") },
              { value: "research", label: t("connect.tabResearch") },
              { value: "trade", label: t("connect.tabTrade") },
              { value: "invoice", label: t("connect.tabInvoice") },
            ]}
          />
        </div>
      </Card>

      {/* 配对码面板：需要登录的平台在这里一次拿走入口 + 回传手段 */}
      {pairInfo && (
        <Card className="border-primary/30 bg-primary/[0.04] p-[var(--card-pad)]">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 text-[13px] font-semibold">
                <ShieldCheck className="h-4 w-4 text-primary" />
                {t("connect.pairTitle", { name: pairInfo.title })}
              </div>
              <p className="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">{pairInfo.how_to || t("connect.pairHint")}</p>
            </div>
            <Button size="sm" variant="ghost" onClick={() => setPairInfo(null)}>
              {t("connect.close")}
            </Button>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {pairInfo.code && (
              <span className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1.5 font-mono text-[13px] tracking-wider">
                {pairInfo.code}
                <button
                  type="button"
                  aria-label={t("connect.copy")}
                  onClick={() => {
                    if (copyText(pairInfo.code ?? "")) toast(t("connect.copied"), "ok");
                  }}
                  className="text-muted-foreground hover:text-foreground"
                >
                  <ClipboardCopy className="h-3.5 w-3.5" />
                </button>
              </span>
            )}
            {pairInfo.login_url && (
              <a
                href={pairInfo.login_url}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-[12px] hover:bg-accent"
              >
                {t("connect.openLogin")}
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}
            {pairInfo.bookmarklet && (
              <button
                type="button"
                onClick={() => {
                  if (copyText(pairInfo.bookmarklet ?? "")) toast(t("connect.bookmarkletCopied"), "ok");
                }}
                className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-[12px] hover:bg-accent"
              >
                <Link2 className="h-3.5 w-3.5" />
                {t("connect.copyBookmarklet")}
              </button>
            )}
          </div>
          <p className="mt-2 text-[10.5px] leading-relaxed text-muted-foreground/80">{t("connect.pairSafety")}</p>
        </Card>
      )}

      {/* 1. 行情直连 */}
      {tab === "sources" && (
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_20rem]">
          {/* min-w-0：grid item 默认 min-width:auto，会被内部表格的固有宽度撑破卡片（实测手机端 table 398px > card 358px） */}
          <div className="min-w-0 space-y-3">
            <Card className="p-[var(--card-pad)]">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-1">
                <div className="text-[13px] font-semibold">{t("connect.indicesTitle")}</div>
                <span className="truncate text-[11px] text-muted-foreground">
                  {indicesQuery.data ? `${t("connect.source")}: ${indicesQuery.data.source}` : ""}
                </span>
              </div>
              {indicesQuery.data?.items?.length ? (
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {indicesQuery.data.items.map((i) => {
                    const pct = i.change_pct ?? 0;
                    const idxMax = Math.max(1, ...indicesQuery.data.items.map((x) => Math.abs(x.change_pct ?? 0)));
                    return (
                      <div key={i.symbol} className="rounded-lg bg-muted/25 px-2.5 py-2">
                        <div className="text-[11px] text-muted-foreground">{i.name}</div>
                        <div className="mt-0.5 text-base font-bold tabular-nums">
                          {i.price.toLocaleString(lang === "zh" ? "zh-CN" : "en-US", { maximumFractionDigits: 2 })}
                        </div>
                        <div className={cn("text-[11px] tabular-nums", pnlClass(pct))}>{fmtPct(pct, true)}</div>
                        <div className={cn("mt-1.5 h-1 overflow-hidden rounded-full bg-muted", pnlClass(pct))}>
                          <div className="h-full rounded-full bg-current" style={{ width: `${Math.min(100, (Math.abs(pct) / idxMax) * 100)}%` }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <EmptyState mode="compact" text={indicesQuery.data?.note || t("connect.noData")} />
              )}
            </Card>

            <Card className="p-[var(--card-pad)]">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <div className="text-[13px] font-semibold">{t("connect.moversTitle")}</div>
                <div className="flex max-w-full flex-wrap items-center gap-1.5">
                  <Segmented
                    size="sm"
                    value={moverKind}
                    onChange={setMoverKind}
                    options={[
                      { value: "gainers", label: t("connect.gainers") },
                      { value: "losers", label: t("connect.losers") },
                      { value: "turnover", label: t("connect.turnover") },
                    ]}
                  />
                  {moversQuery.data?.source ? (
                    <span className="text-[10.5px] text-muted-foreground">{moversQuery.data.source}</span>
                  ) : null}
                </div>
              </div>
              {moversQuery.isPending ? (
                <Skeleton className="h-24 w-full" />
              ) : moversQuery.data?.items?.length ? (
                <MoverBars items={moversQuery.data.items} />
              ) : (
                <EmptyState mode="compact" text={moversQuery.data?.note || t("connect.noData")} />
              )}
            </Card>

            <Card className="p-[var(--card-pad)]">
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="text-[13px] font-semibold">{t("connect.fundTitle")}</div>
                <input
                  value={fundCodes}
                  onChange={(e) => setFundCodes(e.target.value)}
                  placeholder="110011, 000001"
                  className="w-40 rounded-md border border-border bg-background px-2 py-1 text-[12px]"
                />
              </div>
              {fundQuery.isFetching ? (
                <Skeleton className="h-16 w-full" />
              ) : fundQuery.data?.items?.length ? (
                <div className="space-y-1.5">
                  {fundQuery.data.items.map((f) => (
                    <div key={f.code} className="flex items-center gap-2 text-[12px]">
                      <span className="min-w-0 flex-1 truncate font-medium">{f.name}</span>
                      <span className="text-muted-foreground">{f.code}</span>
                      <span className="tabular-nums">{f.nav}</span>
                      <span className={cn("w-16 text-right tabular-nums", pnlClass(f.change_pct))}>{fmtPct(f.change_pct, true)}</span>
                      <span className="w-20 text-right text-[10.5px] text-muted-foreground">{f.date}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState mode="compact" text={fundQuery.data?.note || t("connect.noData")} />
              )}
            </Card>
          </div>

          <Card className="h-fit p-[var(--card-pad)]">
            <div className="mb-2 flex items-center justify-between">
              <div className="text-[13px] font-semibold">{t("connect.statusTitle")}</div>
              <Button size="sm" variant="ghost" onClick={() => void statusQuery.refetch()}>
                <RefreshCw className={cn("h-3.5 w-3.5", statusQuery.isFetching && "animate-spin")} />
              </Button>
            </div>
            <div className="space-y-1.5">
              {sourceStatus.map((s) => (
                <div key={s.id} className="flex items-center gap-2 text-[12px]">
                  <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", s.ok ? "bg-emerald-500" : "bg-red-500")} />
                  <span className="min-w-0 flex-1 truncate">{t(`connect.src.${s.id}`)}</span>
                  <span className="truncate text-[10.5px] text-muted-foreground">{s.detail}</span>
                </div>
              ))}
            </div>
            <p className="mt-2 border-t border-border/60 pt-2 text-[10.5px] leading-relaxed text-muted-foreground">
              {t("connect.statusHint")}
            </p>
          </Card>
        </div>
      )}

      {/* 2. 连接器目录 */}
      {tab === "connectors" && (
        <div className="space-y-4">
          <AccountGatewayCard counts={catalog?.counts.control} total={total} />
          {(catalog?.groups ?? []).map((g) => (
            <div key={g.key}>
              <div className="mb-1.5 flex items-center gap-1.5 text-[12.5px] font-semibold text-foreground/85">
                {t(`connect.cat.${g.key}`)}
                <span className="text-[11px] font-normal text-muted-foreground">{g.items.length}</span>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                {g.items.map((item) => (
                  <ConnectorCard
                    key={item.id}
                    item={item}
                    busy={busy}
                    onCreate={(x) => void doCreate(x)}
                    onSync={(c) => void doSync(c)}
                    onDelete={(c) => setPendingDeleteConn(c)}
                    onPair={(x) => void doPair(x)}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 3. 收件箱 */}
      {tab === "inbox" && (
        <div className="grid gap-3 lg:grid-cols-2">
          <Card className="p-[var(--card-pad)]">
            <div className="flex items-center gap-1.5 text-[13px] font-semibold">
              <FolderOpen className="h-4 w-4 text-primary" />
              {t("connect.inboxTitle")}
            </div>
            <p className="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">{t("connect.inboxDesc")}</p>
            <div className="mt-2 rounded-lg bg-muted/40 px-2.5 py-2 font-mono text-[11px] break-all">
              {inboxQuery.data?.path ?? "backend/data/import-inbox"}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Button size="sm" disabled={scanInbox.isPending} onClick={() => void doScan()}>
                {scanInbox.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <ScanLine className="mr-1 h-3.5 w-3.5" />}
                {t("connect.scanNow")}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => void inboxQuery.refetch()}>
                <RefreshCw className="mr-1 h-3.5 w-3.5" />
                {t("connect.refresh")}
              </Button>
            </div>
            <div className="mt-3 text-[11.5px]">
              <div className="mb-1 text-muted-foreground">{t("connect.inboxPending", { n: inboxQuery.data?.pending.length ?? 0 })}</div>
              {(inboxQuery.data?.pending ?? []).map((f) => (
                <div key={f.name} className="flex items-center gap-2 border-t border-border/40 py-1">
                  <FileSpreadsheet className="h-3.5 w-3.5 text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate">{f.name}</span>
                  <span className="text-[10.5px] text-muted-foreground">{(f.size / 1024).toFixed(1)} KB</span>
                </div>
              ))}
              {(inboxQuery.data?.pending.length ?? 0) === 0 && (
                <div className="text-[11px] text-muted-foreground">{t("connect.inboxEmpty")}</div>
              )}
            </div>
          </Card>

          <Card className="p-[var(--card-pad)]">
            <div className="flex items-center gap-1.5 text-[13px] font-semibold">
              <Inbox className="h-4 w-4 text-primary" />
              {t("connect.inboxDoneTitle")}
            </div>
            <p className="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">{t("connect.inboxDoneDesc")}</p>
            <div className="mt-2 space-y-1">
              {(inboxQuery.data?.done ?? []).slice().reverse().map((f) => (
                <div key={f} className="flex items-center gap-2 border-b border-border/40 py-1 text-[11.5px] last:border-0">
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                  <span className="min-w-0 flex-1 truncate">{f}</span>
                </div>
              ))}
              {(inboxQuery.data?.done.length ?? 0) === 0 && (
                <div className="text-[11px] text-muted-foreground">{t("connect.inboxDoneEmpty")}</div>
              )}
            </div>
          </Card>
        </div>
      )}

      {/* 4. 交易指令 */}
      {tab === "orders" && (
        <div className="grid gap-3 lg:grid-cols-[22rem_minmax(0,1fr)]">
          <Card className="h-fit p-[var(--card-pad)]">
            <div className="flex items-center gap-1.5 text-[13px] font-semibold">
              <BadgeCheck className="h-4 w-4 text-primary" />
              {t("connect.newOrder")}
            </div>
            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{t("connect.orderHint")}</p>
            <div className="mt-2 space-y-2">
              <div className="flex gap-2">
                <input
                  value={draft.symbol}
                  onChange={(e) => setDraft({ ...draft, symbol: e.target.value })}
                  placeholder={t("connect.symbolPh")}
                  className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-[12px]"
                />
                <input
                  value={draft.name}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                  placeholder={t("connect.namePh")}
                  className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-[12px]"
                />
              </div>
              <div className="flex gap-2">
                <Segmented
                  size="sm"
                  value={draft.side}
                  onChange={(v) => setDraft({ ...draft, side: v })}
                  options={[
                    { value: "buy", label: t("connect.buy") },
                    { value: "sell", label: t("connect.sell") },
                  ]}
                />
                <Segmented
                  size="sm"
                  value={draft.mode}
                  onChange={(v) => setDraft({ ...draft, mode: v })}
                  options={[
                    { value: "paper", label: t("connect.modePaper") },
                    { value: "live", label: t("connect.modeLive") },
                  ]}
                />
              </div>
              <div className="flex gap-2">
                <input
                  value={draft.price}
                  onChange={(e) => setDraft({ ...draft, price: e.target.value })}
                  placeholder={t("connect.pricePh")}
                  inputMode="decimal"
                  className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-[12px]"
                />
                <input
                  value={draft.shares}
                  onChange={(e) => setDraft({ ...draft, shares: e.target.value })}
                  placeholder={t("connect.sharesPh")}
                  inputMode="numeric"
                  className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-[12px]"
                />
              </div>
              <Button size="sm" className="w-full" disabled={createIntent.isPending} onClick={() => void doCreateIntent()}>
                {t("connect.createIntent")}
              </Button>
            </div>
          </Card>

          <Card className="p-[var(--card-pad)]">
            <div className="mb-1 flex items-center justify-between">
              <div className="text-[13px] font-semibold">{t("connect.intentList")}</div>
              <span className="text-[11px] text-muted-foreground">
                {t("connect.pendingCount", { n: openIntents.length })}
              </span>
            </div>
            {(intentsQuery.data ?? []).length === 0 ? (
              <EmptyState mode="compact" text={t("connect.noIntents")} />
            ) : (
              <div>
                {(intentsQuery.data ?? []).map((i) => (
                  <IntentRow
                    key={i.id}
                    intent={i}
                    busy={executeIntent.isPending || rejectIntent.isPending}
                    onExecute={(x) => void doExecute(x)}
                    onReject={(x) => void doReject(x)}
                  />
                ))}
              </div>
            )}
            <p className="mt-2 border-t border-border/60 pt-2 text-[10.5px] leading-relaxed text-muted-foreground">
              {t("connect.orderSafety")}
            </p>
          </Card>
        </div>
      )}


      {/* 5. 投研深化：市场温度 + 个股档案 */}
      {tab === "research" && (
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="min-w-0 space-y-3">
            <BreadthCard />
            <StockProfileCard defaultSymbol="600519" />
          </div>
          <Card className="h-fit p-[var(--card-pad)]">
            <div className="text-[13px] font-semibold">{t("connect.researchHintTitle")}</div>
            <p className="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">
              {t("connect.researchHint")}
            </p>
            <div className="mt-2 space-y-1.5 text-[11.5px] text-muted-foreground">
              <div>· {t("connect.researchTip1")}</div>
              <div>· {t("connect.researchTip2")}</div>
              <div>· {t("connect.researchTip3")}</div>
            </div>
          </Card>
        </div>
      )}

      {/* 6. 交易深化：预交易检查 + 条件单 + 风控设置 */}
      {tab === "trade" && (
        <div className="grid gap-3 lg:grid-cols-[22rem_minmax(0,1fr)]">
          <div className="min-w-0 space-y-3">
            <PretradeCard />
            <RiskSettingsCard />
          </div>
          <ConditionalCard />
        </div>
      )}

      {/* 7. 发票与对账 */}
      {tab === "invoice" && (
        <div className="grid gap-3 lg:grid-cols-2">
          <InvoiceCard />
          <PdfStatementCard />
          <HoldingsImportCard />
          <div className="min-w-0 space-y-3">
            <BrokerConfigCard />
            <ExecuteStatusCard />
            <RecategorizeCard />
          </div>
        </div>
      )}

      {/* 底部：连接器目录统计 */}
      <div className="flex flex-wrap items-center gap-3 px-1 text-[10.5px] text-muted-foreground">
        <span>{t("connect.footKinds")}</span>
        <span>·</span>
        <span>{t("connect.footAuto", { n: catalog?.counts.auto ?? 0 })}</span>
        <span>·</span>
        <span>{t("connect.footSemi", { n: catalog?.counts.semi ?? 0 })}</span>
        <span>·</span>
        <span>{t("connect.footManual", { n: catalog?.counts.manual ?? 0 })}</span>
        <span className="ml-auto inline-flex items-center gap-1">
          <Unplug className="h-3 w-3" />
          {t("connect.footSafety")}
          <ArrowRight className="h-3 w-3" />
        </span>
      </div>

      <ConfirmDialog
        open={pendingDeleteConn !== null}
        onOpenChange={(v) => { if (!v) setPendingDeleteConn(null); }}
        title={t("connect.removeTitle", { name: pendingDeleteConn?.label ?? "" })}
        description={t("connect.removeDesc")}
        confirmText={t("connect.removeConfirm")}
        danger
        onConfirm={async () => {
          const target = pendingDeleteConn;
          setPendingDeleteConn(null);
          if (target) await doDelete(target);
        }}
      />
    </div>
  );
}

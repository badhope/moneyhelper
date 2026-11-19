import { useCallback, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LineChart, Plus, RefreshCw, Search, X } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { IndicesStrip } from "@/components/IndicesStrip";
import { MarketDetail } from "@/components/MarketDetail";
import { SparklineCell } from "@/components/SparklineCell";
import { KlineDialog } from "@/components/KlineDialog";
import { EmptyState } from "@/components/ui/empty-state";
import { PillTabs } from "@/components/ui/pill-tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { ConfirmDialog } from "@/components/ui/confirm";
import { useI18n } from "@/lib/i18n";
import { useDashboard } from "@/lib/store";
import { api } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { fmtMoney, fmtPct, pnlClass } from "@/lib/format";
import { cn, errMsg } from "@/lib/utils";

interface WatchItem {
  symbol: string;
  name: string;
  kind: string;
  price?: number;
  change?: number | null;
  change_pct?: number | null;
  quote_source?: string;
}

interface SearchHit {
  symbol: string;
  name: string;
  kind: string;
}

/** 行情页：大盘指数 + 自选（自己盯的标的，可搜索添加/删除，点行看 K 线）+ 持仓行情。 */
export function MarketView() {
  const { t } = useI18n();
  const { toast } = useToast();
  const { dashboard } = useDashboard();
  const [tab, setTab] = useState<"watch" | "holdings">("watch");
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [kline, setKline] = useState<{ symbol: string; name: string } | null>(null);
  const [removing, setRemoving] = useState<WatchItem | null>(null);
  // 右侧详情栏当前选中的标的（股票软件式「列表 + 详情」）
  const [selected, setSelected] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const watchQuery = useQuery({
    queryKey: ["/api/watchlist"],
    queryFn: () => api<{ items: WatchItem[] }>("/api/watchlist").then((r) => r.items ?? []),
  });
  const watch = watchQuery.data ?? [];
  const loading = watchQuery.isPending;

  const invalidateWatchlist = useCallback(
    () => queryClient.invalidateQueries({ queryKey: ["/api/watchlist"] }),
    [queryClient],
  );

  // 搜索防抖：停顿 300ms 才请求
  useEffect(() => {
    const kw = q.trim();
    if (!kw || tab !== "watch") {
      setHits([]);
      return;
    }
    setSearching(true);
    let alive = true;
    const timer = window.setTimeout(() => {
      api<{ items: SearchHit[] }>(`/api/search?q=${encodeURIComponent(kw)}`)
        .then((r) => { if (alive) setHits(r.items ?? []); })
        .catch(() => { if (alive) setHits([]); })
        .finally(() => { if (alive) setSearching(false); });
    }, 300);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [q, tab]);

  const add = async (hit: SearchHit) => {
    try {
      await api("/api/watchlist", { method: "POST", body: JSON.stringify(hit) });
      toast(t("market.added", { name: hit.name }), "ok");
      setQ("");
      setHits([]);
      invalidateWatchlist();
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };

  const remove = async (symbol: string) => {
    try {
      await api(`/api/watchlist/${encodeURIComponent(symbol)}`, { method: "DELETE" });
      invalidateWatchlist();
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };

  const holdings = (dashboard?.positions ?? []).filter((p) => p.kind !== "现金").sort((a, b) => b.market_value - a.market_value);

  const detailWatch = watch.find((w) => w.symbol === selected) ?? watch[0];
  const detailHolding = holdings.find((h) => h.symbol === selected) ?? holdings[0];

  // 骨架屏加载态：首次加载自选列表时展示占位
  if (loading && watch.length === 0) {
    return (
      <div className="space-y-3">
        <IndicesStrip indices={dashboard?.indices ?? []} />
        <Card className="p-[var(--card-pad)]">
          <div className="mb-2 flex items-center gap-1.5">
            <Skeleton className="h-6 w-16 rounded-full" />
            <Skeleton className="h-6 w-16 rounded-full" />
          </div>
          <div className="relative mb-3">
            <Skeleton className="h-9 w-full" />
          </div>
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="flex items-center justify-between">
                <div className="space-y-1.5">
                  <Skeleton className="h-4 w-24" />
                  <Skeleton className="h-3 w-16" />
                </div>
                <Skeleton className="h-4 w-32" />
              </div>
            ))}
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <IndicesStrip indices={dashboard?.indices ?? []} />

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_17rem]">
      <Card className="min-w-0 p-[var(--card-pad)]">
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <PillTabs
            value={tab}
            onChange={setTab}
            size="sm"
            options={[
              { value: "watch", label: t("market.watchlist") },
              { value: "holdings", label: t("market.holdingsTab") },
            ]}
          />
          {tab === "watch" && (
            <span className="ml-auto flex items-center gap-1.5">
              <span className="text-[11px] text-muted-foreground">{watch.length} {t("holdings.items")}</span>
              <Button variant="ghost" size="icon" className="h-7 w-7" aria-label={t("market.refresh")} onClick={() => void watchQuery.refetch()}>
                <RefreshCw className={cn("w-3.5 h-3.5", loading && "animate-spin")} />
              </Button>
            </span>
          )}
        </div>

        {tab === "watch" ? (
          <>
            {/* 搜索添加 */}
            <div className="relative mb-3">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
              <input
                type="search"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder={t("market.searchPh")}
                aria-label={t("market.searchPh")}
                className="w-full rounded-lg border border-input bg-background pl-8 pr-9 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring [&::-webkit-search-cancel-button]:appearance-none"
                maxLength={20}
              />
              {q && (
                <button type="button" className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground" onClick={() => { setQ(""); setHits([]); }} aria-label={t("market.clear")}>
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
            {q.trim() && (
              <div className="mb-3 space-y-0.5">
                {searching ? (
                  <p className="px-2 py-1.5 text-xs text-muted-foreground">{t("market.searching")}</p>
                ) : hits.length === 0 ? (
                  <p className="px-2 py-1.5 text-xs text-muted-foreground">{t("market.noResult")}</p>
                ) : (
                  hits.map((h) => (
                    <div key={h.symbol} className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 hover:bg-accent/50">
                      <span className="min-w-0">
                        <span className="text-sm font-medium truncate">{h.name}</span>
                        <span className="ml-1.5 text-xs text-muted-foreground">{h.kind} · {h.symbol}</span>
                      </span>
                      <Button size="sm" variant="outline" onClick={() => void add(h)}>
                        <Plus className="w-3.5 h-3.5" /> {t("market.add")}
                      </Button>
                    </div>
                  ))
                )}
              </div>
            )}

            {/* 自选列表 */}
            {watch.length === 0 ? (
              <EmptyState mode="card" illustration="search" title={t("market.emptyWatch")} />
            ) : (
              <div className="overflow-hidden rounded-lg border border-border">
                <div className="hidden grid-cols-[minmax(0,1fr)_7rem_5.5rem_6.5rem_2.5rem] gap-3 border-b border-border bg-muted/50 px-3 py-2 text-xs font-medium text-muted-foreground sm:grid">
                  <span>{t("pos.symbol")}</span>
                  <span className="text-right">{t("pos.price")}</span>
                  <span className="text-right">{t("pos.pnlPct")}</span>
                  <span className="text-center">{t("market.trend60")}</span>
                  <span />
                </div>
                <ul className="divide-y divide-border/60">
                  {watch.map((w) => (
                    <li
                      key={w.symbol}
                      onClick={() => setSelected(w.symbol)}
                      className={cn(
                        "group grid cursor-pointer grid-cols-[minmax(0,1fr)_auto] items-center gap-2 px-3 py-2.5 text-sm transition-colors hover:bg-accent/40 sm:grid-cols-[minmax(0,1fr)_7rem_5.5rem_6.5rem_2.5rem] sm:gap-3",
                        selected === w.symbol && "bg-accent/50",
                      )}
                    >
                      <button
                        type="button"
                        className="group/name min-w-0 text-left"
                        aria-label={t("pos.viewK", { name: w.name })}
                      >
                        <span className="truncate font-medium group-hover/name:text-primary">{w.name}</span>
                        <span className="ml-1.5 text-xs text-muted-foreground">{w.kind} · {w.symbol}</span>
                        <LineChart className="ml-1 inline h-3 w-3 text-muted-foreground/50 group-hover/name:text-primary" />
                      </button>
                      <span className="text-right tabular-nums max-sm:row-start-2 max-sm:text-left max-sm:text-xs max-sm:text-muted-foreground">
                        {w.price != null ? fmtMoney(w.price, false, true) : "—"}
                        {(w as { quote_source?: string }).quote_source === "snapshot" && (
                          <span className="ml-1.5 rounded bg-muted px-1 py-0.5 text-[10px] font-medium leading-none text-muted-foreground">
                            {t("market.offline")}
                          </span>
                        )}
                      </span>
                      <span className={cn("text-right tabular-nums", pnlClass(w.change_pct ?? 0))}>
                        {w.change_pct != null ? fmtPct(w.change_pct, true) : "—"}
                      </span>
                      <span className="hidden justify-center sm:flex">
                        <SparklineCell symbol={w.symbol} />
                      </span>
                      <span className="flex justify-end">
                        <button
                          type="button"
                          className="rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:bg-red-500/10 hover:text-red-600 group-hover:opacity-100 max-sm:opacity-100"
                          aria-label={t("market.remove", { name: w.name })}
                          onClick={(e) => {
                            e.stopPropagation();
                            setRemoving(w);
                          }}
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {watch.length > 0 && (
              <p className="mt-2 text-[11px] text-muted-foreground">
                {watch.some((w) => (w as { quote_source?: string }).quote_source === "snapshot")
                  ? t("market.srcSnapshot")
                  : t("market.quoteSrc")} · {t("notAdvice")}
              </p>
            )}
            <div className="mt-3 border-t border-border/60 pt-3 text-[11.5px] leading-relaxed text-muted-foreground">
              <ul className="space-y-1">
                <li>· {t("market.tip1")}</li>
                <li>· {t("market.tip2")}</li>
                <li>· {t("market.tip3")}</li>
              </ul>
            </div>
          </>
        ) : holdings.length === 0 ? (
          <EmptyState mode="compact" text={t("holdings.empty")} />
        ) : (
          <>
            <div className="overflow-hidden rounded-lg border border-border">
              <div className="hidden grid-cols-[minmax(0,1fr)_7rem_6rem_7rem_6.5rem] gap-3 border-b border-border bg-muted/50 px-3 py-2 text-xs font-medium text-muted-foreground sm:grid">
                <span>{t("pos.symbol")}</span>
                <span className="text-right">{t("pos.price")}</span>
                <span className="text-right">{t("dash.todayPnl")}</span>
                <span className="text-right">{t("dash.totalPnl")}</span>
                <span className="text-center">{t("market.trend60")}</span>
              </div>
              <ul className="divide-y divide-border/60">
                {holdings.map((p) => {
                  const day = dashboard?.today_pnl.items[p.symbol];
                  return (
                    <li
                      key={p.symbol}
                      onClick={() => setSelected(p.symbol)}
                      className={cn(
                        "grid cursor-pointer grid-cols-[minmax(0,1fr)_auto] items-center gap-2 px-3 py-2.5 text-sm transition-colors hover:bg-accent/40 sm:grid-cols-[minmax(0,1fr)_7rem_6rem_7rem_6.5rem] sm:gap-3",
                        selected === p.symbol && "bg-accent/50",
                      )}
                    >
                      <button
                        type="button"
                        className="group/name min-w-0 text-left"
                        aria-label={t("pos.viewK", { name: p.name })}
                      >
                        <span className="truncate font-medium group-hover/name:text-primary">{p.name}</span>
                        <span className="ml-1.5 text-xs text-muted-foreground">{p.kind} · {p.symbol}</span>
                      </button>
                      <span className="text-right tabular-nums">{fmtMoney(p.last, false, true)}</span>
                      <span className={cn("text-right tabular-nums", pnlClass(day))}>
                        {day != null ? fmtPct((day / Math.max(1, p.market_value)) * 100, true) : "—"}
                      </span>
                      <span className={cn("text-right tabular-nums", pnlClass(p.pnl))}>{fmtMoney(p.pnl, true, true)}</span>
                      <span className="hidden justify-center sm:flex">
                        <SparklineCell symbol={p.symbol} />
                      </span>
                    </li>
                  );
                })}
              </ul>
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">
              {t("market.holdingSrc", { src: dashboard?.source.quotes ?? "" })} · {t("notAdvice")}
            </p>
          </>
        )}
      </Card>

      <div className="space-y-3">
        {tab === "watch" ? (
          detailWatch ? (
            <MarketDetail
              symbol={detailWatch.symbol}
              name={detailWatch.name}
              kind={detailWatch.kind}
              price={detailWatch.price}
              changePct={detailWatch.change_pct}
              onOpenKline={() => setKline({ symbol: detailWatch.symbol, name: detailWatch.name })}
            />
          ) : null
        ) : detailHolding ? (
          <MarketDetail
            symbol={detailHolding.symbol}
            name={detailHolding.name}
            kind={detailHolding.kind}
            price={detailHolding.last}
            changePct={
              dashboard?.today_pnl.items[detailHolding.symbol] != null
                ? (dashboard.today_pnl.items[detailHolding.symbol] / Math.max(1, detailHolding.market_value)) * 100
                : null
            }
            onOpenKline={() => setKline({ symbol: detailHolding.symbol, name: detailHolding.name })}
          />
        ) : null}

      </div>
      </div>

      {/* 删除确认：自选股移除前确认 */}
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(o) => { if (!o) setRemoving(null); }}
        title={t("market.remove", { name: removing?.name ?? "" })}
        description={t("market.removeDesc")}
        danger
        onConfirm={() => {
          if (removing) void remove(removing.symbol);
          setRemoving(null);
        }}
      />

      <KlineDialog
        symbol={kline?.symbol ?? ""}
        name={kline?.name ?? ""}
        open={kline !== null}
        onOpenChange={(o) => !o && setKline(null)}
      />
    </div>
  );
}

import { useMemo, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/ui/confirm";
import { EmptyState } from "@/components/ui/empty-state";
import { StatCell } from "@/components/ui/stat";
import { PillTabs } from "@/components/ui/pill-tabs";
import { LineChart, Combine } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { store, useDashboard, useBootstrap } from "@/lib/store";
import { fmtMoney, pnlClass } from "@/lib/format";
import { cn } from "@/lib/utils";
import { PositionsTable, type PositionOps } from "@/components/PositionsTable";
import { PositionEditDialog } from "@/components/PositionEditDialog";
import { PositionContributionCard } from "@/components/dashboard/PositionContributionCard";
import { api } from "@/lib/api";
import { useMutate } from "@/lib/use-mutate";
import type { Position } from "@/lib/types";

/** 持仓页：按 股票/基金/理财 分组明细 + 风险概览（集中度 / 行业分布）。
 *  明细行支持编辑 / 删除；工具栏支持「合并重复」与「追加持仓」。 */
export function HoldingsView({ onGoMarket }: { onGoMarket?: () => void } = {}) {
  const { t } = useI18n();
  const { dashboard } = useDashboard();
  const { bootstrap } = useBootstrap();
  const compact = (bootstrap?.settings.compact_numbers ?? "on") === "on";
  const positions = dashboard?.positions ?? [];

  const kinds = useMemo(() => ["all", ...Array.from(new Set(positions.map((p) => p.kind)))], [positions]);
  const [kind, setKind] = useState<string>("all");
  const [editing, setEditing] = useState<Position | null>(null);
  const [deleting, setDeleting] = useState<Position | null>(null);

  // 同名不同 symbol 的重复持仓（合并入口只对真有重复的 name 显示）
  const dupeNames = useMemo(() => {
    const seen = new Map<string, number>();
    for (const p of positions) seen.set(p.name, (seen.get(p.name) ?? 0) + 1);
    return Array.from(seen.entries()).filter(([, n]) => n > 1).map(([n]) => n);
  }, [positions]);

  const del = useMutate<{ symbol: string; name: string }, void>({
    fn: (a) => api(`/api/positions/${encodeURIComponent(a.symbol)}`, { method: "DELETE" }).then(() => undefined),
    key: "pos.deleted",
    vars: (a) => ({ name: a.name }),
    onSettled: (_res, e) => {
      if (!e) setDeleting(null);
    },
  });

  const merge = useMutate<undefined, { n: number; count: number }>({
    fn: async () => {
      let total = 0;
      for (const name of dupeNames) {
        const r = await api<{ merged: number }>("/api/positions/merge", {
          method: "POST",
          body: JSON.stringify({ name }),
        });
        total += r.merged;
      }
      return { n: total, count: dupeNames.length };
    },
    key: (_a, res) => (res.n > 0 ? "pos.mergeAllDone" : "pos.mergeNone"),
    vars: (_a, res) => ({
      n: res.n,
      count: res.count,
      name: res.count > 0 ? dupeNames.join("、") : "",
    }),
  });

  const doMerge = () => {
    if (!dupeNames.length) return;
    void merge.mutateAsync(undefined);
  };

  const append = useMutate<{ p: Position; payload: { shares: number; cost: number; last?: number } }, { new_shares: number }>({
    fn: (a) =>
      api<{ new_shares: number }>(`/api/positions/${encodeURIComponent(a.p.symbol)}/append`, {
        method: "POST",
        body: JSON.stringify(a.payload),
      }),
    key: "pos.appendDone",
    vars: (a, res) => ({ name: a.p.name, shares: res.new_shares }),
  });

  const ops: PositionOps = {
    onEdit: (p) => setEditing(p),
    onDelete: (p) => setDeleting(p),
    onAppend: (p, payload) => void append.mutateAsync({ p, payload }),
  };

  if (!dashboard) return null;

  // 空持仓引导：新用户还没有任何持仓时不给零值统计与空图表
  if (positions.length === 0) {
    return (
      <div className="flex min-h-[calc(100vh-10rem)] flex-col justify-center space-y-3">
        <Card>
          <EmptyState
            illustration="holdings"
            title={t("hold.emptyTitle")}
            desc={t("hold.emptyDesc")}
            actions={
              <Button size="sm" onClick={() => onGoMarket?.()}>
                <LineChart className="w-4 h-4" /> {t("hold.emptyBtn")}
              </Button>
            }
          />
        </Card>
        <p className="px-2 text-center text-xs text-muted-foreground">{t("hold.emptyHint")}</p>
      </div>
    );
  }

  const filtered = kind === "all" ? positions : positions.filter((p) => p.kind === kind);
  const cash = positions.filter((p) => p.kind === "现金").reduce((s, p) => s + p.cost, 0);
  const totalMV = positions.reduce((s, p) => s + p.market_value, 0) - cash;
  const totalPnl = positions.reduce((s, p) => s + p.pnl, 0);
  const todayTotal = dashboard.today_pnl.total;
  // 集中度面板用 investable_pct（相对非现金市值）：现金不该稀释股票权重
  const byAsset = [...dashboard.concentration.by_asset]
    .sort((a, b) => (b.investable_pct ?? b.pct) - (a.investable_pct ?? a.pct))
    .slice(0, 3);
  const byIndustry = [...dashboard.concentration.by_industry]
    .sort((a, b) => (b.investable_pct ?? b.pct) - (a.investable_pct ?? a.pct))
    .slice(0, 4);

  // 资产/行业集中度：找出超过阈值的项，用于"风险提示"条（股票软件常见的红黄标记）
  // 标的与行业分开列：两者是不同维度的超限，合并展示会出现同名项重复
  const breaches = [
    ...dashboard.concentration.asset_breaches.map((b) => ({ label: b.name, pct: b.investable_pct ?? b.pct, kind: t("holdings.breachAsset") })),
    ...dashboard.concentration.industry_breaches.map((b) => ({ label: b.industry, pct: b.investable_pct ?? b.pct, kind: t("holdings.breachIndustry") })),
  ];
  const topWeight = byAsset[0]?.investable_pct ?? byAsset[0]?.pct ?? 0;

  return (
    <div className="space-y-3">
      {/* 摘要条：股票软件式关键指标，一行读完 */}
      <div className="grid grid-cols-2 gap-y-3 rounded-2xl border border-border bg-card px-3 py-2 sm:grid-cols-4 sm:divide-x sm:divide-border/70">
        <StatCell label={t("dash.holdingsValue")} value={fmtMoney(totalMV, false, compact)} />
        <StatCell label={t("dash.todayPnl")} value={fmtMoney(todayTotal, true, compact)} valueClass={pnlClass(todayTotal)} />
        <StatCell label={t("dash.totalPnl")} value={fmtMoney(totalPnl, true, compact)} valueClass={pnlClass(totalPnl)} />
        <StatCell label={t("dash.cashAvailable")} value={fmtMoney(cash, false, compact)} />
      </div>

      {breaches.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-amber-500/30 bg-amber-500/[0.06] px-3 py-2 text-[12px]">
          <span className="font-medium text-amber-700 dark:text-amber-400">
            {t("holdings.breachTitle", { n: breaches.length })}
          </span>
          {breaches.slice(0, 4).map((b) => (
            <span key={`${b.kind}-${b.label}`} className="text-foreground/70">
              <span className="mr-1 text-[11px] text-muted-foreground">{b.kind}</span>
              {b.label} <b className="tabular-nums">{b.pct}%</b>
            </span>
          ))}
          <span className="text-muted-foreground">{t("holdings.breachHint", { n: dashboard.concentration.threshold_pct })}</span>
        </div>
      )}

      {/* 主体：左表格（主）+ 右分析栏（辅），股票软件的经典分栏 */}
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_18rem]">
        <Card className="min-w-0 p-[var(--card-pad)]">
          <div className="mb-2 flex flex-wrap items-center gap-1.5">
            <PillTabs
              value={kind}
              onChange={setKind}
              size="sm"
              options={kinds.map((k) => ({ value: k, label: k === "all" ? t("holdings.all") : k }))}
            />
            <span className="ml-auto text-xs text-muted-foreground">
              {filtered.length} {t("holdings.items")}
            </span>
            {dupeNames.length > 0 && (
              <Button size="sm" variant="outline" onClick={() => void doMerge()} disabled={merge.isPending}>
                <Combine className="h-3.5 w-3.5" /> {t("pos.mergeBtn")}
                <span className="ml-1 text-muted-foreground">({dupeNames.length})</span>
              </Button>
            )}
          </div>
          {filtered.length === 0 ? (
            <EmptyState mode="compact" text={t("holdings.empty")} />
          ) : (
            <>
              <PositionsTable rows={filtered} compact={compact} ops={ops} />
              <PositionContributionCard positions={positions} compact={compact} />
            </>
          )}
        </Card>

        <div className="space-y-3">
          <Card className="p-[var(--card-pad)]">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-medium">{t("holdings.concentration")}</span>
              <Badge variant={topWeight > dashboard.concentration.threshold_pct ? "warn" : "muted"}>
                {t("holdings.threshold", { n: dashboard.concentration.threshold_pct })}
              </Badge>
            </div>
            {byAsset.length === 0 ? (
              <EmptyState mode="compact" text={t("holdings.empty")} className="py-4" />
            ) : (
              <ul className="space-y-2">
                {byAsset.map((a) => {
                  const weight = a.investable_pct ?? a.pct;
                  const over = weight > dashboard.concentration.threshold_pct;
                  return (
                    <li key={a.name} className="text-[13px]">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="min-w-0 truncate">{a.name}</span>
                        <span className={cn("shrink-0 tabular-nums", over ? "font-medium text-amber-600" : "text-muted-foreground")}>
                          {weight}%
                        </span>
                      </div>
                      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
                        <div
                          className={cn("h-full rounded-full", over ? "bg-amber-500" : "bg-primary")}
                          style={{ width: `${Math.min(100, weight)}%` }}
                        />
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>

          <Card className="p-[var(--card-pad)]">
            <div className="mb-2 text-sm font-medium">{t("holdings.industry")}</div>
            {byIndustry.length === 0 ? (
              <EmptyState mode="compact" text={t("holdings.empty")} className="py-4" />
            ) : (
              <ul className="space-y-1.5 text-[13px]">
                {byIndustry.map((x) => (
                  <li key={x.industry} className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate text-foreground/80">{x.industry}</span>
                    <span className="shrink-0 tabular-nums text-muted-foreground">{x.investable_pct ?? x.pct}%</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {/* 风险清单：把后端算好的 flags 直接列出来（股票软件的"风险提示"面板） */}
          {(dashboard.flags ?? []).length > 0 && (
            <Card className="p-[var(--card-pad)]">
              <div className="mb-2 text-sm font-medium">{t("holdings.riskTitle")}</div>
              <ul className="space-y-1.5">
                {(dashboard.flags ?? []).slice(0, 5).map((f) => (
                  <li key={f.code + f.text} className="flex gap-1.5 text-[12px] leading-relaxed">
                    <span
                      className={cn(
                        "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full",
                        f.level === "error" ? "bg-red-500" : f.level === "warn" ? "bg-amber-500" : "bg-emerald-500",
                      )}
                    />
                    <span className="text-foreground/75">{f.text}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>

      {/* 编辑弹窗 */}
      <PositionEditDialog
        position={editing}
        open={editing !== null}
        onOpenChange={(o) => !o && setEditing(null)}
        onDone={() => {
          setEditing(null);
          store.bump();
        }}
      />

      {/* 删除确认 */}
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={t("pos.deleteTitle", { name: deleting?.name ?? "" })}
        description={t("pos.deleteDesc")}
        confirmText={t("confirm.confirm")}
        cancelText={t("confirm.cancel")}
        danger
        onConfirm={() => {
          if (deleting) void del.mutate({ symbol: deleting.symbol, name: deleting.name });
        }}
      />
    </div>
  );
}

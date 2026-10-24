/** 投资策略页：风险体检 / 目标配置再平衡 / 估值温度计 / 定投计划 / FIRE。
 *
 * 信息架构按"股票软件的决策顺序"排：
 *   1. 顶部关键指标条（一眼知道组合现在什么状态）
 *   2. 净值曲线 + 指标表（组合表现与基准对比）
 *   3. 左：再平衡调仓清单 / 右：估值温度计
 *   4. 定投计划表 + FIRE 进度
 * 每一块都能独立降级：行情不可用时显示原因，不显示 0 也不显示空白。
 */

import { useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Gauge,
  Plus,
  RefreshCw,
  Target,
  Trash2,
  TrendingUp,
  Wallet,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { StatCell } from "@/components/ui/stat";
import { ConfirmDialog } from "@/components/ui/confirm";
import { useEChart, usePalette, axisLabelColor } from "@/lib/charts";
import { useTheme } from "@/lib/theme";
import { useI18n } from "@/lib/i18n";
import { useDashboard } from "@/lib/store";
import { fmtMoney, fmtPct, pnlClass } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  useAllocation,
  useDcaPlans,
  useDeleteDca,
  useFire,
  useRisk,
  useSaveAllocation,
  useSaveDca,
  useValuation,
  type DcaPlan,
  type DriftItem,
  type RiskMetrics,
  type ValuationItem,
} from "@/lib/use-strategy";

const BENCHMARKS = [
  { key: "sh000300", label: "沪深300" },
  { key: "sh000001", label: "上证指数" },
  { key: "sz399001", label: "深证成指" },
  { key: "sz399006", label: "创业板指" },
];

const ZONE_TEXT: Record<ValuationItem["zone"], string> = {
  cheap: "text-emerald-600 dark:text-emerald-400",
  low: "text-emerald-600 dark:text-emerald-400",
  fair: "text-amber-600 dark:text-amber-400",
  high: "text-orange-600 dark:text-orange-400",
  expensive: "text-red-600 dark:text-red-400",
};

/** 指标卡：指标名 + 数值 + 一行解释（解释比数字重要，否则用户不知道好坏） */
function MetricCell({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "up" | "down" | "muted";
}) {
  return (
    <div className="min-w-0 rounded-lg bg-muted/25 px-3 py-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div
        className={cn(
          "mt-0.5 text-lg font-bold tabular-nums leading-tight",
          tone === "up" ? "text-up" : tone === "down" ? "text-down" : "text-foreground",
        )}
      >
        {value}
      </div>
      {hint && <div className="mt-0.5 text-[11px] leading-snug text-muted-foreground">{hint}</div>}
    </div>
  );
}

function metricOrDash(v: number | null | undefined, suffix = ""): string {
  return v == null ? "数据不足" : `${v}${suffix}`;
}

function sharpeTone(v: number | null | undefined): "up" | "down" | "muted" {
  if (v == null) return "muted";
  return v >= 1 ? "up" : v < 0 ? "down" : "muted";
}

/** 组合净值曲线 vs 基准：两条线归一化到 100 起点，看相对强弱。 */
function EquityChart({ equity, benchmark, label }: { equity: number[]; benchmark?: number[] | null; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const { resolved } = useTheme();
  const palette = usePalette();

  const option = useMemo(() => {
    if (!equity.length) return null;
    const norm = (arr: number[]) => {
      const base = arr[0] || 1;
      return arr.map((v) => Number(((v / base) * 100).toFixed(2)));
    };
    const series: Record<string, unknown>[] = [
      {
        name: label,
        type: "line",
        data: norm(equity),
        showSymbol: false,
        lineStyle: { width: 1.8, color: palette[0] },
        itemStyle: { color: palette[0] },
        areaStyle: { opacity: 0.08, color: palette[0] },
      },
    ];
    if (benchmark && benchmark.length) {
      // 基准可能与组合长度不同（停牌/数据源差异）：按尾部对齐，短的一方左补 null，
      // 保证两条线的右端是同一天，否则"跑赢/跑输"会因为时间轴错位而失真。
      const b = norm(benchmark);
      const n = Math.min(equity.length, b.length);
      const pad = equity.length - n;
      const aligned: (number | null)[] = [...new Array(pad).fill(null), ...b.slice(b.length - n)];
      series.push({
        name: "基准",
        type: "line",
        data: aligned,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 1.2, type: "dashed", color: palette[5] },
        itemStyle: { color: palette[5] },
      });
    }
    return {
      tooltip: { trigger: "axis", triggerOn: "click", renderMode: "richText", confine: true },
      legend: { top: 0, textStyle: { fontSize: 11, color: axisLabelColor(resolved) } },
      grid: { left: 6, right: 10, top: 28, bottom: 4, containLabel: true },
      xAxis: { type: "category", data: equity.map((_, i) => i), show: false },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: { fontSize: 10, color: axisLabelColor(resolved), formatter: (v: number) => `${v}` },
        splitLine: { lineStyle: { type: "dashed", color: "hsl(var(--border))" } },
      },
      series,
    };
  }, [equity, benchmark, label, palette, resolved]);

  useEChart(ref, option, [option]);
  return <div ref={ref} className="h-56 w-full" />;
}

/** 风险块：指标条 + 曲线 + 指标表 */
function RiskSection({ benchmark, onBenchmark }: { benchmark: string; onBenchmark: (k: string) => void }) {
  const { t } = useI18n();
  const { data, isLoading, isError, refetch, isFetching } = useRisk(benchmark);

  if (isLoading) {
    return (
      <Card className="p-[var(--card-pad)]">
        <Skeleton className="mb-3 h-4 w-32" />
        <Skeleton className="h-56 w-full" />
      </Card>
    );
  }
  if (isError || !data) {
    return (
      <Card className="p-[var(--card-pad)]">
        <EmptyState mode="compact" text={t("strategy.loadFail")} />
      </Card>
    );
  }

  const m: RiskMetrics | undefined = data.metrics;
  const available = data.available && m;

  return (
    <Card className="p-[var(--card-pad)]">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Activity className="h-4 w-4 text-primary" />
          {t("strategy.riskTitle")}
        </div>
        <Badge variant="muted">{t("strategy.backtestBasis")}</Badge>
        <span className="ml-auto flex items-center gap-1.5">
          {BENCHMARKS.map((b) => (
            <button
              key={b.key}
              type="button"
              onClick={() => onBenchmark(b.key)}
              className={cn(
                "rounded-full px-2 py-0.5 text-[11px] transition-colors",
                benchmark === b.key
                  ? "bg-foreground text-background"
                  : "bg-muted text-muted-foreground hover:text-foreground",
              )}
            >
              {b.label}
            </button>
          ))}
          <button
            type="button"
            onClick={() => void refetch()}
            aria-label={t("strategy.refresh")}
            className="rounded p-1 text-muted-foreground hover:text-foreground"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", isFetching && "animate-spin")} />
          </button>
        </span>
      </div>

      {!available ? (
        <EmptyState mode="compact" text={data.reason || t("strategy.noRiskData")} className="py-10" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <MetricCell
              label={t("strategy.totalReturn")}
              value={metricOrDash(m.total_return_pct, "%")}
              hint={t("strategy.totalReturnHint")}
              tone={m.total_return_pct == null ? "muted" : m.total_return_pct >= 0 ? "up" : "down"}
            />
            <MetricCell
              label={t("strategy.annualVol")}
              value={metricOrDash(m.annualized_volatility_pct, "%")}
              hint={t("strategy.annualVolHint")}
              tone="muted"
            />
            <MetricCell
              label={t("strategy.maxDrawdown")}
              value={metricOrDash(m.max_drawdown_pct, "%")}
              hint={t("strategy.maxDrawdownHint")}
              tone="down"
            />
            <MetricCell
              label={t("strategy.sharpe")}
              value={metricOrDash(m.sharpe)}
              hint={t("strategy.sharpeHint")}
              tone={sharpeTone(m.sharpe)}
            />
          </div>

          <div className="mt-3">
            <EquityChart
              equity={data.equity_curve ?? []}
              benchmark={data.benchmark_curve}
              label={t("strategy.portfolio")}
            />
          </div>

          <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[12px] sm:grid-cols-3">
            <MetricRow label={t("strategy.sortino")} value={metricOrDash(m.sortino)} />
            <MetricRow label={t("strategy.calmar")} value={metricOrDash(m.calmar)} />
            <MetricRow label={t("strategy.var95")} value={metricOrDash(m.var_95_pct, "%")} />
            <MetricRow label={t("strategy.beta")} value={metricOrDash(m.beta)} />
            <MetricRow label={t("strategy.alpha")} value={metricOrDash(m.alpha_pct, "%")} />
            <MetricRow
              label={t("strategy.excess")}
              value={metricOrDash(m.excess_return_pct, "%")}
              tone={m.excess_return_pct == null ? undefined : m.excess_return_pct >= 0 ? "up" : "down"}
            />
            <MetricRow label={t("strategy.winRate")} value={metricOrDash(m.win_rate_pct, "%")} />
            <MetricRow label={t("strategy.bestDay")} value={metricOrDash(m.best_day_pct, "%")} />
            <MetricRow label={t("strategy.worstDay")} value={metricOrDash(m.worst_day_pct, "%")} />
          </div>

          <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
            {data.basis_note}
            {data.diagnostics && data.diagnostics.missing.length > 0 && (
              <span className="ml-1 inline-block text-amber-600 dark:text-amber-400">
                {" "}
                {t("strategy.missingQuotes", { n: data.diagnostics.missing.length, names: data.diagnostics.missing.slice(0, 3).join("、") })}
              </span>
            )}
          </p>          {m.notes.length > 0 && (
            <p className="mt-1 text-[11px] text-muted-foreground">{m.notes.join("；")}</p>
          )}
        </>
      )}
    </Card>
  );
}

function MetricRow({ label, value, tone }: { label: string; value: string; tone?: "up" | "down" }) {
  return (
    <div className="flex items-baseline justify-between gap-2 border-b border-border/40 py-0.5">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("tabular-nums", tone === "up" ? "text-up" : tone === "down" ? "text-down" : "text-foreground")}>
        {value}
      </span>
    </div>
  );
}

/** 再平衡块：目标配置编辑 + 漂移清单 */
function RebalanceSection() {
  const { t } = useI18n();
  const { dashboard } = useDashboard();
  const [band, setBand] = useState(5);
  // band 必须作为查询参数传给后端：调仓清单是按容忍带算出来的，
  // 只改前端 select 不改请求，用户会以为调了带而清单没动。
  const { data, isLoading, refetch } = useAllocation(band);
  const save = useSaveAllocation();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<{ symbol: string; name: string; target_pct: string }[]>([]);

  const positions = dashboard?.positions ?? [];
  const plan = data?.plan;
  const targets = data?.targets ?? [];

  const startEdit = () => {
    const existing = new Map(targets.map((t) => [t.symbol, t.target_pct]));
    const rows = positions.map((p) => ({
      symbol: p.symbol,
      name: p.name,
      target_pct: String(existing.get(p.symbol) ?? 0),
    }));
    setDraft(rows);
    setEditing(true);
  };

  const totalDraft = draft.reduce((s, r) => s + (Number(r.target_pct) || 0), 0);

  const submit = () => {
    const payload = draft
      .map((r) => ({ symbol: r.symbol, name: r.name, target_pct: Number(r.target_pct) || 0 }))
      .filter((r) => r.target_pct > 0);
    save.mutate(payload, {
      onSuccess: () => {
        setEditing(false);
        void refetch();
      },
    });
  };

  if (isLoading) {
    return (
      <Card className="p-[var(--card-pad)]">
        <Skeleton className="mb-3 h-4 w-28" />
        <Skeleton className="h-40 w-full" />
      </Card>
    );
  }

  const actionBadge = (item: DriftItem) => {
    if (item.action === "buy")
      return (
        <span className="inline-flex items-center gap-0.5 rounded bg-red-500/10 px-1.5 py-0.5 text-[11px] font-medium text-red-600 dark:text-red-400">
          <ArrowUpRight className="h-3 w-3" /> {t("strategy.buy")}
        </span>
      );
    if (item.action === "sell")
      return (
        <span className="inline-flex items-center gap-0.5 rounded bg-emerald-500/10 px-1.5 py-0.5 text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
          <ArrowDownRight className="h-3 w-3" /> {t("strategy.sell")}
        </span>
      );
    return <span className="text-[11px] text-muted-foreground">{t("strategy.hold")}</span>;
  };

  return (
    <Card className="flex min-w-0 flex-col p-[var(--card-pad)]">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Target className="h-4 w-4 text-primary" />
          {t("strategy.rebalanceTitle")}
        </div>
        {plan && data?.available && (
          <Badge variant={plan.needs_rebalance ? "warn" : "ok"}>
            {plan.needs_rebalance
              ? t("strategy.needRebalance", { p: plan.max_drift_pct })
              : t("strategy.inBand", { p: plan.band_pct })}
          </Badge>
        )}
        {!data?.available && <Badge variant="muted">{t("strategy.notConfigured")}</Badge>}
        <span className="ml-auto flex items-center gap-2">
          <label className="flex items-center gap-1 text-[11px] text-muted-foreground">
            {t("strategy.band")}
            <select
              value={band}
              onChange={(e) => setBand(Number(e.target.value))}
              className="rounded border border-border bg-background px-1 py-0.5 text-[11px]"
            >
              {[3, 5, 8, 10].map((b) => (
                <option key={b} value={b}>
              ±{b}%
                </option>
              ))}
            </select>
          </label>
          <Button size="sm" variant="outline" className="h-7 px-2 text-xs" onClick={startEdit}>
            {t("strategy.editTargets")}
          </Button>
        </span>
      </div>

      {editing ? (
        <div className="space-y-2">
          <p className="text-[11px] text-muted-foreground">{t("strategy.editHint")}</p>
          <div className="max-h-72 overflow-y-auto scroll-thin">
            <table className="w-full text-[12px]">
              <tbody>
                {draft.map((row, i) => (
                  <tr key={row.symbol} className="border-b border-border/40">
                    <td className="py-1.5 pr-2">
                      <span className="font-medium">{row.name}</span>
                      <span className="ml-1 text-muted-foreground">{row.symbol}</span>
                    </td>
                    <td className="w-24 py-1.5 text-right">
                      <input
                        type="number"
                        min={0}
                        max={100}
                        step={1}
                        value={row.target_pct}
                        onChange={(e) => {
                          const next = [...draft];
                          next[i] = { ...row, target_pct: e.target.value };
                          setDraft(next);
                        }}
                        className="w-16 rounded border border-border bg-background px-1.5 py-0.5 text-right tabular-nums"
                      />
                      <span className="ml-1 text-muted-foreground">%</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between text-[12px]">
            <span className={cn(totalDraft === 100 ? "text-muted-foreground" : "text-amber-600 dark:text-amber-400")}>
              {t("strategy.targetSum", { p: totalDraft })}
            </span>
            <span className="flex gap-2">
              <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={() => setEditing(false)}>
                {t("confirm.cancel")}
              </Button>
              <Button size="sm" className="h-7 px-2 text-xs" onClick={submit} disabled={save.isPending}>
                {t("strategy.saveTargets")}
              </Button>
            </span>
          </div>
        </div>
      ) : !data?.available ? (
        <EmptyState
          mode="compact"
          text={t("strategy.noTargets")}
          className="py-10"
        />
      ) : (
        <>
          <div className="overflow-x-auto scroll-thin">
            <table className="w-full min-w-[420px] text-[12px]">
              <thead>
                <tr className="border-b border-border text-left text-[11px] text-muted-foreground">
                  <th className="py-1.5 pr-2 font-medium">{t("strategy.colName")}</th>
                  <th className="py-1.5 pr-2 text-right font-medium">{t("strategy.colCurrent")}</th>
                  <th className="py-1.5 pr-2 text-right font-medium">{t("strategy.colTarget")}</th>
                  <th className="py-1.5 pr-2 text-right font-medium">{t("strategy.colDrift")}</th>
                  <th className="py-1.5 pr-2 text-right font-medium">{t("strategy.colAmount")}</th>
                  <th className="py-1.5 text-right font-medium">{t("strategy.colAction")}</th>
                </tr>
              </thead>
              <tbody>
                {plan?.items.map((item) => (
                  <tr key={item.symbol} className="border-b border-border/40 last:border-0">
                    <td className="max-w-[8rem] truncate py-1.5 pr-2">{item.name}</td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">{item.current_pct}%</td>
                    <td className="py-1.5 pr-2 text-right tabular-nums text-muted-foreground">{item.target_pct}%</td>
                    <td
                      className={cn(
                        "py-1.5 pr-2 text-right tabular-nums",
                        Math.abs(item.drift_pct) > (plan?.band_pct ?? 5) ? "font-medium text-amber-600 dark:text-amber-400" : "text-muted-foreground",
                      )}
                    >
                      {item.drift_pct > 0 ? "+" : ""}
                      {item.drift_pct}%
                    </td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">
                      {item.action === "hold" ? "—" : fmtMoney(item.amount, false, true)}
                      {item.approx_shares != null && (
                        <span className="ml-1 text-[10px] text-muted-foreground">≈{item.approx_shares}股</span>
                      )}
                    </td>
                    <td className="py-1.5 text-right">{actionBadge(item)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="mt-2 space-y-0.5">
            {plan?.notes.map((n, i) => (
              <li key={i} className="text-[11px] leading-relaxed text-muted-foreground">
                · {n}
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

/** 估值温度计：每只持仓一根横向色条，指针位置=分位 */
function ValuationSection() {
  const { t } = useI18n();
  const { data, isLoading, isError } = useValuation();

  if (isLoading) {
    return (
      <Card className="p-[var(--card-pad)]">
        <Skeleton className="mb-3 h-4 w-28" />
        <Skeleton className="h-40 w-full" />
      </Card>
    );
  }
  if (isError || !data) {
    return (
      <Card className="p-[var(--card-pad)]">
        <EmptyState mode="compact" text={t("strategy.loadFail")} />
      </Card>
    );
  }

  return (
    <Card className="p-[var(--card-pad)]">
      <div className="mb-2 flex items-center gap-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Gauge className="h-4 w-4 text-primary" />
          {t("strategy.valuationTitle")}
        </div>
        {(data.lookback_days ?? 0) > 0 && (
          <span className="ml-auto text-[11px] text-muted-foreground">
            {t("strategy.lookback", { n: data.lookback_days })}
          </span>
        )}
      </div>

      {!data.available || data.items.length === 0 ? (
        <EmptyState mode="compact" text={data.reason || t("strategy.noValuation")} className="py-10" />
      ) : (
        <ul className="space-y-2.5">
          {data.items.map((item) => (
            <li key={item.symbol}>
              <div className="flex items-baseline justify-between gap-2 text-[12px]">
                <span className="min-w-0 truncate">
                  <span className="font-medium">{item.name}</span>
                  <span className="ml-1 text-muted-foreground">{item.symbol}</span>
                </span>
                <span className="flex shrink-0 items-baseline gap-2">
                  <span className={cn("font-medium tabular-nums", ZONE_TEXT[item.zone])}>{item.zone_label}</span>
                  <span className="tabular-nums text-muted-foreground">{item.percentile}%</span>
                </span>
              </div>
              {/* 温度条：五段色阶 + 当前位置指针 */}
              <div className="relative mt-1 flex h-1.5 overflow-hidden rounded-full">
                <span className="h-full flex-1 bg-emerald-500/70" />
                <span className="h-full flex-1 bg-emerald-400/70" />
                <span className="h-full flex-1 bg-amber-400/70" />
                <span className="h-full flex-1 bg-orange-500/70" />
                <span className="h-full flex-1 bg-red-500/70" />
                <span
                  className="absolute top-1/2 h-3 w-0.5 -translate-y-1/2 rounded bg-foreground shadow"
                  style={{ left: `calc(${Math.max(0, Math.min(100, item.percentile))}% - 1px)` }}
                />
              </div>
              <div className="mt-0.5 flex justify-between text-[10px] text-muted-foreground">
                <span>
                  {t("strategy.rangeLow")} {item.low}
                </span>
                <span>
                  {t("strategy.current")} {item.current}
                </span>
                <span>
                  {t("strategy.rangeHigh")} {item.high}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">{t("strategy.valuationNote")}</p>
    </Card>
  );
}

/** 定投计划块：表格 + 新建表单 */
function DcaSection() {
  const { t } = useI18n();
  const { dashboard } = useDashboard();
  const { data, isLoading } = useDcaPlans();
  const save = useSaveDca();
  const del = useDeleteDca();
  const [adding, setAdding] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<DcaPlan | null>(null);
  const [form, setForm] = useState({
    symbol: "",
    name: "",
    amount: "1000",
    frequency: "monthly" as "monthly" | "weekly",
    day: "10",
  });

  const positions = (dashboard?.positions ?? []).filter((p) => p.kind !== "现金");
  const items = data?.items ?? [];

  const submit = () => {
    const amt = Number(form.amount);
    if (!form.symbol || !amt || amt <= 0) return;
    save.mutate(
      {
        symbol: form.symbol,
        name: form.name || form.symbol,
        amount: amt,
        frequency: form.frequency,
        day: Number(form.day) || 1,
      },
      {
        onSuccess: () => {
          setAdding(false);
          setForm({ symbol: "", name: "", amount: "1000", frequency: "monthly", day: "10" });
        },
      },
    );
  };

  if (isLoading) {
    return (
      <Card className="p-[var(--card-pad)]">
        <Skeleton className="mb-3 h-4 w-24" />
        <Skeleton className="h-32 w-full" />
      </Card>
    );
  }

  return (
    <Card className="p-[var(--card-pad)]">
      <div className="mb-2 flex items-center gap-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <TrendingUp className="h-4 w-4 text-primary" />
          {t("strategy.dcaTitle")}
        </div>
        <Button
          size="sm"
          variant="outline"
          className="ml-auto h-7 px-2 text-xs"
          onClick={() => setAdding((v) => !v)}
        >
          <Plus className="h-3.5 w-3.5" /> {t("strategy.dcaAdd")}
        </Button>
      </div>

      {adding && (
        <div className="mb-3 space-y-2 rounded-lg border border-border bg-muted/20 p-2.5">
          <div className="grid grid-cols-2 gap-2 text-[12px]">
            <label className="flex flex-col gap-0.5">
              <span className="text-[11px] text-muted-foreground">{t("strategy.dcaSymbol")}</span>
              <select
                value={form.symbol}
                onChange={(e) => {
                  const p = positions.find((x) => x.symbol === e.target.value);
                  setForm({ ...form, symbol: e.target.value, name: p?.name ?? "" });
                }}
                className="rounded border border-border bg-background px-1.5 py-1"
              >
                <option value="">—</option>
                {positions.map((p) => (
                  <option key={p.symbol} value={p.symbol}>
                    {p.name}（{p.symbol}）
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-0.5">
              <span className="text-[11px] text-muted-foreground">{t("strategy.dcaAmount")}</span>
              <input
                type="number"
                min={1}
                value={form.amount}
                onChange={(e) => setForm({ ...form, amount: e.target.value })}
                className="rounded border border-border bg-background px-1.5 py-1 tabular-nums"
              />
            </label>
            <label className="flex flex-col gap-0.5">
              <span className="text-[11px] text-muted-foreground">{t("strategy.dcaFrequency")}</span>
              <select
                value={form.frequency}
                onChange={(e) => setForm({ ...form, frequency: e.target.value as "monthly" | "weekly" })}
                className="rounded border border-border bg-background px-1.5 py-1"
              >
                <option value="monthly">{t("strategy.monthly")}</option>
                <option value="weekly">{t("strategy.weekly")}</option>
              </select>
            </label>
            <label className="flex flex-col gap-0.5">
              <span className="text-[11px] text-muted-foreground">
                {form.frequency === "monthly" ? t("strategy.dayOfMonth") : t("strategy.dayOfWeek")}
              </span>
              <input
                type="number"
                min={1}
                max={form.frequency === "monthly" ? 28 : 7}
                value={form.day}
                onChange={(e) => setForm({ ...form, day: e.target.value })}
                className="rounded border border-border bg-background px-1.5 py-1 tabular-nums"
              />
            </label>
          </div>
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={() => setAdding(false)}>
              {t("confirm.cancel")}
            </Button>
            <Button size="sm" className="h-7 px-2 text-xs" onClick={submit} disabled={save.isPending || !form.symbol}>
              {t("strategy.dcaSave")}
            </Button>
          </div>
        </div>
      )}

      {items.length === 0 ? (
        <EmptyState mode="compact" text={t("strategy.dcaEmpty")} className="py-8" />
      ) : (
        <div className="overflow-x-auto scroll-thin">
          <table className="w-full min-w-[520px] text-[12px]">
            <thead>
              <tr className="border-b border-border text-left text-[11px] text-muted-foreground">
                <th className="py-1.5 pr-2 font-medium">{t("strategy.colName")}</th>
                <th className="py-1.5 pr-2 text-right font-medium">{t("strategy.dcaPerPeriod")}</th>
                <th className="py-1.5 pr-2 text-right font-medium">{t("strategy.dcaInvested")}</th>
                <th className="py-1.5 pr-2 text-right font-medium">{t("strategy.dcaAvgCost")}</th>
                <th className="py-1.5 pr-2 text-right font-medium">{t("strategy.dcaPnl")}</th>
                <th className="py-1.5 pr-2 text-right font-medium">{t("strategy.dcaNext")}</th>
                <th className="py-1.5 w-6" />
              </tr>
            </thead>
            <tbody>
              {items.map((plan) => {
                const s = plan.stats;
                return (
                  <tr key={plan.id} className="border-b border-border/40 last:border-0">
                    <td className="max-w-[9rem] truncate py-1.5 pr-2">
                      <span className="font-medium">{plan.name}</span>
                      <span className="ml-1 text-[10px] text-muted-foreground">
                        {plan.frequency === "monthly"
                          ? `${t("strategy.monthly")} ${plan.day}${t("strategy.dayUnit")}`
                          : `${t("strategy.weekly")}`}
                      </span>
                    </td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">{fmtMoney(plan.amount, false, true)}</td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">{fmtMoney(s.invested, false, true)}</td>
                    <td className="py-1.5 pr-2 text-right tabular-nums text-muted-foreground">{s.avg_cost ?? "—"}</td>
                    <td className={cn("py-1.5 pr-2 text-right tabular-nums", pnlClass(s.pnl))}>
                      {s.pnl == null ? "—" : fmtMoney(s.pnl, true, true)}
                      {s.pnl_pct != null && <span className="ml-1 text-[10px]">({fmtPct(s.pnl_pct, true)})</span>}
                    </td>
                    <td className="py-1.5 pr-2 text-right tabular-nums text-muted-foreground">{plan.next_run ?? "—"}</td>
                    <td className="py-1.5 text-right">
                      <button
                        type="button"
                        aria-label={t("strategy.dcaDelete")}
                        onClick={() => setPendingDelete(plan)}
                        className="rounded p-0.5 text-muted-foreground hover:text-red-500"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(o) => !o && setPendingDelete(null)}
        title={t("strategy.dcaDeleteTitle", { name: pendingDelete?.name ?? "" })}
        description={t("strategy.dcaDeleteDesc")}
        confirmText={t("confirm.confirm")}
        cancelText={t("confirm.cancel")}
        danger
        onConfirm={() => {
          const p = pendingDelete;
          setPendingDelete(null);
          if (p) del.mutate(p.id);
        }}
      />
    </Card>
  );
}

/** FIRE 进度：目标本金 + 缺口 + 年限 */
function FireSection() {
  const { t } = useI18n();
  const { data, isLoading, isError } = useFire();

  if (isLoading) {
    return (
      <Card className="p-[var(--card-pad)]">
        <Skeleton className="mb-3 h-4 w-24" />
        <Skeleton className="h-28 w-full" />
      </Card>
    );
  }
  if (isError || !data) {
    return (
      <Card className="p-[var(--card-pad)]">
        <EmptyState mode="compact" text={t("strategy.loadFail")} />
      </Card>
    );
  }

  const pct = Math.max(0, Math.min(100, data.progress_pct ?? 0));
  const reached = (data.progress_pct ?? 0) >= 100;

  return (
    <Card className="p-[var(--card-pad)]">
      <div className="mb-2 flex items-center gap-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Wallet className="h-4 w-4 text-primary" />
          {t("strategy.fireTitle")}
        </div>
        <Badge variant={reached ? "ok" : "muted"} className="ml-auto">
          {reached ? t("strategy.fireReached") : t("strategy.fireInProgress")}
        </Badge>
      </div>

      {!data.available ? (
        <EmptyState mode="compact" text={t("strategy.fireNoData")} className="py-8" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <StatCell label={t("strategy.fireTarget")} value={fmtMoney(data.target_principal, false, true)} />
            <StatCell label={t("strategy.fireNetWorth")} value={fmtMoney(data.current_net_worth, false, true)} />
            <StatCell
              label={t("strategy.fireGap")}
              value={fmtMoney(Math.max(0, data.target_principal - data.current_net_worth), false, true)}
            />
            <StatCell
              label={t("strategy.fireYears")}
              value={data.years_to_fire == null ? "—" : `${data.years_to_fire}`}
              sub={
                data.years_to_fire == null
                  ? data.reachable === false
                    ? t("strategy.fireUnreachable")
                    : t("strategy.fireNoSaving")
                  : t("strategy.fireYearsUnit")
              }
            />
          </div>
          <div className="mt-3">
            <div className="mb-1 flex justify-between text-[11px] text-muted-foreground">
              <span>{t("strategy.fireProgress", { p: data.progress_pct ?? 0 })}</span>
              <span>
                {t("strategy.fireSavingsRate")} {data.savings_rate_pct}%
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-muted">
              <div
                className={cn("h-full rounded-full", reached ? "bg-emerald-500" : "bg-primary")}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
            {t("strategy.fireNote", {
              w: data.withdrawal_rate_pct,
              r: data.expected_return_pct,
            })}
          </p>
        </>
      )}
    </Card>
  );
}

/** 策略页主体 */
export function StrategyPage() {
  const { t } = useI18n();
  const { dashboard } = useDashboard();
  const [benchmark, setBenchmark] = useState("sh000300");

  if (!dashboard) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  const hasHoldings = dashboard.positions.some((p) => p.kind !== "现金");
  if (!hasHoldings) {
    return (
      <Card>
        <EmptyState
          illustration="holdings"
          title={t("strategy.emptyTitle")}
          desc={t("strategy.emptyDesc")}
        />
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      <RiskSection benchmark={benchmark} onBenchmark={setBenchmark} />
      <div className="grid gap-3 xl:grid-cols-2">
        <RebalanceSection />
        <ValuationSection />
      </div>
      <DcaSection />
      <FireSection />
    </div>
  );
}

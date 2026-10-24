import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CalendarClock, CheckCircle2, ChevronDown, CreditCard, HeartPulse, LineChart, MessageSquare, NotebookPen, RefreshCw, Send } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton, DashboardSkeleton } from "@/components/ui/skeleton";
import { StatCell } from "@/components/ui/stat";
import { ProgressBar } from "@/components/ui/progress-bar";
import { EmptyState } from "@/components/ui/empty-state";
import { AlertBanner } from "@/components/ui/alert";
import { PanelSm } from "@/components/ui/panel";
import { useEChart, usePalette, axisLabelColor } from "@/lib/charts";
import { useTheme } from "@/lib/theme";
import { useI18n } from "@/lib/i18n";
import { api } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";
import { useMutate } from "@/lib/use-mutate";
import { store, useDashboard, useBootstrap } from "@/lib/store";
import { fmtMoney, fmtPct, fmtMonth, getMoneyLocale, pnlClass } from "@/lib/format";
import { useSubscriptionsOverview } from "@/lib/use-subs-overview";
import { SmartEvalCard } from "@/components/SmartEvalCard";
import { PositionsTable } from "@/components/PositionsTable";
import { HealthCheckDialog } from "@/components/HealthCheckDialog";
import { IndicesStrip } from "@/components/IndicesStrip";
import { NetWorthCard } from "@/components/dashboard/NetWorthCard";
import { HealthScoreCard } from "@/components/dashboard/HealthScoreCard";
import { ReturnsCard } from "@/components/dashboard/ReturnsCard";
import { CashflowWaterfallCard } from "@/components/dashboard/CashflowWaterfallCard";
import { ExpenseTreemapCard } from "@/components/dashboard/ExpenseTreemapCard";
import { SubscriptionTimelineCard } from "@/components/dashboard/SubscriptionTimelineCard";
import { HealthRadarCard } from "@/components/dashboard/HealthRadarCard";
import { GoalProgressCard } from "@/components/dashboard/GoalProgressCard";
import type { DashboardData, TrendMonth, BudgetUsage } from "@/lib/types";

/** 置顶快捷记账条：一句话记账（AI 解析 + 规则兜底），总览常驻 */
export function QuickLedgerBar() {
  const { t: tr } = useI18n();
  const [text, setText] = useState("");
  const nl = useMutate<string, { source: string; transaction: { item: string; category: string; amount: number } }>({
    fn: (q) =>
      api<{ source: string; transaction: { item: string; category: string; amount: number } }>("/api/nl-add", {
        method: "POST",
        body: JSON.stringify({ text: q }),
      }),
    key: "dash.ledgerSaved",
    vars: (_a, res) => ({ c: res.transaction.category, v: fmtMoney(res.transaction.amount) }),
    errorKey: "dash.ledgerFail",
    onSettled: (_res, e) => {
      if (!e) setText("");
    },
  });
  const submit = () => {
    const v = text.trim();
    if (!v || nl.isPending) return;
    void nl.mutate(v);
  };
  return (
    <PanelSm className="flex items-center gap-2 px-3 py-2.5">
      <NotebookPen className="w-4 h-4 text-primary shrink-0" />
      <input
        className="min-w-0 flex-1 bg-transparent text-sm focus:outline-none placeholder:text-muted-foreground"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") submit();
        }}
        placeholder={tr("dash.quickLedgerPh")}
        maxLength={80}
        aria-label={tr("dash.quickLedger")}
      />
      {nl.isPending ? (
        <span className="shrink-0 text-xs text-muted-foreground">{tr("dash.ledgerParsing")}</span>
      ) : (
        <Button size="sm" disabled={!text.trim()} onClick={submit}>
          <Send className="w-3.5 h-3.5" /> {tr("dash.quickLedger")}
        </Button>
      )}
    </PanelSm>
  );
}

/** 持仓速览：Top5 非现金持仓（市值 + 今日盈亏 + 累计盈亏） */
export function TopHoldings({ dashboard }: { dashboard: DashboardData }) {
  const { t: tr } = useI18n();
  const rows = dashboard.positions.filter((p) => p.kind !== "现金").slice(0, 5);
  if (!rows.length) return null;
  // 行情来源醒目标注：非东财实时价（快照/降级）时显示「离线估值」徽标
  const src = dashboard.source.quotes ?? "";
  const isSnapshot = src.includes("快照");
  return (
    <Card className="p-[var(--card-pad)]">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium">{tr("dash.topHoldings")}</span>
        <span className="flex items-center gap-2">
          {isSnapshot && (
            <span className="rounded bg-muted px-1.5 py-0.5 text-[11px] font-medium leading-none text-muted-foreground">
              {tr("dash.offlineValuation")}
            </span>
          )}
          <span className="text-[11px] text-muted-foreground">
            {tr("dash.todayPnl")} · {tr("dash.totalPnl")} · {tr("dash.holdingsValue")}
          </span>
        </span>
      </div>
      <ul className="space-y-2">
        {rows.map((p) => {
          const day = dashboard.today_pnl.items[p.symbol];
          return (
            <li key={p.symbol} className="flex items-center justify-between gap-2 text-sm">
              <span className="min-w-0 truncate">
                {p.name}
                <span className="ml-1.5 text-xs text-muted-foreground">{p.kind}</span>
              </span>
              <span className="flex shrink-0 items-center gap-2.5 tabular-nums">
                <span className={pnlClass(day)}>{day != null ? fmtMoney(day, true, true) : "—"}</span>
                <span className={`w-16 text-right ${pnlClass(p.pnl)}`}>{fmtMoney(p.pnl, true, true)}</span>
                <span className="w-20 text-right text-muted-foreground">{fmtMoney(p.market_value, false, true)}</span>
              </span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

export function RiskBanner({ flags }: { flags: DashboardData["flags"] }) {
  const { t: tr } = useI18n();
  /* 摘掉的配饰：原来这里是一只和统计卡/待扣提醒同款的白色圆角卡。
     4 项风险自己会说话，不需要第三个同款盒子——改成一段带竖线锚的列表。 */
  if (!flags.length) {
    return (
      <div className="flex items-center gap-2 border-l-2 border-emerald-500/60 pl-3 py-1 text-sm">
        <CheckCircle2 className="w-4 h-4 text-success shrink-0" />
        <span className="text-success text-balance">{tr("dash.noRisk")}</span>
      </div>
    );
  }
  return (
    <div className="border-l-2 border-amber-500/70 pl-3 py-1">
      <div className="flex items-center gap-2 text-sm font-medium text-amber-700 dark:text-amber-400">
        <AlertTriangle className="w-4 h-4 shrink-0" />
        {tr("dash.riskCount", { n: flags.length })}
      </div>
      <ul className="mt-1.5 space-y-1">
        {flags.map((f, i) => (
          <li key={i} className="flex gap-2 text-sm text-foreground/85">
            <span className="mt-1.5 w-1 h-1 rounded-full bg-amber-500 shrink-0" />
            <span className="text-balance">{f.text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** 近期待扣提醒：今天到期（红）与 3 天内到期（黄）的负债与订阅。 */
export function DueSoonStrip({ dashboard }: { dashboard: DashboardData }) {
  const { t: tr } = useI18n();
  const today = new Date();
  const day = today.getDate();
  const monthLabel = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
  const items = [
    ...dashboard.debts.items.map((d) => ({ name: d.name, amount: d.monthly, due: d.due_day ?? "", kind: "还款" as const })),
    ...dashboard.subscriptions.items.map((s) => ({ name: s.name, amount: s.monthly, due: s.due_day ?? "", kind: "扣款" as const })),
  ].filter((i) => i.due && /^\d{1,2}$/.test(i.due));

  const dueToday = items.filter((i) => Number(i.due) === day);
  // 跨月：本月已过号的扣款日滚动到下月，按"距下次扣款天数"计算（含月末→月初）
  const daysInMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate();
  const daysUntil = (due: number) => (due >= day ? due - day : daysInMonth - day + due);
  const dueSoon = items.filter((i) => {
    const d = daysUntil(Number(i.due));
    return d > 0 && d <= 3;
  });
  if (dueToday.length === 0 && dueSoon.length === 0) return null;
  const totalToday = dueToday.reduce((s, i) => s + i.amount, 0);
  const totalSoon = dueSoon.reduce((s, i) => s + i.amount, 0);

  return (
    /* 待扣提醒：账本的一行行条目，卡中卡去掉，改用左侧色条区分紧急度 */
    <PanelSm className="px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-sm font-medium mb-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-red-500 inline-block" />
        {tr("dash.upcoming", { m: monthLabel })}
      </div>
      <div className="space-y-1.5">
        {dueToday.length > 0 && (
          <div className="border-l-2 border-red-500/70 pl-2.5">
            <div className="text-xs font-medium text-red-600 dark:text-red-400">{tr("dash.dueToday", { v: fmtMoney(totalToday, false) })}</div>
            <div className="mt-0.5 flex gap-x-3 gap-y-0.5 flex-wrap text-xs text-muted-foreground">
              {dueToday.map((i) => (
                <span key={i.name} className="tabular-nums">
                  {i.name} {fmtMoney(i.amount, false)}（{tr("dash.dueOn", { d: i.due })} {i.kind === "还款" ? tr("dash.repay") : tr("dash.charge")}）
                </span>
              ))}
            </div>
          </div>
        )}
        {dueSoon.length > 0 && (
          <div className="border-l-2 border-amber-500/70 pl-2.5">
            <div className="text-xs font-medium text-amber-600 dark:text-amber-400">{tr("dash.dueSoon", { v: fmtMoney(totalSoon, false) })}</div>
            <div className="mt-0.5 flex gap-x-3 gap-y-0.5 flex-wrap text-xs text-muted-foreground">
              {dueSoon.map((i) => (
                <span key={i.name} className="tabular-nums">
                  {i.name} {fmtMoney(i.amount, false)}（{Number(i.due) < day ? tr("dash.nextMonth") : ""}{tr("dash.dueOn", { d: i.due })} {i.kind === "还款" ? tr("dash.repay") : tr("dash.charge")}）
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </PanelSm>
  );
}
export function AlertLine({ budget, goals }: { budget: BudgetUsage | null; goals: DashboardData["goals"] }) {
  const { t: tr } = useI18n();
  const today = new Date();
  const monthLabel = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
  const overBudget = budget && budget.usage.total_budget > 0 && budget.usage.total_pct >= 100;
  const expiring = goals.filter((g) => !g.done && g.deadline && g.deadline.startsWith(monthLabel));
  if (!overBudget && expiring.length === 0) return null;
  return (
    <PanelSm className="px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-sm font-medium mb-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-500 inline-block" />
        {tr("dash.alerts")}
      </div>
      <div className="space-y-1.5">
        {overBudget && (
          <div className="border-l-2 border-red-500/70 pl-2.5 text-xs">
            <span className="font-medium text-red-600 dark:text-red-400">
              {tr("dash.budgetOver", { m: budget!.month, p: budget!.usage.total_pct })}
            </span>
            <span className="ml-2 text-muted-foreground tabular-nums">
              {fmtMoney(budget!.usage.total_spent, false)} / {fmtMoney(budget!.usage.total_budget, false)}
            </span>
          </div>
        )}
        {expiring.map((g) => (
          <div key={g.name} className="border-l-2 border-amber-500/70 pl-2.5 text-xs">
            <span className="text-amber-600 dark:text-amber-400">{tr("dash.goalDue", { n: g.name })}</span>
            <span className="ml-2 text-muted-foreground tabular-nums">
              {fmtMoney(g.saved, false)} / {fmtMoney(g.target, false)}
            </span>
          </div>
        ))}
      </div>
    </PanelSm>
  );
}

export function AssetPie({ data }: { data: DashboardData }) {
  const ref = useRef<HTMLDivElement>(null);
  const palette = usePalette();
  const { resolved } = useTheme();
  const option = useMemo(() => {
    const items = data.concentration.by_asset.filter((a) => a.pct > 0.5);
    return {
      tooltip: { trigger: "item", triggerOn: "click", renderMode: "richText", confine: true, formatter: `{b}\n${getMoneyLocale() === "zh" ? "占比" : "Share"} {d}%` },
      legend: {
        type: "scroll",
        bottom: 0,
        textStyle: { fontSize: 11, color: axisLabelColor(resolved) },
        icon: "circle",
        itemWidth: 8,
        itemHeight: 8,
      },
      series: [
        {
          type: "pie",
          radius: ["42%", "68%"],
          center: ["50%", "44%"],
          avoidLabelOverlap: true,
          itemStyle: { borderRadius: 4, borderColor: "transparent", borderWidth: 2 },
          label: { show: false },
          emphasis: { label: { show: true, fontSize: 12, fontWeight: 600, color: axisLabelColor(resolved) } },
          data: items.map((a, i) => ({ name: a.name, value: a.pct, itemStyle: { color: palette[i % palette.length] } })),
        },
      ],
      grid: { containLabel: true },
    };
  }, [data, palette, resolved]);
  useEChart(ref, option, [option]);
  return <div ref={ref} className="h-52 w-full" />;
}

export function ExpenseBar({ data }: { data: DashboardData }) {
  const ref = useRef<HTMLDivElement>(null);
  const palette = usePalette();
  const { resolved } = useTheme();
  const option = useMemo(() => {
    const cats = data.cashflow.by_category.slice(0, 6);
    return {
      tooltip: { trigger: "axis", triggerOn: "click", renderMode: "richText", confine: true, axisPointer: { type: "shadow" } },
      grid: { left: 8, right: 12, top: 14, bottom: 4, containLabel: true },
      xAxis: {
        type: "value",
        axisLabel: { fontSize: 10, color: axisLabelColor(resolved), formatter: (v: number) => (v >= 10000 ? `${(v / 10000).toFixed(1)}${getMoneyLocale() === "zh" ? "万" : "k"}` : `${v}`) },
        splitLine: { lineStyle: { type: "dashed", color: "hsl(var(--border))" } },
      },
      yAxis: { type: "category", data: cats.map((c) => c.category), axisLabel: { fontSize: 11, color: axisLabelColor(resolved) } },
      series: [
        {
          type: "bar",
          data: cats.map((c, i) => ({
            value: c.amount,
            itemStyle: { color: palette[(i + 2) % palette.length], borderRadius: [0, 4, 4, 0] },
          })),
          barWidth: 14,
          label: { show: true, position: "right", fontSize: 10, color: axisLabelColor(resolved), formatter: (p: { value: number }) => fmtMoney(p.value) },
        },
      ],
    };
  }, [data, palette, resolved]);
  useEChart(ref, option, [option]);
  return <div ref={ref} className="h-52 w-full" />;
}

/** 月度收支趋势（柱状：收入 / 支出，折线：结余） */
export function TrendChart({ trend }: { trend: TrendMonth[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const { resolved } = useTheme();
  const palette = usePalette();
  const option = useMemo(() => {
    const months = trend.map((t) => fmtMonth(t.month));
    return {
      tooltip: { trigger: "axis", triggerOn: "click", renderMode: "richText", confine: true },
      legend: { top: 0, textStyle: { fontSize: 11, color: axisLabelColor(resolved) } },
      grid: { left: 8, right: 8, top: 30, bottom: 4, containLabel: true },
      xAxis: { type: "category", data: months, axisLabel: { fontSize: 10, color: axisLabelColor(resolved) } },
      yAxis: {
        type: "value",
        axisLabel: { fontSize: 10, color: axisLabelColor(resolved), formatter: (v: number) => (v >= 10000 ? `${(v / 10000).toFixed(1)}${getMoneyLocale() === "zh" ? "万" : "k"}` : `${v}`) },
        splitLine: { lineStyle: { type: "dashed", color: "hsl(var(--border))" } },
      },
      series: [
        {
          name: getMoneyLocale() === "zh" ? "收入" : "Income",
          type: "bar",
          data: trend.map((t) => t.income),
          itemStyle: { color: palette[2], borderRadius: [4, 4, 0, 0] },
          barWidth: 12,
        },
        {
          name: getMoneyLocale() === "zh" ? "支出" : "Expense",
          type: "bar",
          data: trend.map((t) => t.expense),
          itemStyle: { color: palette[5], borderRadius: [4, 4, 0, 0] },
          barWidth: 12,
        },
        {
          name: getMoneyLocale() === "zh" ? "结余" : "Net",
          type: "line",
          data: trend.map((t) => t.net),
          symbolSize: 5,
          itemStyle: { color: palette[0] },
          lineStyle: { width: 2 },
        },
      ],
    };
  }, [trend, resolved, palette]);
  useEChart(ref, option, [option]);
  return <div ref={ref} className="h-56 w-full" />;
}

export function EmergencyCard({ data }: { data: DashboardData }) {
  const { t: tr } = useI18n();
  const em = data.emergency;
  const pct = em.has_data && em.target_months ? Math.min(100, (em.months_covered / em.target_months) * 100) : 0;
  return (
    <Card className="p-[var(--card-pad)]">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium">{tr("dash.emergency")}</div>
        {em.has_data ? (
          <Badge variant={em.ok ? "ok" : "warn"}>{em.ok ? tr("dash.onTrack") : tr("dash.short")}</Badge>
        ) : (
          <Badge variant="muted">{tr("dash.noData")}</Badge>
        )}
      </div>
      <div className="mt-3 flex items-baseline gap-1">
        <span className="text-2xl font-bold tabular-nums">{em.has_data ? em.months_covered : "—"}</span>
        <span className="text-sm text-muted-foreground">
          {em.has_data ? tr("dash.emergencyMonths", { n: em.months_covered, target: em.target_months }) : tr("dash.estUnknown")}
        </span>
      </div>
      <div className="mt-2 h-2 rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full ${em.has_data && !em.ok ? "bg-amber-500" : "bg-success"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="mt-2 text-xs text-muted-foreground">
        {tr("dash.cashVsEssential", { c: fmtMoney(em.cash), e: fmtMoney(em.essential_monthly) })}
      </div>
    </Card>
  );
}

/** 本月预算：总预算进度 + 剩余日均 + 分类进度；未设置预算时不占位
 *  数据由 Dashboard 主组件统一拉取（避免双请求 /api/budgets），本组件只渲染 */
export function BudgetCard({
  budget,
  onOpenSettings,
}: {
  budget: BudgetUsage | null;
  onOpenSettings?: () => void;
}) {
  const { t: tr } = useI18n();

  if (!budget || budget.usage.total_budget <= 0) {
    return (
      <Card className="p-4 flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg bg-muted/60 flex items-center justify-center">
          <CreditCard className="w-4 h-4 text-muted-foreground" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium">{tr("budget.noBudgetTitle")}</div>
          <div className="text-xs text-muted-foreground truncate">{tr("budget.noBudgetHint")}</div>
        </div>
        {onOpenSettings && (
          <button onClick={onOpenSettings} className="text-xs text-primary hover:underline shrink-0">
            {tr("budget.set")}
          </button>
        )}
      </Card>
    );
  }
  const u = budget.usage;
  const pct = Math.max(0, Math.min(100, u.total_pct));
  const color = u.over ? "bg-red-500" : u.total_pct >= 85 ? "bg-amber-500" : u.total_pct >= 60 ? "bg-amber-400" : "bg-emerald-500";
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <CreditCard className="w-4 h-4 text-primary" />
          <span>{tr("budget.usageTitle", { month: budget.month })}</span>
          {u.over && (
            <span className="text-[11px] font-semibold px-1.5 py-0.5 rounded bg-red-500/15 text-red-500">{tr("budget.overBadge")}</span>
          )}
        </div>
        <span className={`text-xs font-mono ${u.over ? "text-red-500" : "text-muted-foreground"}`}>{u.total_pct}%</span>
      </div>
      <ProgressBar pct={pct} colorClass={color} className="h-2" />
      <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
        <span>{tr("budget.usedOf", { used: fmtMoney(u.total_spent), total: fmtMoney(u.total_budget) })}</span>
        <span>{u.over ? tr("budget.overBy", { over: fmtMoney(u.total_spent - u.total_budget) }) : tr("budget.left", { left: fmtMoney(u.left) })}</span>
      </div>
      {u.categories.length > 0 && (
        <div className="mt-3 grid grid-cols-1 gap-1.5">
          {u.categories.slice(0, 4).map((c) => (
            <div key={c.category} className="flex items-center gap-2">
              <span className="text-[11px] text-foreground truncate w-16 shrink-0">{c.category}</span>
              <ProgressBar
                pct={Math.max(0, Math.min(100, c.pct))}
                colorClass={c.over ? "bg-red-500" : c.pct >= 85 ? "bg-amber-500" : c.pct >= 60 ? "bg-amber-400" : "bg-emerald-500"}
                className="flex-1 h-1.5"
              />
              <span className="text-[11px] text-muted-foreground shrink-0 w-16 text-right">
                {fmtMoney(c.spent)} / {fmtMoney(c.budget)}
              </span>
            </div>
          ))}
          {u.categories.length > 4 && <div className="text-[11px] text-muted-foreground text-center">{tr("budget.moreCats", { n: u.categories.length - 4 })}</div>}
        </div>
      )}
    </Card>
  );
}

/** 订阅待缴卡片：月度合计 + N 内到期订阅列表（ upfront 弹窗 7 天内，每次打开刷新）。 */
export function SubscriptionsCard({
  items,
}: {
  items: { name: string; monthly: number; note: string; due_day: string }[];
}) {
  const { t: tr } = useI18n();
  const overview = useSubscriptionsOverview(items);
  const monthlyTotal = overview.monthly_total;
  const upcoming = overview.upcoming;

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2 text-sm font-medium">
          <CalendarClock className="w-4 h-4 text-primary" />
          <span>{tr("subscriptions.cardTitle")}</span>
        </div>
        <span className="text-xs text-muted-foreground">{tr("subscriptions.monthlyTotal", { v: fmtMoney(monthlyTotal) })}</span>
      </div>
      {upcoming.length === 0 ? (
        <div className="text-xs text-muted-foreground py-2 flex items-center gap-1.5">
          <CreditCard className="w-3.5 h-3.5" />
          {tr("subscriptions.noneDue", { days: 7 })}
        </div>
      ) : (
        <ul className="mt-2 space-y-1">
          {upcoming.slice(0, 4).map((r) => (
            <li key={r.name} className="flex items-center justify-between text-xs">
              <span className="truncate mr-2">
                <span className="font-medium">{r.name}</span>
                <span className="text-muted-foreground"> · {fmtMoney(r.monthly)}</span>
              </span>
              <span
                className={`text-[11px] font-semibold px-1.5 py-0.5 rounded shrink-0 ${
                  r.days_until === 0
                    ? "bg-red-500/15 text-red-500"
                    : r.days_until <= 2
                      ? "bg-amber-500/15 text-amber-600"
                      : "bg-muted text-muted-foreground"
                }`}
              >
                {r.days_until === 0 ? tr("subscriptions.dueToday") : tr("subscriptions.dueIn", { n: r.days_until })}
              </span>
            </li>
          ))}
          {upcoming.length > 4 && <li className="text-[11px] text-muted-foreground text-center">{tr("subscriptions.moreItems", { n: upcoming.length - 4 })}</li>}
        </ul>
      )}
    </Card>
  );
}

/** 目标卡：前 3 个目标进度 + 财务体检入口；无目标时只留体检按钮 */
export function GoalsCard({ goals, net }: { goals: DashboardData["goals"]; net: number }) {
  const { t: tr } = useI18n();
  const [healthOpen, setHealthOpen] = useState(false);
  const top = goals.filter((g) => !g.done).slice(0, 3);

  return (
    <Card className="p-[var(--card-pad)]">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium">{tr("dash.goals")}</div>
        <Button size="sm" variant="outline" className="h-6 px-2 text-xs" onClick={() => setHealthOpen(true)}>
          <HeartPulse className="w-3.5 h-3.5" /> {tr("dash.healthCheck")}
        </Button>
      </div>
      {top.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">
          {goals.length > 0
            ? tr("dash.allGoalsDone")
            : tr("dash.noGoals")}
        </p>
      ) : (
        <div className="mt-3 space-y-2.5">
          {top.map((g) => (
            <div key={g.name}>
              <div className="flex items-center justify-between text-xs">
                <span className="truncate pr-2">{g.name}</span>
                <span className="tabular-nums text-muted-foreground shrink-0">{g.pct}%</span>
              </div>
              <ProgressBar pct={g.pct} />
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                {fmtMoney(g.saved, false)} / {fmtMoney(g.target, false)}
                {g.monthly_suggest != null && ` · ${tr("dash.suggestMonthly")} ${fmtMoney(g.monthly_suggest, false)}`}
                {g.gap > 0 && net > 0 && ` · ${tr("dash.monthsToGoal", { n: Math.max(1, Math.ceil(g.gap / net)) })}`}
              </div>
            </div>
          ))}
        </div>
      )}
      <HealthCheckDialog open={healthOpen} onOpenChange={setHealthOpen} />
    </Card>
  );
}

export function Dashboard({
  onGoLedger,
  onGoMarket,
  onGoChat,
  onGoSettings,
}: {
  onGoLedger?: () => void;
  onGoMarket?: () => void;
  onGoChat?: () => void;
  onGoSettings?: () => void;
} = {}) {
  const { dashboard, loading } = useDashboard();
  const { bootstrap } = useBootstrap();
  const { t: tr } = useI18n();
  const [detailsOpen, setDetailsOpen] = useState(false);
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const compact = (bootstrap?.settings.compact_numbers ?? "on") === "on";
  const { data: budgetData } = useQuery({
    queryKey: ["budgets"],
    queryFn: async () => api<BudgetUsage>("/api/budgets"),
    enabled: !!dashboard,
  });
  const budget = budgetData ?? null;
  const { data: trendData } = useQuery({
    queryKey: ["trend", 6],
    queryFn: async () => (await api<{ months: TrendMonth[] }>("/api/trend?months=6")).months,
    enabled: !!dashboard,
  });
  const trend = trendData ?? null;
  const { data: subsData } = useQuery({
    queryKey: ["subscriptions"],
    queryFn: async () =>
      api<{ subscriptions: { name: string; monthly: number; note: string; due_day: string }[] }>(
        "/api/subscriptions",
      ).then((r) => r.subscriptions),
    enabled: !!dashboard,
  });
  const subsRaw = subsData ?? [];

  // details toggle：只挂载时 attach 一次，与数据刷新无关
  useEffect(() => {
    const el = detailsRef.current;
    if (!el) return;
    const onToggle = () => setDetailsOpen(el.open);
    setDetailsOpen(el.open);
    el.addEventListener("toggle", onToggle);
    return () => el.removeEventListener("toggle", onToggle);
  }, [dashboard !== null]);

  if (loading && !dashboard) {
    return <DashboardSkeleton />;
  }
  if (!dashboard) {
    return (
      <div className="p-8 text-center">
        <p className="text-sm text-muted-foreground mb-3">{tr("dash.loadFail")}</p>
        <Button variant="outline" size="sm" onClick={() => store.refreshDashboard()}>
          <RefreshCw className="w-4 h-4" /> {tr("dash.retry")}
        </Button>
      </div>
    );
  }

  const t = dashboard.totals;
  const cf = dashboard.cashflow;
  const cash = dashboard.positions.filter((p) => p.kind === "现金").reduce((s, p) => s + p.cost, 0);
  const todayPnl = dashboard.today_pnl.total;
  // 今日收益率的分母要用「非现金持仓总成本」：后端 dashboard.positions[].cost
  // 已经是总成本（单价 × 股数），这里**不能再乘 shares**——
  // 重复相乘会把分母放大到股数量级，导致今日收益率恒为 +0.00%。
  const nonCashCost = dashboard.positions
    .filter((p) => p.kind !== "现金")
    .reduce((s, p) => s + p.cost, 0);
  // 是否有非现金持仓：无持仓时「资产分布」占满整行，避免两列 grid 只渲染一列导致右侧大留白
  const hasNonCash = dashboard.positions.some((p) => p.kind !== "现金");

  // 空数据降级为引导：不渲染零值统计卡与风险横幅（零值 + 误报警是新用户劝退组合）。
  // 新用户首启即此态：一句话记账条 + 开始引导 + 大盘，聊天式起步。
  if (dashboard.positions.length === 0 && dashboard.transactions.length === 0) {
    return (
      <div className="space-y-3">
        <QuickLedgerBar />
        <Card className="p-6 text-center">
          <EmptyState
            mode="card"
            illustration="data"
            title={tr("dash.emptyTitle")}
            desc={tr("dash.emptyDesc")}
            actions={
              <div className="flex flex-wrap justify-center gap-2">
                <Button size="sm" onClick={() => onGoLedger?.()}>
                  <NotebookPen className="w-4 h-4" /> {tr("dash.goLedger")}
                </Button>
                <Button size="sm" variant="outline" onClick={() => onGoMarket?.()}>
                  <LineChart className="w-4 h-4" /> {tr("dash.emptyHoldingBtn")}
                </Button>
                <Button size="sm" variant="outline" onClick={() => onGoChat?.()}>
                  <MessageSquare className="w-4 h-4" /> {tr("dash.emptyAskBtn")}
                </Button>
              </div>
            }
          />
        </Card>
        <IndicesStrip indices={dashboard.indices} />
        <p className="px-2 text-xs text-muted-foreground">
          {tr("dash.demoHint")}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* 示例数据横幅：首启种入的示例数据必须明说，避免被当成自己的真实数据 */}
      {dashboard.source.seeded && (
        <AlertBanner
          tone="warn"
          className="rounded-[var(--radius)]"
          action={
            <Button variant="outline" size="sm" className="h-6 px-2" onClick={() => onGoLedger?.()}>
              {tr("dash.firstEntry")}
            </Button>
          }
        >
          {tr("dash.demoBanner")}
        </AlertBanner>
      )}
      {/* 置顶快捷记账条：记一笔就走，AI 自动分类 */}
      <QuickLedgerBar />

      {/* 净值总览：资产 / 负债 / 组成饼图，一眼看到净资产 */}
      <NetWorthCard />

      {/* 指数行情条：大盘一眼可读 */}
      <IndicesStrip indices={dashboard.indices} />

      {/* 资产抬头：总资产（突出） / 今日盈亏 / 累计盈亏 / 可用现金。
       *  总资产用 emphasis 拉开层级；子行只放同属性关键参照（成本/收益率/今日净现金流），
       *  次级信息收进明细区，首屏更干净（对标 GPT：核心数字突出、其余统一） */}
      <div className="grid grid-cols-2 gap-y-3 rounded-[var(--radius)] border border-border bg-card px-3 py-2 sm:grid-cols-4 sm:divide-x sm:divide-border/70">
        <StatCell label={tr("dash.totalAssets")} value={fmtMoney(t.total_market_value, false, compact)} sub={`${tr("dash.costBasis")} ${fmtMoney(t.total_cost, false, compact)}`} emphasis />
        <StatCell
          label={tr("dash.todayPnl")}
          value={fmtMoney(todayPnl, true, compact)}
          sub={fmtPct(todayPnl && nonCashCost ? (todayPnl / nonCashCost) * 100 : 0, true)}
          tone={todayPnl >= 0 ? "up" : "down"}
        />
        <StatCell label={tr("dash.totalPnl")} value={fmtMoney(t.total_pnl, true, compact)} sub={fmtPct(t.total_pnl_pct, true)} tone={t.total_pnl >= 0 ? "up" : "down"} />
        <StatCell label={tr("dash.cashAvailable")} value={fmtMoney(cash, false, compact)} sub={`${cf.month} ${tr("dash.net")} ${fmtMoney(cf.net, true, compact)}`} />
      </div>

      {/* 健康评分 + 投资收益：双列卡片，一眼看懂财务健康与收益 */}
      <div className="grid gap-3 sm:grid-cols-2">
        <HealthScoreCard />
        <ReturnsCard months={6} />
      </div>

      {/* 现金流与支出结构：瀑布看"钱从哪来到哪去"，树图看"哪类支出最大" */}
      <div className="grid gap-3 lg:grid-cols-2">
        <CashflowWaterfallCard />
        <ExpenseTreemapCard />
      </div>

      {/* 健康五维 + 订阅扣款时间线 */}
      <div className="grid gap-3 lg:grid-cols-2">
        <HealthRadarCard />
        <SubscriptionTimelineCard />
      </div>

      {/* 首页评估：预算/订阅/债务/目标/现金流 → 结构化行动项 */}
      <SmartEvalCard />

      {/* 本月预算 + 订阅待缴（同一行，节省纵向空间） */}
      <div className="grid gap-3 sm:grid-cols-2">
        <BudgetCard budget={budget} onOpenSettings={onGoSettings} />
        <SubscriptionsCard items={subsRaw} />
      </div>

      {/* 财务目标 + 体检入口 */}
      <GoalsCard goals={dashboard.goals ?? []} net={dashboard.cashflow.net} />

      {/* 财务目标进度总览 */}
      <GoalProgressCard />

      {/* 资产分布 + 持仓速览：一眼看懂钱在哪、今天怎么样 */}
      <div className="grid lg:grid-cols-2 gap-3">
        <Card className={`p-[var(--card-pad)] ${hasNonCash ? "" : "lg:col-span-2"}`}>
          <div className="text-sm font-medium mb-2">{tr("dash.assetMix")}</div>
          <AssetPie data={dashboard} />
        </Card>
        {hasNonCash && <TopHoldings dashboard={dashboard} />}
      </div>

      {/* 需要注意的事：待扣款 + 风险 + 预算/目标提醒，一眼看完 */}
      <div className="space-y-3">
        <DueSoonStrip dashboard={dashboard} />
        <AlertLine budget={budget} goals={dashboard.goals ?? []} />
        <RiskBanner flags={dashboard.flags} />
      </div>

      {/* 明细默认收起：图表 + 持仓，展开后才挂载（ECharts 运行时懒加载，不拖累首屏） */}
      <details ref={detailsRef} className="group rounded-[var(--radius)] border border-border bg-card">
        <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm font-medium">
          <span>
            {tr("dash.details")}
            <span className="ml-2 text-xs font-normal text-muted-foreground">
              {tr("dash.detailsSub")}
            </span>
          </span>
          <ChevronDown className="w-4 h-4 text-muted-foreground transition-transform group-open:rotate-180" />
        </summary>
        {detailsOpen && (
          <div className="space-y-3 border-t border-border p-3">
          <Card className="p-[var(--card-pad)]">
            <div className="text-sm font-medium mb-2">{tr("dash.spendingMix", { m: cf.month })}</div>
            <ExpenseBar data={dashboard} />
          </Card>

          <Card className="p-[var(--card-pad)]">
            <div className="text-sm font-medium mb-2">{tr("dash.trendTitle")}</div>
            {trend === null ? (
              <div className="h-56">
                <Skeleton className="h-full w-full" />
              </div>
            ) : trend.length > 0 ? (
              <TrendChart trend={trend} />
            ) : (
              <div className="h-40 flex items-center justify-center text-sm text-muted-foreground">
                {tr("dash.trendEmpty")}
              </div>
            )}
          </Card>

          <div className="grid lg:grid-cols-2 gap-3">
            <EmergencyCard data={dashboard} />
            <Card className="p-[var(--card-pad)]">
              <div className="flex items-center justify-between">
                <div className="text-sm font-medium">{tr("dash.debt")}</div>
                <Badge variant={dashboard.debts.dti_pct > 40 ? "warn" : "ok"}>
                  {tr("dash.dti", { n: dashboard.debts.dti_pct })}
                </Badge>
              </div>
              {dashboard.debts.items.length === 0 ? (
                <div className="mt-3 text-sm text-muted-foreground">{tr("dash.noDebt")}</div>
              ) : (
                <ul className="mt-3 space-y-2">
                  {dashboard.debts.items.map((d) => (
                    <li key={d.name} className="flex items-center justify-between text-sm">
                      <span>
                        {d.name}
                        <span className="text-xs text-muted-foreground ml-2">
                          {tr("dash.rate", { r: (d.rate * 100).toFixed(1) })}{d.due_day ? ` · ${tr("dash.dueOn", { d: d.due_day })} ${tr("dash.repay")}` : ""}
                        </span>
                      </span>
                      <span className="tabular-nums">{fmtMoney(d.monthly, false, compact)}{tr("dash.perMonth")}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          <Card className="p-[var(--card-pad)]">
            <div className="flex items-center justify-between mb-2">
              <div className="text-sm font-medium">{tr("dash.positions")}</div>
              <span className="text-xs text-muted-foreground">{dashboard.source.quotes}</span>
            </div>
            <PositionsTable rows={dashboard.positions} compact={compact} />
          </Card>
          </div>
        )}
      </details>
    </div>
  );
}

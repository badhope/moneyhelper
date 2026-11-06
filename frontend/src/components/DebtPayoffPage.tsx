/** 债务清偿规划页（v4.14）：雪崩 / 雪球对比、逐月时间线、可省利息。
 *
 * 为什么单独一页而不是塞进「记账 → 负债」标签：
 * 台账回答「我欠多少」（每天看），规划回答「先还哪笔、多久还清」（每次做决定看）。
 * 两类问题的心智模型不同，混在一起会让高频动作被低频表单挤走。
 *
 * 口径全部来自后端 calculations/debt_payoff.py 的确定性模拟，
 * 本页只负责输入额外还款额与展示，不在前端做任何除法或复利推算
 * （前端算一遍就会出现两套口径）。
 */

import { useMemo, useState } from "react";
import { ArrowRight, CalendarClock, CircleDollarSign, PiggyBank, TrendingDown } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { Segmented } from "@/components/ui/segmented";
import { useI18n } from "@/lib/i18n";
import { fmtMoney, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { usePayoffPlan } from "@/lib/use-payoff";
import type { PayoffCompare, PayoffCompareUnavailable, PayoffPlan } from "@/lib/use-payoff";

const METHOD_KEY = {
  avalanche: "debts.methodAvalanche",
  snowball: "debts.methodSnowball",
} as const;

export function DebtPayoffPage({ onGoLedger }: { onGoLedger?: () => void }) {
  const { t } = useI18n();
  const [extraInput, setExtraInput] = useState("2000");
  const [method, setMethod] = useState<"avalanche" | "snowball">("avalanche");
  // 输入防抖：用户连续敲数字时不发请求，停 400ms 才查
  const extra = useDebouncedValue(extraInput, 400);
  const parsedExtra = useMemo(() => {
    const n = Number(extra);
    return Number.isFinite(n) && n >= 0 ? n : 0;
  }, [extra]);

  const { data, isPending, error, compare } = usePayoffPlan(parsedExtra, method);

  if (isPending) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-24 w-full rounded-[var(--radius)]" />
        <Skeleton className="h-40 w-full rounded-[var(--radius)]" />
        <Skeleton className="h-64 w-full rounded-[var(--radius)]" />
      </div>
    );
  }

  if (error) {
    return (
      <Card className="p-[var(--card-pad)]">
        <div className="text-sm text-red-600 dark:text-red-400">
          {t("debts.loadError")}: {error instanceof Error ? error.message : String(error)}
        </div>
      </Card>
    );
  }

  if (!data || data.available === false) {
    return (
      <Card className="p-[var(--card-pad)]">
        <EmptyState
          mode="card"
          illustration="wallet"
          title={t("debts.emptyTitle")}
          desc={data?.reason ?? t("debts.emptyHint")}
          actions={
            onGoLedger ? (
              <button
                type="button"
                onClick={onGoLedger}
                className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-[12.5px] font-medium text-primary-foreground"
              >
                {t("debts.goLedger")} <ArrowRight className="h-3.5 w-3.5" />
              </button>
            ) : null
          }
        />
      </Card>
    );
  }

  const plan = data as PayoffPlan;

  return (
    <div className="space-y-3">
      {/* 控制条：额外还款额 + 方法切换 */}
      <Card className="p-[var(--card-pad)]">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[13.5px] font-semibold">{t("debts.title")}</div>
            <p className="mt-1 max-w-2xl text-[11.5px] leading-relaxed text-muted-foreground">
              {t("debts.intro")}
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-[11px] text-muted-foreground">{t("debts.extraLabel")}</span>
              <input
                type="number"
                inputMode="decimal"
                min={0}
                step={100}
                value={extraInput}
                onChange={(e) => setExtraInput(e.target.value)}
                className="h-9 w-32 rounded-lg border border-input bg-background px-2.5 text-[13px] tabular-nums focus:outline-none focus:ring-2 focus:ring-ring"
                aria-label={t("debts.extraLabel")}
              />
            </label>
            <Segmented
              size="sm"
              value={method}
              onChange={(v) => setMethod(v as "avalanche" | "snowball")}
              options={[
                { value: "avalanche", label: t("debts.methodAvalanche") },
                { value: "snowball", label: t("debts.methodSnowball") },
              ]}
            />
          </div>
        </div>
      </Card>

      {/* 结论条：还清时间 / 总利息 / 可省利息 */}
      {/* 移动端两列：四张卡纵向铺满会让「还清日期」这个最关键的结论被推出首屏 */}
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatCard
          icon={<CalendarClock className="h-4 w-4 text-primary" />}
          label={t("debts.debtFree")}
          value={plan.debt_free_date ?? "—"}
          sub={
            plan.warnings.length
              ? t("debts.cannotClear")
              : t("debts.monthsValue", { n: plan.months, y: plan.years })
          }
          tone={plan.warnings.length ? "danger" : "ok"}
        />
        <StatCard
          icon={<CircleDollarSign className="h-4 w-4 text-primary" />}
          label={t("debts.totalInterest")}
          value={plan.warnings.length ? "—" : fmtMoney(plan.total_interest)}
          sub={t("debts.monthlyBudget", { v: fmtMoney(plan.monthly_budget) })}
        />
        <StatCard
          icon={<TrendingDown className="h-4 w-4 text-success" />}
          label={t("debts.interestSaved")}
          value={plan.interest_saved == null ? "—" : fmtMoney(plan.interest_saved)}
          sub={
            plan.baseline_available && plan.baseline_interest != null
              ? t("debts.vsMinimum", { v: fmtMoney(plan.baseline_interest) })
              : t("debts.baselineUnavailable")
          }
          tone={plan.interest_saved == null ? undefined : "ok"}
        />
        <StatCard
          icon={<PiggyBank className="h-4 w-4 text-primary" />}
          label={t("debts.extra")}
          value={fmtMoney(plan.extra_payment)}
          sub={t("debts.perMonth")}
        />
      </div>

      {plan.warnings.length > 0 && (
        <Card className="border-amber-500/40 bg-amber-500/[0.06] p-[var(--card-pad)]">
          <div className="text-[12.5px] font-medium text-amber-700 dark:text-amber-400">
            {t("debts.warningTitle")}
          </div>
          <ul className="mt-1 space-y-0.5">
            {(plan.warning_codes?.length ? plan.warning_codes : []).map((w) => (
              <li
                key={w.code}
                className="text-[11.5px] leading-snug text-amber-700/90 dark:text-amber-400/90"
              >
                {msg(t, "debts.warn", w)}
              </li>
            ))}
            {/* 未知 code（后端新增但前端未更新）时退回后端中文原文，不吞掉告警 */}
            {!plan.warning_codes?.length &&
              plan.warnings.map((w) => (
                <li key={w} className="text-[11.5px] leading-snug text-amber-700/90 dark:text-amber-400/90">
                  {w}
                </li>
              ))}
          </ul>
        </Card>
      )}

      {/* 对比：两种方法的差额（只有拿到可用的 compare 数据才渲染） */}
      {isCompareReady(compare.data) && (
        <Card className="p-[var(--card-pad)]">
          <div className="text-[13px] font-semibold">{t("debts.compareTitle")}</div>
          <div className="mt-2 grid gap-3 sm:grid-cols-2">
            {(["avalanche", "snowball"] as const).map((k) => {
              const p = k === "avalanche" ? compare.data!.avalanche : compare.data!.snowball;
              const active = k === method;
              return (
                <div
                  key={k}
                  className={cn(
                    "rounded-lg border px-3 py-2",
                    active ? "border-primary/50 bg-primary/[0.05]" : "border-border",
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-[12.5px] font-medium">{t(METHOD_KEY[k])}</span>
                    {active && <Badge variant="ok">{t("debts.current")}</Badge>}
                  </div>
                  <dl className="mt-1.5 space-y-1 text-[11.5px]">
                    {/* 不可行的一方不能显示「月数 1 / 总利息」——那会被读成「1 个月还清」。
                        月数与利息在中断时只是「跑到第几个月」，不是还款计划。 */}
                    <div className="flex justify-between">
                      <dt className="text-muted-foreground">{t("debts.monthsLabel")}</dt>
                      <dd className="tabular-nums">
                        {p.warnings.length ? "—" : p.months}
                      </dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-muted-foreground">{t("debts.totalInterest")}</dt>
                      <dd className="tabular-nums">
                        {p.warnings.length ? "—" : fmtMoney(p.total_interest)}
                      </dd>
                    </div>
                    <div className="flex justify-between gap-2">
                      <dt className="shrink-0 text-muted-foreground">{t("debts.order")}</dt>
                      <dd className="truncate text-right" title={p.order.join(" → ")}>
                        {p.order.join(" → ")}
                      </dd>
                    </div>
                  </dl>
                </div>
              );
            })}
          </div>
          <p className="mt-2 text-[11.5px] leading-relaxed text-foreground/80">
            {msg(t, "debts.verdict", compare.data.verdict_code) || compare.data.verdict}
          </p>
        </Card>
      )}

      {/* 逐笔负债 + 利息占比 */}
      <Card className="p-[var(--card-pad)]">
        <div className="text-[13px] font-semibold">{t("debts.byDebt")}</div>
        <div className="mt-2 overflow-x-auto scroll-thin">
          <table className="w-full min-w-[520px] border-collapse text-[12px]">
            <thead>
              <tr className="border-b border-border text-left text-[11px] text-muted-foreground">
                <th className="py-1.5 pr-2 font-medium">{t("debts.colName")}</th>
                <th className="py-1.5 pr-2 text-right font-medium">{t("debts.colBalance")}</th>
                <th className="py-1.5 pr-2 text-right font-medium">{t("debts.colRate")}</th>
                <th className="py-1.5 pr-2 text-right font-medium">{t("debts.colMin")}</th>
                <th className="py-1.5 text-right font-medium">{t("debts.colClear")}</th>
              </tr>
            </thead>
            <tbody>
              {plan.debts.map((d) => {
                const ms = plan.milestones.find((m) => m.name === d.name);
                return (
                  <tr key={d.name} className="border-b border-border/40 last:border-0">
                    <td className="max-w-[16rem] truncate py-1.5 pr-2" title={d.name}>
                      {d.name}
                    </td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">{fmtMoney(d.balance)}</td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">
                      <span className={d.rate >= 0.15 ? "text-danger" : undefined}>
                        {fmtPct(d.rate * 100)}
                      </span>
                    </td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">{fmtMoney(d.min_payment)}</td>
                    <td className="py-1.5 text-right tabular-nums">
                      {ms ? (
                        <span title={t("debts.clearMonth", { n: ms.month })}>{ms.date}</span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {/* 时间线：按还清顺序列出里程碑 */}
      {plan.milestones.length > 0 && (
        <Card className="p-[var(--card-pad)]">
          <div className="text-[13px] font-semibold">{t("debts.timeline")}</div>
          <ol className="mt-2 space-y-0">
            {plan.milestones.map((m, i) => (
              <li key={`${m.name}-${m.month}`} className="relative flex gap-2.5 pb-2.5 last:pb-0">
                <span className="relative flex w-4 shrink-0 justify-center">
                  <span
                    className={cn(
                      "mt-1 h-2 w-2 rounded-full",
                      i === 0 ? "bg-success" : "bg-primary/60",
                    )}
                  />
                  {i < plan.milestones.length - 1 && (
                    <span className="absolute top-3 bottom-0 w-px bg-border" />
                  )}
                </span>
                <span className="min-w-0 text-[12px]">
                  <span className="font-medium">{m.name}</span>
                  <span className="ml-1.5 text-muted-foreground">
                    {m.date} · {t("debts.clearMonth", { n: m.month })}
                  </span>
                </span>
              </li>
            ))}
          </ol>
        </Card>
      )}

      <div className="space-y-0.5 px-1 text-[10.5px] leading-relaxed text-muted-foreground">
        {(plan.note_codes ?? []).map((n) => (
          <p key={n.code}>{msg(t, "debts.note", n)}</p>
        ))}
        {!plan.note_codes?.length && plan.notes.map((n) => <p key={n}>{n}</p>)}
        <p>{t("debts.disclaimer")}</p>
      </div>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  sub,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  tone?: "ok" | "danger";
}) {
  return (
    <Card className="p-[var(--card-pad)]">
      <div className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
        {icon}
        {label}
      </div>
      <div
        className={cn(
          "mt-1 text-lg font-semibold tabular-nums",
          tone === "danger" && "text-danger",
          tone === "ok" && "text-success",
        )}
      >
        {value}
      </div>
      {sub && <div className="mt-0.5 text-[11px] text-muted-foreground">{sub}</div>}
    </Card>
  );
}

/**
 * 把后端返回的结构化消息（{code, amount?}）翻成当前语言。
 *
 * 为什么不在后端拼文案：后端同时服务 web / CLI / MCP，只有 web 需要按语言切换；
 * 后端只给 code，翻译权归前端，才不会出现「英文界面里蹦出中文句子」。
 * 未知 code 返回空串，由调用方回退到后端原文（宁可显示中文也不能吞掉告警）。
 */
function msg(
  t: (k: string, vars?: Record<string, string | number>) => string,
  prefix: string,
  m: { code: string; amount?: number } | undefined,
): string {
  if (!m) return "";
  const key = `${prefix}.${m.code}`;
  const out = t(key, m.amount == null ? undefined : { amount: m.amount.toFixed(2) });
  return out === key ? "" : out;
}

/** POST 在负债被删空时返回 {available:false,reason}，此时没有 avalanche/snowball。 */
function isCompareReady(
  d: PayoffCompare | PayoffCompareUnavailable | undefined,
): d is PayoffCompare {
  return !!d && "avalanche" in d && "snowball" in d;
}

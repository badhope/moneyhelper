/** 月度结账复盘：账务工作区里的一个确定性视图。 */

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  CalendarCheck,
  CheckCircle2,
  ClipboardList,
  Copy,
  Download,
  RefreshCw,
  Wallet,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ProgressBar } from "@/components/ui/progress-bar";
import { StatTile } from "@/components/ui/stat";
import { copyText } from "@/lib/clipboard";
import { fmtMoney } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { useMonthlyReview } from "@/lib/use-review";
import { cn, errMsg } from "@/lib/utils";

function currentMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function money(v: number) {
  return fmtMoney(v, false, false);
}

function deltaText(t: (k: string, vars?: Record<string, string | number>) => string, n: number | null) {
  if (n == null) return undefined;
  if (n > 0) return t("review.deltaUp", { n: n.toFixed(1) });
  if (n < 0) return t("review.deltaDown", { n: n.toFixed(1) });
  return t("review.deltaFlat");
}

export function MonthlyReviewPage() {
  const { t, lang } = useI18n();
  const { toast } = useToast();
  const [month, setMonth] = useState(currentMonth);
  const q = useMonthlyReview(month, lang);
  const data = q.data;

  const summary = useMemo(() => {
    if (!data) return "";
    const lines = [
      `# ${t("review.summaryTitle")} ${data.month}`,
      "",
      data.headline,
      "",
      data.verdict,
      "",
      `- ${t("review.income")}: ${money(data.cashflow.income)}`,
      `- ${t("review.expense")}: ${money(data.cashflow.expense)}`,
      `- ${t("review.net")}: ${money(data.cashflow.net)}`,
      `- ${t("review.savings")}: ${data.cashflow.savings_rate}%`,
      `- ${t("review.budget")}: ${data.budget.total ? `${money(data.budget.spent)} / ${money(data.budget.total)}` : t("review.budgetNo")}`,
      `- ${t("review.anomalies")}: ${data.anomalies.count}`,
      "",
      `## ${t("review.actions")}`,
      ...data.actions.map((a, i) => `${i + 1}. ${a.title} — ${a.detail}`),
      "",
      data.disclaimer,
    ];
    return lines.join("\n");
  }, [data, t]);

  const copy = () => {
    if (!summary) return;
    if (copyText(summary)) toast(t("review.copied"), "ok");
    else toast(t("identity.copyFailed"), "error");
  };

  const exportJson = () => {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `moneyhelper-review-${data.month}-${data.fingerprint}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-3">
      <Card className="flex flex-wrap items-center justify-between gap-3 p-[var(--card-pad)]">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <CalendarCheck className="h-4 w-4" />
            </span>
            <div>
              <div className="text-[15px] font-semibold">{t("review.title")}</div>
              <div className="mt-0.5 max-w-2xl text-[11.5px] leading-relaxed text-muted-foreground">
                {t("review.subtitle")}
              </div>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            {t("review.month")}
            <input
              type="month"
              value={month}
              onChange={(e) => setMonth(e.target.value)}
              className="rounded-md border border-border bg-background px-2 py-1 text-[12px] text-foreground"
            />
          </label>
          {data && (
            <Badge variant={data.status === "in_progress" ? "warn" : "ok"} className="text-[10px]">
              {data.status === "in_progress" ? t("review.statusInProgress") : t("review.statusClosed")}
            </Badge>
          )}
          <Button size="sm" variant="outline" onClick={() => void q.refetch()} disabled={q.isFetching}>
            <RefreshCw className={cn("mr-1 h-3.5 w-3.5", q.isFetching && "animate-spin")} />
            {t("review.refresh")}
          </Button>
        </div>
      </Card>

      {q.isLoading && (
        <Card className="p-[var(--card-pad)]">
          <div className="h-56 animate-pulse rounded-lg bg-muted/30" />
        </Card>
      )}

      {q.isError && (
        <Card className="flex flex-wrap items-center justify-between gap-2 p-[var(--card-pad)]">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <AlertTriangle className="h-4 w-4 text-destructive" />
            {t("review.failed")}：{errMsg(q.error)}
          </div>
          <Button size="sm" variant="outline" onClick={() => void q.refetch()}>{t("review.retry")}</Button>
        </Card>
      )}

      {data && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/60 bg-card px-3 py-2">
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
              <span className="font-mono">{data.fingerprint}</span>
              <span>{data.period.start} → {data.period.as_of}</span>
              {data.cashflow.transaction_count === 0 && <Badge variant="warn">{t("review.empty")}</Badge>}
            </div>
            <div className="flex items-center gap-1.5">
              <Button size="sm" variant="ghost" onClick={copy}>
                <Copy className="mr-1 h-3.5 w-3.5" />{t("review.copy")}
              </Button>
              <Button size="sm" variant="ghost" onClick={exportJson}>
                <Download className="mr-1 h-3.5 w-3.5" />{t("review.export")}
              </Button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 rounded-[var(--radius)] border border-border bg-card px-3 py-2 sm:grid-cols-4 sm:divide-x sm:divide-border/70">
            <StatTile label={t("review.income")} value={money(data.cashflow.income)} tone="positive" size="md" hint={deltaText(t, data.cashflow.previous.income_delta_pct)} />
            <StatTile label={t("review.expense")} value={money(data.cashflow.expense)} tone="negative" size="md" hint={deltaText(t, data.cashflow.previous.expense_delta_pct)} />
            <StatTile label={t("review.net")} value={money(data.cashflow.net)} tone={data.cashflow.net >= 0 ? "positive" : "negative"} size="md" hint={t("review.prevNet", { v: money(data.cashflow.previous.net) })} />
            <StatTile label={t("review.savings")} value={`${data.cashflow.savings_rate}%`} tone={data.cashflow.savings_rate >= data.savings_target ? "positive" : "negative"} size="md" hint={t("review.target", { n: data.savings_target })} />
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <Card className="p-[var(--card-pad)]">
              <div className="text-[13px] font-semibold">{t("review.headline")}</div>
              <p className="mt-2 text-[12.5px] leading-relaxed text-foreground/85">{data.headline}</p>
              <p className="mt-2 border-t border-border/60 pt-2 text-[12px] leading-relaxed text-muted-foreground">{data.verdict}</p>
            </Card>

            <Card className="p-[var(--card-pad)]">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[13px] font-semibold">{t("review.budget")}</span>
                {data.budget.total ? (
                  <Badge variant={data.budget.over ? "danger" : "ok"}>
                    {data.budget.over ? t("review.budgetOver") : `${data.budget.pct}%`}
                  </Badge>
                ) : (
                  <Badge variant="warn">{t("review.budgetUnset")}</Badge>
                )}
              </div>
              {data.budget.total ? (
                <>
                  <div className="mt-2 flex items-center justify-between text-[11px] text-muted-foreground">
                    <span>{t("review.spent", { v: money(data.budget.spent) })}</span>
                    <span>{money(data.budget.total)}</span>
                  </div>
                  <ProgressBar
                    pct={data.budget.total ? data.budget.spent / data.budget.total * 100 : 0}
                    className="mt-1.5"
                    colorClass={data.budget.over ? "bg-red-500" : "bg-primary"}
                  />
                  {data.budget.over_categories.length > 0 ? (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {data.budget.over_categories.slice(0, 5).map((c) => (
                        <span key={c.category} className="rounded-full bg-red-500/10 px-2 py-0.5 text-[10px] text-red-600 dark:text-red-400">
                          {c.category} +{money(c.spent - c.budget)}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-2 text-[11px] text-muted-foreground">{t("review.noOver")}</p>
                  )}
                </>
              ) : (
                <p className="mt-2 text-[12px] text-muted-foreground">{t("review.budgetNo")}。{t("review.budgetNoHint")}</p>
              )}
            </Card>
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <Card className="p-[var(--card-pad)]">
              <div className="text-[13px] font-semibold">{t("review.categories")}</div>
              <ul className="mt-2 space-y-1.5">
                {data.categories.map((c) => (
                  <li key={c.category}>
                    <div className="flex items-center justify-between gap-2 text-[11.5px]">
                      <span className="truncate">{c.category}</span>
                      <span className="shrink-0 tabular-nums text-muted-foreground">{money(c.amount)} · {c.share_pct}%</span>
                    </div>
                    <ProgressBar pct={c.share_pct} className="mt-1 h-1.5" colorClass="bg-primary/70" />
                  </li>
                ))}
                {data.categories.length === 0 && <li className="text-[11.5px] text-muted-foreground">{t("review.empty")}</li>}
              </ul>
            </Card>

            <Card className="p-[var(--card-pad)]">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[13px] font-semibold">{t("review.anomalies")}</span>
                <Badge variant={data.anomalies.count ? "warn" : "ok"}>{data.anomalies.count}</Badge>
              </div>
              {data.anomalies.count === 0 ? (
                <p className="mt-2 text-[12px] text-muted-foreground">{t("review.noAnomalies")}</p>
              ) : (
                <ul className="mt-2 space-y-1.5">
                  {data.anomalies.items.slice(0, 4).map((a, i) => (
                    <li key={`${a.item}-${i}`} className="flex items-start justify-between gap-2 border-b border-border/40 pb-1.5 text-[11.5px] last:border-0 last:pb-0">
                      <span className="min-w-0">
                        <span className="block truncate">{a.item}</span>
                        <span className="text-[10px] text-muted-foreground">{a.date}{a.multiple ? ` · ${a.multiple}x` : ""}</span>
                      </span>
                      <span className="shrink-0 tabular-nums text-red-600 dark:text-red-400">{money(a.amount)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          <div className="grid gap-3 lg:grid-cols-3">
            <Card className="p-[var(--card-pad)]">
              <div className="text-[13px] font-semibold">{t("review.subscriptions")}</div>
              <div className="mt-1 text-[11px] text-muted-foreground">{t("review.monthlyTotal", { v: money(data.subscriptions.monthly_total) })}</div>
              <div className="text-[11px] text-muted-foreground">{t("review.annualTotal", { v: money(data.subscriptions.annual_total) })}</div>
              <div className="mt-2 space-y-1">
                {data.subscriptions.top.map((s) => (
                  <div key={s.name} className="flex items-center justify-between text-[11.5px]">
                    <span className="truncate">{s.name}</span>
                    <span className="tabular-nums text-muted-foreground">{money(s.monthly)}</span>
                  </div>
                ))}
              </div>
            </Card>

            <Card className="p-[var(--card-pad)]">
              <div className="text-[13px] font-semibold">{t("review.debts")}</div>
              <div className="mt-1 text-[11px] text-muted-foreground">{t("review.balance", { v: money(data.debts.balance) })}</div>
              <div className="text-[11px] text-muted-foreground">{t("review.monthlyPayment", { v: money(data.debts.monthly) })}</div>
              <div className="mt-2 flex items-center gap-1.5 text-[11.5px]">
                <Wallet className="h-3.5 w-3.5 text-muted-foreground" />
                {t("review.dti", { n: data.debts.dti_pct })}
              </div>
            </Card>

            <Card className="p-[var(--card-pad)]">
              <div className="text-[13px] font-semibold">{t("review.goals")}</div>
              <div className="mt-1 text-[11px] text-muted-foreground">{t("review.behind", { n: data.goals.behind })}</div>
              <div className="text-[11px] text-muted-foreground">{t("review.gap", { v: money(data.goals.gap) })}</div>
              <div className="mt-2 text-[11.5px]">{data.goals.done} / {data.goals.count}</div>
            </Card>
          </div>

          <Card className="p-[var(--card-pad)]">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-1.5 text-[13px] font-semibold">
                <ClipboardList className="h-4 w-4 text-primary" />
                {t("review.actions")}
              </div>
              <Badge variant={data.closing.ready ? "ok" : "warn"}>
                {t("review.closing", { p: data.closing.passed, t: data.closing.total })}
              </Badge>
            </div>
            <ol className="mt-2.5 grid gap-2 lg:grid-cols-3">
              {data.actions.map((a, i) => (
                <li key={a.code} className="rounded-lg border border-border/60 bg-muted/15 p-3">
                  <div className="flex items-start gap-2">
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10px] font-semibold text-primary">{i + 1}</span>
                    <div className="min-w-0">
                      <div className="text-[12.5px] font-medium">{a.title}</div>
                      <div className="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">{a.detail}</div>
                      {a.amount != null && (
                        <div className="mt-1 text-[10.5px] tabular-nums text-muted-foreground">{t("review.actionAmount", { v: money(a.amount) })}</div>
                      )}
                    </div>
                  </div>
                </li>
              ))}
            </ol>
            <div className="mt-3 grid gap-2 border-t border-border/60 pt-3 sm:grid-cols-2 lg:grid-cols-5">
              {data.closing.checks.map((c) => (
                <div key={c.id} className="flex items-center gap-1.5 text-[11px]">
                  {c.ok ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" /> : <AlertTriangle className="h-3.5 w-3.5 text-amber-600" />}
                  <span className={c.ok ? "text-muted-foreground" : "text-foreground/80"}>{c.label}</span>
                </div>
              ))}
            </div>
            <p className="mt-2 text-[10.5px] text-muted-foreground">{data.closing.note}</p>
          </Card>

          <Card className="p-[var(--card-pad)]">
            <div className="grid gap-2 sm:grid-cols-3">
              <div>
                <div className="text-[11px] text-muted-foreground">{t("review.coverage")}</div>
                <div className="mt-0.5 text-[12px] font-medium">{t("review.coveragePct", { n: data.coverage.coverage_pct })}</div>
                <div className="text-[10.5px] text-muted-foreground">{t("review.days", { d: data.coverage.days_with_transactions, t: data.coverage.days_in_period })}</div>
              </div>
              <div>
                <div className="text-[11px] text-muted-foreground">{t("review.uncategorized", { n: data.coverage.uncategorized })}</div>
                <div className="mt-0.5 text-[12px] font-medium">{data.coverage.uncategorized}</div>
              </div>
              <div>
                <div className="text-[11px] text-muted-foreground">{t("review.budget")}</div>
                <div className="mt-0.5 text-[12px] font-medium">{data.coverage.budget_set ? t("review.budgetSet") : t("review.budgetUnset")}</div>
              </div>
            </div>
            <p className="mt-3 border-t border-border/60 pt-2 text-[10.5px] text-muted-foreground">{data.disclaimer}</p>
          </Card>
        </>
      )}
    </div>
  );
}

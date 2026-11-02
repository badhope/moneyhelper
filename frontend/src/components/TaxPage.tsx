/** 公司财税页（v4.5）：税负测算 / 个税 / 工资 / 月结清单 / 现金流预测 / 订阅与异常。
 *
 * 信息架构按「财务人员的一天」排：
 *   1. 顶部：现金流三档预测（先看有没有钱）
 *   2. 税负测算（增值税 / 企业所得税 / 个税 / 工资）四个页签
 *   3. 月结清单（模板 + 本地勾选进度）
 *   4. 订阅与异常扣款（个人侧，但同一套流水）
 *
 * 所有结果都标口径与免责；不显示「看起来合理」的假数字。
 */

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  Coins,
  Loader2,
  Receipt,
  RefreshCw,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { PillTabs } from "@/components/ui/pill-tabs";
import { Segmented } from "@/components/ui/segmented";
import { useI18n } from "@/lib/i18n";
import { fmtMoney, fmtPct, pnlClass } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  useAnomalies,
  useCalcCit,
  useCalcIit,
  useCalcPayroll,
  useCalcVat,
  useDetectedSubscriptions,
  useForecast,
  useMonthEnd,
  useMonthEndProgress,
  type CitResult,
  type IitResult,
  type PayrollResult,
  type VatResult,
} from "@/lib/use-finance-tax";

type TaxTab = "vat" | "cit" | "iit" | "payroll" | "monthend";

function Field({
  label,
  value,
  onChange,
  hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint?: string;
}) {
  return (
    <label className="block">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        inputMode="decimal"
        className="mt-0.5 w-full rounded-md border border-border bg-background px-2 py-1.5 text-[12px] tabular-nums"
      />
      {hint ? <span className="mt-0.5 block text-[10px] text-muted-foreground/80">{hint}</span> : null}
    </label>
  );
}

function ResultGrid({ items }: { items: { label: string; value: string; tone?: string }[] }) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {items.map((x) => (
        <div key={x.label} className="rounded-lg bg-muted/25 px-2.5 py-2">
          <div className="text-[10.5px] text-muted-foreground">{x.label}</div>
          <div className={cn("mt-0.5 text-[14px] font-bold tabular-nums", x.tone)}>{x.value}</div>
        </div>
      ))}
    </div>
  );
}

function VatPanel() {
  const { t } = useI18n();
  const calc = useCalcVat();
  const [f, setF] = useState({ sales: "1000000", purchases: "600000", rate: "0.13", location: "city", simple: false });
  const [res, setRes] = useState<VatResult | null>(null);
  // 打开即用默认参数算一次：空结果区只剩「计算」两个字，用户不知道右边会发生什么
  useEffect(() => {
    void calc
      .mutateAsync({
        sales: Number(f.sales),
        purchases: Number(f.purchases),
        rate: Number(f.rate),
        location: f.location,
        simple: f.simple,
      })
      .then(setRes)
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div className="grid gap-3 lg:grid-cols-[20rem_minmax(0,1fr)]">
      <div className="space-y-2">
        <Field label={t("tax.sales")} value={f.sales} onChange={(v) => setF({ ...f, sales: v })} />
        <Field label={t("tax.purchases")} value={f.purchases} onChange={(v) => setF({ ...f, purchases: v })} />
        <label className="block">
          <span className="text-[11px] text-muted-foreground">{t("tax.rate")}</span>
          <select
            value={f.rate}
            onChange={(e) => setF({ ...f, rate: e.target.value })}
            className="mt-0.5 w-full rounded-md border border-border bg-background px-2 py-1.5 text-[12px]"
          >
            <option value="0.13">13%</option>
            <option value="0.09">9%</option>
            <option value="0.06">6%</option>
            <option value="0">0%</option>
          </select>
        </label>
        <label className="block">
          <span className="text-[11px] text-muted-foreground">{t("tax.location")}</span>
          <select
            value={f.location}
            onChange={(e) => setF({ ...f, location: e.target.value })}
            className="mt-0.5 w-full rounded-md border border-border bg-background px-2 py-1.5 text-[12px]"
          >
            <option value="city">{t("tax.location.city")}</option>
            <option value="county">{t("tax.location.county")}</option>
            <option value="other">{t("tax.location.other")}</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-[11.5px]">
          <input type="checkbox" checked={f.simple} onChange={(e) => setF({ ...f, simple: e.target.checked })} />
          {t("tax.simple")}
        </label>
        <Button
          size="sm"
          className="w-full"
          disabled={calc.isPending}
          onClick={() =>
            void calc
              .mutateAsync({
                sales: Number(f.sales),
                purchases: Number(f.purchases),
                rate: Number(f.rate),
                location: f.location,
                simple: f.simple,
              })
              .then(setRes)
              .catch(() => undefined)
          }
        >
          {calc.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
          {t("tax.calc")}
        </Button>
      </div>
      <div>
        {res ? (
          <>
            <ResultGrid
              items={[
                { label: t("tax.outputVat"), value: fmtMoney(res.output_vat) },
                { label: t("tax.inputVat"), value: fmtMoney(res.input_vat) },
                { label: t("tax.vatPayable"), value: fmtMoney(res.vat_payable) },
                { label: t("tax.surcharge"), value: fmtMoney(res.surcharge) },
                { label: t("tax.total"), value: fmtMoney(res.total), tone: "text-foreground" },
              ]}
            />
            {res.surcharge_detail ? (
              <div className="mt-2 text-[10.5px] text-muted-foreground">
                城建 {fmtMoney(res.surcharge_detail.city_construction)} · 教育{" "}
                {fmtMoney(res.surcharge_detail.education)} · 地方教育{" "}
                {fmtMoney(res.surcharge_detail.local_education)}
              </div>
            ) : null}
            {res.note ? <p className="mt-1.5 text-[10.5px] text-amber-600 dark:text-amber-400">{res.note}</p> : null}
          </>
        ) : (
          <EmptyState mode="compact" text={t("tax.calc")} />
        )}
      </div>
    </div>
  );
}

function CitPanel() {
  const { t } = useI18n();
  const calc = useCalcCit();
  const [f, setF] = useState({ revenue: "5000000", cost: "3000000", expenses: "800000", loss: "0", category: "standard" });
  const [res, setRes] = useState<CitResult | null>(null);
  useEffect(() => {
    void calc
      .mutateAsync({
        revenue: Number(f.revenue),
        cost: Number(f.cost),
        expenses: Number(f.expenses),
        loss_carryforward: Number(f.loss),
        category: f.category,
      })
      .then(setRes)
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div className="grid gap-3 lg:grid-cols-[20rem_minmax(0,1fr)]">
      <div className="space-y-2">
        <Field label={t("tax.revenue")} value={f.revenue} onChange={(v) => setF({ ...f, revenue: v })} />
        <Field label={t("tax.cost")} value={f.cost} onChange={(v) => setF({ ...f, cost: v })} />
        <Field label={t("tax.expenses")} value={f.expenses} onChange={(v) => setF({ ...f, expenses: v })} />
        <Field label={t("tax.loss")} value={f.loss} onChange={(v) => setF({ ...f, loss: v })} />
        <label className="block">
          <span className="text-[11px] text-muted-foreground">{t("tax.category")}</span>
          <select
            value={f.category}
            onChange={(e) => setF({ ...f, category: e.target.value })}
            className="mt-0.5 w-full rounded-md border border-border bg-background px-2 py-1.5 text-[12px]"
          >
            <option value="standard">{t("tax.category.standard")}</option>
            <option value="high_tech">{t("tax.category.high_tech")}</option>
            <option value="small_micro">{t("tax.category.small_micro")}</option>
          </select>
        </label>
        <Button
          size="sm"
          className="w-full"
          disabled={calc.isPending}
          onClick={() =>
            void calc
              .mutateAsync({
                revenue: Number(f.revenue),
                cost: Number(f.cost),
                expenses: Number(f.expenses),
                loss_carryforward: Number(f.loss),
                category: f.category,
              })
              .then(setRes)
              .catch(() => undefined)
          }
        >
          {t("tax.calc")}
        </Button>
      </div>
      <div>
        {res ? (
          <>
            <ResultGrid
              items={[
                { label: t("tax.taxable"), value: fmtMoney(res.taxable_income) },
                { label: t("tax.citPayable"), value: fmtMoney(res.tax_payable) },
                { label: t("tax.netProfit"), value: fmtMoney(res.net_profit) },
                { label: t("tax.effectiveRate"), value: fmtPct(res.effective_rate * 100, true) },
              ]}
            />
            {res.note ? <p className="mt-1.5 text-[10.5px] text-amber-600 dark:text-amber-400">{res.note}</p> : null}
          </>
        ) : (
          <EmptyState mode="compact" text={t("tax.calc")} />
        )}
      </div>
    </div>
  );
}

function IitPanel() {
  const { t } = useI18n();
  const calc = useCalcIit();
  const [f, setF] = useState({
    salary: "30000",
    months: "1",
    social: "4000",
    fund: "1000",
    special: "2000",
    withheld: "0",
  });
  const [res, setRes] = useState<IitResult | null>(null);
  useEffect(() => {
    void calc
      .mutateAsync({
        monthly_salary: Number(f.salary),
        months: Number(f.months),
        social_insurance: Number(f.social),
        housing_fund: Number(f.fund),
        special_additional: Number(f.special),
        already_withheld: Number(f.withheld),
      })
      .then(setRes)
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div className="grid gap-3 lg:grid-cols-[20rem_minmax(0,1fr)]">
      <div className="space-y-2">
        <Field label={t("tax.monthlySalary")} value={f.salary} onChange={(v) => setF({ ...f, salary: v })} />
        <Field label={t("tax.months")} value={f.months} onChange={(v) => setF({ ...f, months: v })} />
        <Field label={t("tax.social")} value={f.social} onChange={(v) => setF({ ...f, social: v })} />
        <Field label={t("tax.fund")} value={f.fund} onChange={(v) => setF({ ...f, fund: v })} />
        <Field label={t("tax.special")} value={f.special} onChange={(v) => setF({ ...f, special: v })} />
        <Button
          size="sm"
          className="w-full"
          disabled={calc.isPending}
          onClick={() =>
            void calc
              .mutateAsync({
                monthly_salary: Number(f.salary),
                months: Number(f.months),
                social_insurance: Number(f.social),
                housing_fund: Number(f.fund),
                special_additional: Number(f.special),
                already_withheld: Number(f.withheld),
              })
              .then(setRes)
              .catch(() => undefined)
          }
        >
          {t("tax.calc")}
        </Button>
      </div>
      <div>
        {res ? (
          <ResultGrid
            items={[
              { label: t("tax.taxable"), value: fmtMoney(res.taxable_income) },
              { label: t("tax.iitCumulative"), value: fmtMoney(res.cumulative_tax) },
              { label: t("tax.iitCurrent"), value: fmtMoney(res.current_withholding) },
              { label: t("tax.effectiveRate"), value: fmtPct(res.effective_rate * 100, true) },
            ]}
          />
        ) : (
          <EmptyState mode="compact" text={t("tax.calc")} />
        )}
      </div>
    </div>
  );
}

function PayrollPanel() {
  const { t } = useI18n();
  const calc = useCalcPayroll();
  const [f, setF] = useState({ gross: "30000", special: "2000" });
  const [res, setRes] = useState<PayrollResult | null>(null);
  useEffect(() => {
    void calc
      .mutateAsync({ gross_salary: Number(f.gross), special_additional: Number(f.special) })
      .then(setRes)
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div className="grid gap-3 lg:grid-cols-[20rem_minmax(0,1fr)]">
      <div className="space-y-2">
        <Field label={t("tax.grossSalary")} value={f.gross} onChange={(v) => setF({ ...f, gross: v })} />
        <Field label={t("tax.special")} value={f.special} onChange={(v) => setF({ ...f, special: v })} />
        <Button
          size="sm"
          className="w-full"
          disabled={calc.isPending}
          onClick={() =>
            void calc
              .mutateAsync({ gross_salary: Number(f.gross), special_additional: Number(f.special) })
              .then(setRes)
              .catch(() => undefined)
          }
        >
          {t("tax.calc")}
        </Button>
        <p className="text-[10px] leading-relaxed text-muted-foreground">{t("tax.payrollNote")}</p>
      </div>
      <div>
        {res ? (
          <>
            <ResultGrid
              items={[
                { label: t("tax.grossSalary"), value: fmtMoney(res.gross) },
                { label: t("tax.employeeTotal"), value: fmtMoney(res.employee_total) },
                { label: t("tax.income_tax"), value: fmtMoney(res.income_tax) },
                { label: t("tax.netPay"), value: fmtMoney(res.net_pay), tone: "text-foreground" },
                { label: t("tax.employerTotal"), value: fmtMoney(res.employer_total) },
                { label: t("tax.employerCost"), value: fmtMoney(res.employer_cost) },
              ]}
            />
            {res.notes?.length ? (
              <div className="mt-1.5 space-y-0.5">
                {res.notes.map((n) => (
                  <div key={n} className="text-[10px] text-amber-600 dark:text-amber-400">
                    {n}
                  </div>
                ))}
              </div>
            ) : null}
          </>
        ) : (
          <EmptyState mode="compact" text={t("tax.calc")} />
        )}
      </div>
    </div>
  );
}

function MonthEndPanel() {
  const { t } = useI18n();
  const month = new Date().toISOString().slice(0, 7);
  const q = useMonthEnd(month);
  const progress = useMonthEndProgress(month);
  const [done, setDone] = useState<string[]>(() => progress.read());
  const toggle = (id: string) => {
    const next = done.includes(id) ? done.filter((x) => x !== id) : [...done, id];
    setDone(next);
    progress.write(next);
  };
  if (q.isPending) return <Skeleton className="h-40 w-full" />;
  const d = q.data;
  if (!d) return <EmptyState mode="compact" text={t("tax.monthEndTitle")} />;
  const doneCount = d.items.filter((i) => done.includes(i.id)).length;
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[13px] font-semibold">{t("tax.monthEndTitle")} · {d.month}</div>
        <span className="text-[11px] text-muted-foreground">
          {t("tax.progress", { d: doneCount, t: d.total, p: ((doneCount / d.total) * 100).toFixed(0) })}
        </span>
      </div>
      <p className="mt-1 text-[10.5px] leading-relaxed text-muted-foreground">{t("tax.monthEndDesc")}</p>
      <div className="mt-2 space-y-1">
        {d.items.map((item) => {
          const checked = done.includes(item.id);
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => toggle(item.id)}
              className="flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-accent/60"
            >
              {checked ? (
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
              ) : (
                <Circle className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground/50" />
              )}
              <span className="min-w-0">
                <span className={cn("block text-[12px] font-medium", checked && "text-muted-foreground line-through")}>
                  {item.title}
                </span>
                <span className="block text-[10.5px] leading-snug text-muted-foreground">{item.detail}</span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** 现金流三档预测 */
function ForecastCard() {
  const { t } = useI18n();
  const [months, setMonths] = useState(3);
  const q = useForecast(months);
  const d = q.data;
  if (q.isPending) return <Card className="p-[var(--card-pad)]"><Skeleton className="h-32 w-full" /></Card>;
  if (!d?.available) {
    return (
      <Card className="p-[var(--card-pad)]">
        <div className="text-[13px] font-semibold">{t("tax.forecastTitle")}</div>
        <EmptyState mode="compact" text={d?.reason || t("connect.noData")} />
      </Card>
    );
  }
  return (
    <Card className="p-[var(--card-pad)]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-[13px] font-semibold">
          <Coins className="h-4 w-4 text-primary" />
          {t("tax.forecastTitle")}
        </div>
        <Segmented
          size="sm"
          value={String(months)}
          onChange={(v) => setMonths(Number(v))}
          options={[
            { value: "1", label: "1M" },
            { value: "3", label: "3M" },
            { value: "6", label: "6M" },
          ]}
        />
      </div>
      <p className="mt-1 text-[10.5px] leading-relaxed text-muted-foreground">{t("tax.forecastDesc")}</p>
      <div className="mt-2 grid gap-2 sm:grid-cols-3">
        {(["pessimistic", "base", "optimistic"] as const).map((k) => {
          const s = d.scenarios?.[k];
          if (!s) return null;
          const tone = k === "pessimistic" ? "text-down" : k === "optimistic" ? "text-up" : "text-foreground";
          return (
            <div key={k} className="rounded-lg bg-muted/25 px-2.5 py-2">
              <div className="text-[10.5px] text-muted-foreground">{t(`tax.scenario.${k}`)}</div>
              <div className={cn("mt-0.5 text-base font-bold tabular-nums", tone)}>{fmtMoney(s.ending_balance)}</div>
              <div className="text-[10.5px] text-muted-foreground">
                {t("tax.monthlyNet")} {fmtMoney(s.monthly_net, true)}
              </div>
              {s.goes_negative ? (
                <div className="mt-0.5 flex items-center gap-1 text-[10px] text-red-600 dark:text-red-400">
                  <AlertTriangle className="h-3 w-3" /> {t("tax.endingBalance")}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
      {d.warnings?.length ? (
        <div className="mt-1.5 space-y-0.5">
          {d.warnings.map((w) => (
            <div key={w} className="text-[10.5px] leading-snug text-amber-600 dark:text-amber-400">
              {w}
            </div>
          ))}
        </div>
      ) : null}
      <div className="mt-1.5 text-[10px] text-muted-foreground/80">
        {d.basis} · {t("tax.disclaimer")}
      </div>
    </Card>
  );
}

/** 订阅与异常 */
function SubsAnomalyCard() {
  const { t } = useI18n();
  const subs = useDetectedSubscriptions();
  const anomalies = useAnomalies(180);
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <Card className="min-w-0 p-[var(--card-pad)]">
        <div className="flex items-center gap-1.5 text-[13px] font-semibold">
          <RefreshCw className="h-4 w-4 text-primary" />
          {t("tax.subsTitle")}
        </div>
        <p className="mt-1 text-[10.5px] text-muted-foreground">{t("tax.subsDesc")}</p>
        {subs.isPending ? (
          <Skeleton className="mt-2 h-16 w-full" />
        ) : (subs.data?.items ?? []).length === 0 ? (
          <EmptyState mode="compact" text={t("tax.subsNone")} />
        ) : (
          <div className="mt-2 space-y-1">
            {(subs.data?.items ?? []).map((s) => (
              <div key={s.name} className="flex flex-wrap items-center gap-1.5 border-b border-border/40 py-1.5 text-[11.5px] last:border-0">
                <span className="font-medium">{s.name}</span>
                {s.price_hike ? <Badge variant="danger" className="px-1.5 py-0 text-[10px]">{t("tax.priceHike")}</Badge> : null}
                <span className="tabular-nums">{fmtMoney(s.monthly_equivalent)}/月</span>
                <span className="text-muted-foreground">
                  {t("tax.nextCharge")} {s.next_expected}（{s.days_until_next} 天）
                </span>
              </div>
            ))}
            <div className="pt-1 text-[10.5px] text-muted-foreground">
              月均合计 {fmtMoney(subs.data?.monthly_total ?? 0)} · 年化 {fmtMoney(subs.data?.annual_total ?? 0)}
            </div>
          </div>
        )}
      </Card>

      <Card className="min-w-0 p-[var(--card-pad)]">
        <div className="flex items-center gap-1.5 text-[13px] font-semibold">
          <AlertTriangle className="h-4 w-4 text-amber-500" />
          {t("tax.anomalyTitle")}
        </div>
        <p className="mt-1 text-[10.5px] text-muted-foreground">{t("tax.anomalyDesc")}</p>
        {anomalies.isPending ? (
          <Skeleton className="mt-2 h-16 w-full" />
        ) : (anomalies.data?.items ?? []).length === 0 ? (
          <EmptyState mode="compact" text={t("tax.anomalyNone")} />
        ) : (
          <div className="mt-2 space-y-1">
            {(anomalies.data?.items ?? []).slice(0, 8).map((a) => (
              <div key={`${a.item}-${a.date}`} className="border-b border-border/40 py-1.5 text-[11px] last:border-0">
                <div className="flex items-center gap-1.5">
                  <span className="font-medium">{a.item}</span>
                  <span className="text-muted-foreground">{a.date}</span>
                  <span className={cn("tabular-nums", pnlClass(-1))}>{fmtMoney(a.amount)}</span>
                  {a.multiple ? (
                    <span className="text-[10px] text-amber-600 dark:text-amber-400">
                      {t("tax.multiple", { n: a.multiple })}
                    </span>
                  ) : null}
                </div>
                <div className="text-[10px] text-muted-foreground">{a.suggestion}</div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

export function TaxPage() {
  const { t } = useI18n();
  const [tab, setTab] = useState<TaxTab>("vat");
  return (
    <div className="space-y-3">
      <Card className="p-[var(--card-pad)]">
        <div className="flex items-center gap-1.5 text-[13.5px] font-semibold">
          <Receipt className="h-4 w-4 text-primary" />
          {t("tax.title")}
        </div>
        <p className="mt-1 max-w-3xl text-[12px] leading-relaxed text-muted-foreground">{t("tax.intro")}</p>
        <div className="mt-3">
          <PillTabs
            value={tab}
            onChange={setTab}
            size="sm"
            options={[
              { value: "vat", label: t("tax.tabVat") },
              { value: "cit", label: t("tax.tabCit") },
              { value: "iit", label: t("tax.tabIit") },
              { value: "payroll", label: t("tax.tabPayroll") },
              { value: "monthend", label: t("tax.tabMonthEnd") },
            ]}
          />
        </div>
      </Card>

      <ForecastCard />

      <Card className="p-[var(--card-pad)]">
        {tab === "vat" && <VatPanel />}
        {tab === "cit" && <CitPanel />}
        {tab === "iit" && <IitPanel />}
        {tab === "payroll" && <PayrollPanel />}
        {tab === "monthend" && <MonthEndPanel />}
      </Card>

      <SubsAnomalyCard />

      <div className="px-1 text-[10.5px] text-muted-foreground">{t("tax.disclaimer")}</div>
    </div>
  );
}

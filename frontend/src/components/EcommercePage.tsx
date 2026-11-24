/** 电商经营测算（4.23.0）。
 *
 * 界面只做三件事：填参数、看净利与盈亏平衡 ROAS、保存方案。
 * 计算全部在后端纯函数里，前端不复制一份公式，避免两边算得不一样。
 * 订单直连只给入口（连接中心已预留抖店/淘宝/拼多多/有赞），不假装已接通。
 */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  Calculator,
  CheckCircle2,
  ClipboardCopy,
  Loader2,
  Save,
  ShoppingBag,
  Trash2,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { api } from "@/lib/api";
import { fmtMoney, fmtPct } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface Inputs {
  gmv: number;
  refunds: number;
  orders: number;
  commission_pct: number;
  payment_pct: number;
  ad_spend: number;
  cogs: number;
  fulfillment: number;
  other_cost: number;
  input_vat: number;
  vat_rate_pct: number;
  surtax_pct: number;
  income_tax_pct: number;
}

interface Result {
  verdict: "healthy" | "thin" | "loss";
  net_sales: number;
  refund_rate: number;
  gross_profit: number;
  gross_margin: number;
  platform_fee: number;
  payment_fee: number;
  output_vat: number;
  vat_payable: number;
  surtax: number;
  contribution_before_ad: number;
  ad_spend: number;
  contribution_after_ad: number;
  contribution_margin: number;
  profit_before_tax: number;
  income_tax: number;
  net_profit: number;
  net_margin: number;
  ros: number;
  aov: number;
  per_order_profit: number;
  ad_roas: number;
  breakeven_ad_spend: number;
  breakeven_roas: number;
  warnings: { level: string; text: string }[];
  formula_note: string;
}

interface Scenario {
  id: number;
  name: string;
  input: Partial<Inputs>;
  result: Result;
  created_at: string;
}

const DEFAULTS: Inputs = {
  gmv: 100000,
  refunds: 5000,
  orders: 1000,
  commission_pct: 5,
  payment_pct: 0.6,
  ad_spend: 8000,
  cogs: 45000,
  fulfillment: 6000,
  other_cost: 2000,
  input_vat: 3000,
  vat_rate_pct: 13,
  surtax_pct: 12,
  income_tax_pct: 25,
};

const FIELDS: {
  section: string;
  items: { key: keyof Inputs; label: string; suffix?: string }[];
}[] = [
  {
    section: "ecommerce.sectionTrade",
    items: [
      { key: "gmv", label: "ecommerce.gmv" },
      { key: "refunds", label: "ecommerce.refunds" },
      { key: "orders", label: "ecommerce.orders" },
    ],
  },
  {
    section: "ecommerce.sectionFee",
    items: [
      { key: "commission_pct", label: "ecommerce.commission", suffix: "%" },
      { key: "payment_pct", label: "ecommerce.payment", suffix: "%" },
    ],
  },
  {
    section: "ecommerce.sectionCost",
    items: [
      { key: "ad_spend", label: "ecommerce.adSpend" },
      { key: "cogs", label: "ecommerce.cogs" },
      { key: "fulfillment", label: "ecommerce.fulfillment" },
      { key: "other_cost", label: "ecommerce.otherCost" },
    ],
  },
  {
    section: "ecommerce.sectionTax",
    items: [
      { key: "input_vat", label: "ecommerce.inputVat" },
      { key: "vat_rate_pct", label: "ecommerce.vatRate", suffix: "%" },
      { key: "surtax_pct", label: "ecommerce.surtax", suffix: "%" },
      { key: "income_tax_pct", label: "ecommerce.incomeTax", suffix: "%" },
    ],
  },
];

const VERDICT_STYLE: Record<Result["verdict"], string> = {
  healthy: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  thin: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  loss: "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300",
};

function Metric({
  label,
  value,
  hint,
  negative,
  emphasis,
}: {
  label: string;
  value: string;
  hint?: string;
  negative?: boolean;
  emphasis?: boolean;
}) {
  return (
    <Card className={cn("p-3", emphasis && "border-primary/30 bg-primary/5")}>
      <div className="text-[10.5px] text-muted-foreground">{label}</div>
      <div
        className={cn(
          "mt-0.5 text-[20px] font-semibold tabular-nums",
          emphasis && "text-[26px]",
          negative ? "text-rose-600 dark:text-rose-400" : "",
        )}
      >
        {value}
      </div>
      {hint ? <div className="mt-0.5 text-[10.5px] leading-tight text-muted-foreground">{hint}</div> : null}
    </Card>
  );
}

export function EcommercePage({ onGo }: { onGo: (kind: "connect" | "autopilot") => void }) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const [inputs, setInputs] = useState<Inputs>(DEFAULTS);
  const [result, setResult] = useState<Result | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [copied, setCopied] = useState(false);
  const [saved, setSaved] = useState(false);
  const [actionError, setActionError] = useState("");

  useEffect(() => {
    if (!saved) return;
    const timer = window.setTimeout(() => setSaved(false), 2200);
    return () => window.clearTimeout(timer);
  }, [saved]);

  useEffect(() => {
    let canceled = false;
    setLoading(true);
    const timer = window.setTimeout(async () => {
      try {
        const res = await api<{ result: Result }>("/api/ecommerce/calculate", {
          method: "POST",
          body: JSON.stringify(inputs),
        });
        if (!canceled) {
          setResult(res.result);
          setError("");
        }
      } catch (err) {
        if (!canceled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!canceled) setLoading(false);
      }
    }, 320);
    return () => {
      canceled = true;
      window.clearTimeout(timer);
    };
  }, [inputs]);

  const scenarios = useQuery({
    queryKey: ["ecommerce-scenarios"],
    queryFn: () => api<{ items: Scenario[] }>("/api/ecommerce/scenarios"),
  });

  const save = useMutation({
    mutationFn: () =>
      api<{ item: Scenario }>("/api/ecommerce/scenarios", {
        method: "POST",
        body: JSON.stringify({ name: name || `${t("ecommerce.scenarioName")} ${new Date().toLocaleDateString()}`, input: inputs }),
      }),
    onSuccess: () => {
      setName("");
      setSaved(true);
      setActionError("");
      void qc.invalidateQueries({ queryKey: ["ecommerce-scenarios"] });
    },
    onError: (err) => {
      setSaved(false);
      setActionError(err instanceof Error ? err.message : String(err));
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) => api(`/api/ecommerce/scenarios/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      setSaved(false);
      setActionError("");
      void qc.invalidateQueries({ queryKey: ["ecommerce-scenarios"] });
    },
    onError: (err) => setActionError(err instanceof Error ? err.message : String(err)),
  });

  const bars = useMemo(() => {
    if (!result) return [];
    const denom = Math.max(result.net_sales, 1);
    return [
      { key: "ecommerce.cogs", value: inputs.cogs, cls: "bg-slate-500/70" },
      { key: "ecommerce.platformFee", value: result.platform_fee, cls: "bg-indigo-500/70" },
      { key: "ecommerce.paymentFee", value: result.payment_fee, cls: "bg-sky-500/70" },
      { key: "ecommerce.surtaxCost", value: result.surtax, cls: "bg-teal-500/70" },
      { key: "ecommerce.vat", value: result.vat_payable, cls: "bg-violet-500/70" },
      { key: "ecommerce.adSpend", value: result.ad_spend, cls: "bg-amber-500/70" },
      { key: "ecommerce.incomeTaxCost", value: result.income_tax, cls: "bg-rose-500/70" },
    ].map((b) => ({ ...b, width: Math.min(100, Math.abs(b.value) / denom * 100) }));
  }, [result, inputs.cogs]);

  const copy = async () => {
    if (!result) return;
    const text = [
      `${t("ecommerce.netProfit")}: ${result.net_profit.toFixed(2)}`,
      `${t("ecommerce.netSales")}: ${result.net_sales.toFixed(2)}`,
      `${t("ecommerce.netMargin")}: ${(result.net_margin * 100).toFixed(2)}%`,
      `${t("ecommerce.breakevenRoas")}: ${result.breakeven_roas.toFixed(2)}`,
    ].join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="space-y-4">
      <section className="relative overflow-hidden rounded-[var(--radius)] border border-border/70 bg-gradient-to-br from-amber-500/10 via-background to-emerald-500/10 p-4 sm:p-5">
        <div className="pointer-events-none absolute -right-14 -top-14 h-44 w-44 rounded-full bg-amber-500/15 blur-3xl" />
        <div className="relative flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.18em] text-amber-700 dark:text-amber-400">
              <ShoppingBag className="h-3.5 w-3.5" />
              Commerce margin
            </div>
            <h1 className="mt-1 text-[26px] font-semibold tracking-tight sm:text-[30px]">{t("ecommerce.title")}</h1>
            <p className="mt-1 max-w-2xl text-[12.5px] leading-relaxed text-muted-foreground">{t("ecommerce.subtitle")}</p>
            <p className="mt-2 inline-flex items-center gap-1 text-[11px] text-muted-foreground">
              <Calculator className="h-3.5 w-3.5" />
              {t("ecommerce.autoCalc")}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={copy} disabled={!result}>
              <ClipboardCopy className="h-4 w-4" />
              {copied ? t("ecommerce.copied") : t("ecommerce.copyResult")}
            </Button>
            <Button variant="outline" onClick={() => onGo("connect")}>
              {t("ecommerce.connectCta")}
              <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </section>

      {error && (
        <Card className="border-rose-500/30 p-3 text-[12px] text-rose-700 dark:text-rose-300">
          {t("ecommerce.calcFail", { reason: error })}
        </Card>
      )}
      {actionError && (
        <Card className="border-rose-500/30 p-3 text-[12px] text-rose-700 dark:text-rose-300">
          {actionError}
        </Card>
      )}

      <div className="grid gap-3 xl:grid-cols-[1.05fr_1.35fr]">
        <Card className="h-fit p-4">
          <div className="flex items-baseline justify-between gap-2">
            <h2 className="text-[14px] font-semibold">{t("ecommerce.formTitle")}</h2>
            {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
          </div>
          <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">{t("ecommerce.formHint")}</p>
          <div className="mt-3 space-y-3">
            {FIELDS.map((section) => (
              <div key={section.section}>
                <div className="mb-1 text-[11px] font-semibold text-foreground/80">{t(section.section)}</div>
                <div className="grid grid-cols-2 gap-2">
                  {section.items.map((item) => (
                    <label key={item.key} className="grid gap-0.5 text-[10.5px] text-muted-foreground">
                      {t(item.label)}
                      <div className="relative">
                        <input
                          type="number"
                          min={0}
                          step={item.suffix ? 0.1 : 1}
                          value={inputs[item.key]}
                          onChange={(e) => {
                            const raw = e.target.value;
                            const parsed = Number(raw);
                            setInputs((prev) => ({
                              ...prev,
                              [item.key]: raw === "" || !Number.isFinite(parsed) ? 0 : parsed,
                            }));
                          }}
                          className="h-9 w-full rounded-md border border-border bg-background px-2 pr-6 text-[12px] text-foreground tabular-nums outline-none focus:border-primary/60"
                        />
                        {item.suffix && (
                          <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground">
                            {item.suffix}
                          </span>
                        )}
                      </div>
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <p className="mt-3 text-[10.5px] leading-relaxed text-muted-foreground">{t("ecommerce.formula")}</p>
        </Card>

        <div className="space-y-3">
          {result ? (
            <>
              <Card className={cn("border p-4", VERDICT_STYLE[result.verdict])}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <div className="flex items-center gap-1.5 text-[11px] font-medium">
                      {result.verdict === "loss" ? <TrendingDown className="h-3.5 w-3.5" /> : <TrendingUp className="h-3.5 w-3.5" />}
                      {t("ecommerce.netProfit")}
                      <Badge className={cn("border px-1.5 py-0 text-[10px]", VERDICT_STYLE[result.verdict])}>
                        {t(`ecommerce.verdict.${result.verdict}`)}
                      </Badge>
                    </div>
                    <div className="mt-1 text-[34px] font-semibold tabular-nums leading-none">
                      {fmtMoney(result.net_profit)}
                    </div>
                    <div className="mt-1 text-[11px] opacity-90">
                      {t("ecommerce.netMargin")} {fmtPct(result.net_margin * 100)} · {t("ecommerce.breakevenRoas")} {result.breakeven_roas.toFixed(2)}
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-right text-[10.5px] opacity-90">
                    <span>{t("ecommerce.netSales")}</span>
                    <span className="font-medium tabular-nums">{fmtMoney(result.net_sales)}</span>
                    <span>{t("ecommerce.contribution")}</span>
                    <span className="font-medium tabular-nums">{fmtMoney(result.contribution_after_ad)}</span>
                    <span>{t("ecommerce.adRoas")}</span>
                    <span className="font-medium tabular-nums">{result.ad_roas.toFixed(2)}</span>
                  </div>
                </div>
              </Card>

              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Metric label={t("ecommerce.perOrder")} value={fmtMoney(result.per_order_profit)} negative={result.per_order_profit < 0} emphasis />
                <Metric label={t("ecommerce.aov")} value={fmtMoney(result.aov)} />
                <Metric label={t("ecommerce.refundRate")} value={fmtPct(result.refund_rate * 100)} />
                <Metric label={t("ecommerce.breakevenRoas")} value={result.breakeven_roas.toFixed(2)} hint={t("ecommerce.breakdownHint")} />
              </div>

              <Card className="p-4">
                <div className="flex flex-wrap items-baseline justify-between gap-1">
                  <h2 className="text-[13.5px] font-semibold">{t("ecommerce.breakdown")}</h2>
                  <span className="text-[10.5px] text-muted-foreground">{t("ecommerce.breakdownHint")}</span>
                </div>
                <div className="mt-3 space-y-1.5">
                  {bars.map((b) => (
                    <div key={b.key} className="grid grid-cols-[92px_1fr_74px] items-center gap-1.5 text-[10.5px]">
                      <span className="truncate text-muted-foreground">{t(b.key)}</span>
                      <div className="h-2 overflow-hidden rounded-full bg-muted">
                        <div className={cn("h-full rounded-full transition-all", b.cls)} style={{ width: `${b.width}%` }} />
                      </div>
                      <span className="text-right tabular-nums text-muted-foreground">{fmtMoney(b.value)}</span>
                    </div>
                  ))}
                </div>
              </Card>

              <Card className={cn("p-3", result.warnings.length ? "border-amber-500/30 bg-amber-500/5" : "border-emerald-500/30 bg-emerald-500/5")}>
                <div className="flex items-center gap-1.5 text-[12px] font-semibold">
                  {result.warnings.length ? <AlertTriangle className="h-3.5 w-3.5" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                  {t("ecommerce.warnings")}
                </div>
                {result.warnings.length ? (
                  <ul className="mt-1.5 space-y-1">
                    {result.warnings.map((w) => (
                      <li key={w.text} className="text-[11.5px] leading-relaxed text-muted-foreground">· {w.text}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1 text-[11.5px] text-muted-foreground">{t("ecommerce.noWarnings")}</p>
                )}
              </Card>
            </>
          ) : (
            <Card className="p-4 text-[12px] text-muted-foreground">
              {loading ? t("ecommerce.autoCalc") : t("ecommerce.loadFail")}
            </Card>
          )}
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card className="p-4">
          <h2 className="text-[14px] font-semibold">{t("ecommerce.saveTitle")}</h2>
          <p className="mt-0.5 text-[11px] text-muted-foreground">{t("ecommerce.saveHint")}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("ecommerce.scenarioName")}
              className="h-9 min-w-0 flex-1 rounded-md border border-border bg-background px-2 text-[12px] outline-none focus:border-primary/60"
            />
            <Button onClick={() => save.mutate()} disabled={!result || save.isPending}>
              {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {save.isPending ? t("ecommerce.saving") : t("ecommerce.save")}
            </Button>
          </div>
          {saved && <p className="mt-1.5 text-[11px] text-emerald-700 dark:text-emerald-400">{t("ecommerce.saved")}</p>}
        </Card>

        <Card className="p-4">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-[14px] font-semibold">{t("ecommerce.scenarios")}</h2>
            {scenarios.data?.items?.length ? <span className="text-[10.5px] text-muted-foreground">{scenarios.data.items.length}</span> : null}
          </div>
          {scenarios.data?.items?.length ? (
            <div className="mt-2 space-y-1.5">
              {scenarios.data.items.slice(0, 5).map((s) => (
                <div key={s.id} className="flex items-center gap-2 rounded-md border border-border/60 px-2 py-1.5 text-[11.5px]">
                  <span className="min-w-0 flex-1 truncate">{s.name}</span>
                  <span className={cn("tabular-nums", s.result.net_profit < 0 ? "text-rose-600 dark:text-rose-400" : "text-emerald-700 dark:text-emerald-400")}>
                    {fmtMoney(s.result.net_profit)}
                  </span>
                  <button
                    type="button"
                    aria-label={t("ecommerce.delete")}
                    onClick={() => remove.mutate(s.id)}
                    className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-2 text-[11.5px] text-muted-foreground">{t("ecommerce.emptyScenarios")}</p>
          )}
        </Card>
      </div>

      <Card className="flex flex-col gap-2 border-sky-500/25 bg-sky-500/5 p-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="text-[12.5px] font-semibold">{t("ecommerce.connectTitle")}</div>
          <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">{t("ecommerce.connectHint")}</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => onGo("connect")}>
          {t("ecommerce.connectCta")}
          <ArrowRight className="h-3.5 w-3.5" />
        </Button>
      </Card>
    </div>
  );
}

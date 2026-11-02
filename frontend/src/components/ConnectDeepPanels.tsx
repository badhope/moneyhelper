/** 连接中心深化面板（v4.5）：市场温度 / 个股档案 / 预交易检查 / 风控参数 / 条件单 / 发票 / 券商对账。
 *
 * 拆成独立文件：ConnectPage 已 900+ 行，继续内联会让单文件失控；这些面板都只依赖
 * use-connect 的 hooks，彼此独立，按需渲染。
 */

import { useState } from "react";
import {
  Banknote,
  Gauge,
  Loader2,
  Receipt,
  RefreshCw,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { Segmented } from "@/components/ui/segmented";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { fmtMoney, fmtPct, pnlClass } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  useBreadth,
  useConditionals,
  useCreateConditional,
  useDeleteConditional,
  useEvaluateConditionals,
  useImportHoldings,
  useInvoices,
  useDeleteInvoice,
  useRiskCheck,
  useRiskSettings,
  useSaveRiskSettings,
  useStockProfile,
  useUploadInvoiceText,
  type RiskCheckResult,
} from "@/lib/use-connect";

const MOOD_STYLE: Record<string, string> = {
  hot: "text-red-600 dark:text-red-400",
  warm: "text-amber-600 dark:text-amber-400",
  neutral: "text-muted-foreground",
  cool: "text-sky-600 dark:text-sky-400",
  cold: "text-emerald-600 dark:text-emerald-400",
};

/** 市场温度：涨跌家数 + 涨跌停 + 情绪刻度 */
export function BreadthCard() {
  const { t } = useI18n();
  const q = useBreadth();
  const d = q.data;
  if (q.isPending) {
    return (
      <Card className="p-[var(--card-pad)]">
        <Skeleton className="h-28 w-full" />
      </Card>
    );
  }
  if (!d?.available) {
    return (
      <Card className="p-[var(--card-pad)]">
        <EmptyState mode="compact" text={d?.reason || t("connect.noData")} />
      </Card>
    );
  }
  const temp = d.temperature ?? 0;
  return (
    <Card className="p-[var(--card-pad)]">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-[13px] font-semibold">
          <Gauge className="h-4 w-4 text-primary" />
          {t("connect.breadthTitle")}
        </div>
        <span className={cn("text-[11px]", MOOD_STYLE[d.mood ?? "neutral"])}>
          {t(`connect.mood.${d.mood ?? "neutral"}`)}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
        {[
          { label: t("connect.breadthUp"), value: d.up, tone: "text-up" },
          { label: t("connect.breadthDown"), value: d.down, tone: "text-down" },
          { label: t("connect.breadthLimitUp"), value: d.limit_up, tone: "text-up" },
          { label: t("connect.breadthLimitDown"), value: d.limit_down, tone: "text-down" },
          { label: t("connect.breadthStrong"), value: d.strong, tone: "text-foreground" },
        ].map((x) => (
          <div key={x.label} className="rounded-lg bg-muted/25 px-2.5 py-2">
            <div className="text-[10.5px] text-muted-foreground">{x.label}</div>
            <div className={cn("mt-0.5 text-base font-bold tabular-nums", x.tone)}>{x.value ?? "-"}</div>
          </div>
        ))}
      </div>
      <div className="mt-2">
        <div className="flex items-center justify-between text-[11px] text-muted-foreground">
          <span>{t("connect.temperature")}</span>
          <span className="font-medium tabular-nums">{temp.toFixed(1)} / 100</span>
        </div>
        <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div
            className={cn(
              "h-full rounded-full",
              temp >= 55 ? "bg-red-500" : temp >= 45 ? "bg-amber-500" : "bg-emerald-500",
            )}
            style={{ width: `${Math.max(2, Math.min(100, temp))}%` }}
          />
        </div>
        <div className="mt-1.5 text-[10.5px] text-muted-foreground">
          {t("connect.breadthRatio", { up: d.up_ratio_pct ?? 0, total: d.total ?? 0 })}
        </div>
      </div>
    </Card>
  );
}

/** 个股档案：价格 + 估值 + 规模 + 活跃度 */
export function StockProfileCard({ defaultSymbol }: { defaultSymbol: string }) {
  const { t } = useI18n();
  const [sym, setSym] = useState(defaultSymbol);
  const [query, setQuery] = useState(defaultSymbol);
  const q = useStockProfile(query);
  const d = q.data;
  return (
    <Card className="p-[var(--card-pad)]">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="text-[13px] font-semibold">{t("connect.profileTitle")}</div>
        <div className="flex items-center gap-1.5">
          <input
            value={sym}
            onChange={(e) => setSym(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") setQuery(sym.trim());
            }}
            placeholder="600519"
            className="w-28 rounded-md border border-border bg-background px-2 py-1 text-[12px]"
          />
          <Button size="sm" variant="outline" onClick={() => setQuery(sym.trim())}>
            {t("connect.query")}
          </Button>
        </div>
      </div>
      {q.isPending ? (
        <Skeleton className="h-24 w-full" />
      ) : q.isError || !d ? (
        <EmptyState mode="compact" text={t("connect.profileFail")} />
      ) : (
        <>
          <div className="flex items-baseline gap-2">
            <span className="text-[15px] font-semibold">{d.name || d.symbol}</span>
            <span className="text-lg font-bold tabular-nums">{d.price}</span>
            <span className={cn("text-[12px] tabular-nums", pnlClass(d.change_pct))}>
              {fmtPct(d.change_pct, true)}
            </span>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              { label: t("connect.pe"), value: d.pe_ttm != null ? d.pe_ttm.toFixed(2) : "-", tone: "" },
              { label: t("connect.pb"), value: d.pb != null ? d.pb.toFixed(2) : "-", tone: "" },
              {
                label: t("connect.totalMv"),
                value: d.total_mv_yi != null ? `${d.total_mv_yi.toFixed(0)} 亿` : "-",
                tone: "",
              },
              {
                label: t("connect.turnoverRate"),
                value: d.turnover_pct != null ? `${d.turnover_pct.toFixed(2)}%` : "-",
                tone: "",
              },
              {
                label: t("connect.volumeRatio"),
                value: d.volume_ratio != null ? d.volume_ratio.toFixed(2) : "-",
                tone: "",
              },
              {
                label: t("connect.amplitude"),
                value: d.amplitude_pct != null ? `${d.amplitude_pct.toFixed(2)}%` : "-",
                tone: "",
              },
              { label: t("connect.limitUp"), value: d.limit_up != null ? String(d.limit_up) : "-", tone: "text-up" },
              {
                label: t("connect.limitDown"),
                value: d.limit_down != null ? String(d.limit_down) : "-",
                tone: "text-down",
              },
            ].map((x) => (
              <div key={x.label} className="rounded-lg bg-muted/25 px-2 py-1.5">
                <div className="text-[10.5px] text-muted-foreground">{x.label}</div>
                <div className={cn("text-[13px] font-semibold tabular-nums", x.tone)}>{x.value}</div>
              </div>
            ))}
          </div>
          {d.valuation?.pe_note ? (
            <p className="mt-1.5 text-[10.5px] text-amber-600 dark:text-amber-400">{d.valuation.pe_note}</p>
          ) : null}
        </>
      )}
    </Card>
  );
}

/** 预交易检查：填单 → 逐项检查结果 */
export function PretradeCard() {
  const { t } = useI18n();
  const { toast } = useToast();
  const [form, setForm] = useState({ symbol: "600519", side: "buy" as "buy" | "sell", price: "", shares: "100" });
  const [result, setResult] = useState<RiskCheckResult | null>(null);
  const check = useRiskCheck();
  const run = async () => {
    const price = Number(form.price);
    const shares = Number(form.shares);
    if (!form.symbol.trim() || !price || !shares) {
      toast(t("connect.fillRequired"), "error");
      return;
    }
    try {
      setResult(await check.mutateAsync({ symbol: form.symbol.trim(), side: form.side, price, shares }));
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };
  return (
    <Card className="p-[var(--card-pad)]">
      <div className="mb-1 flex items-center gap-1.5 text-[13px] font-semibold">
        <ShieldCheck className="h-4 w-4 text-primary" />
        {t("connect.pretradeTitle")}
      </div>
      <p className="text-[10.5px] leading-relaxed text-muted-foreground">{t("connect.pretradeHint")}</p>
      <div className="mt-2 space-y-2">
        <div className="flex gap-2">
          <input
            value={form.symbol}
            onChange={(e) => setForm({ ...form, symbol: e.target.value })}
            placeholder="600519"
            className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-[12px]"
          />
          <Segmented
            size="sm"
            value={form.side}
            onChange={(v) => setForm({ ...form, side: v })}
            options={[
              { value: "buy", label: t("connect.buy") },
              { value: "sell", label: t("connect.sell") },
            ]}
          />
        </div>
        <div className="flex gap-2">
          <input
            value={form.price}
            onChange={(e) => setForm({ ...form, price: e.target.value })}
            inputMode="decimal"
            placeholder={t("connect.pricePh")}
            className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-[12px]"
          />
          <input
            value={form.shares}
            onChange={(e) => setForm({ ...form, shares: e.target.value })}
            inputMode="numeric"
            placeholder={t("connect.sharesPh")}
            className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-[12px]"
          />
        </div>
        <Button size="sm" className="w-full" disabled={check.isPending} onClick={() => void run()}>
          {check.isPending ? (
            <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
          ) : (
            <ShieldCheck className="mr-1 h-3.5 w-3.5" />
          )}
          {t("connect.runCheck")}
        </Button>
      </div>
      {result && (
        <div className="mt-2 border-t border-border/60 pt-2">
          <div
            className={cn(
              "text-[12px] font-medium",
              result.ok ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400",
            )}
          >
            {result.ok ? t("connect.checkPass") : t("connect.checkFail")} · {result.summary}
          </div>
          <div className="mt-1.5 space-y-1">
            {result.checks.map((c) => (
              <div key={c.id} className="flex items-start gap-1.5 text-[10.5px]">
                <span
                  className={cn(
                    "mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full",
                    c.ok ? "bg-emerald-500" : c.level === "block" ? "bg-red-500" : "bg-amber-500",
                  )}
                />
                <span
                  className={cn(
                    "min-w-0 leading-snug",
                    c.ok
                      ? "text-muted-foreground"
                      : c.level === "block"
                        ? "text-red-600 dark:text-red-400"
                        : "text-amber-600 dark:text-amber-400",
                  )}
                >
                  {t(`connect.check.${c.id}`)}: {c.detail}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

/** 风控参数 */
export function RiskSettingsCard() {
  const { t } = useI18n();
  const { toast } = useToast();
  const q = useRiskSettings();
  const save = useSaveRiskSettings();
  const [form, setForm] = useState({ daily_limit: "", deviation_pct: "", concentration_pct: "" });
  const data = q.data;
  const value = (k: "daily_limit" | "deviation_pct" | "concentration_pct") =>
    form[k] !== "" ? form[k] : String(data?.[k] ?? "");
  const submit = async () => {
    try {
      await save.mutateAsync({
        daily_limit: Number(value("daily_limit")),
        deviation_pct: Number(value("deviation_pct")),
        concentration_pct: Number(value("concentration_pct")),
      });
      setForm({ daily_limit: "", deviation_pct: "", concentration_pct: "" });
      toast(t("connect.saved"), "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };
  return (
    <Card className="p-[var(--card-pad)]">
      <div className="mb-1 text-[13px] font-semibold">{t("connect.riskSettingsTitle")}</div>
      <div className="space-y-1.5">
        {(
          [
            ["daily_limit", t("connect.dailyLimit")],
            ["deviation_pct", t("connect.deviationPct")],
            ["concentration_pct", t("connect.concentrationPct")],
          ] as const
        ).map(([key, label]) => (
          <label key={key} className="flex items-center gap-2 text-[11.5px]">
            <span className="min-w-0 flex-1 text-muted-foreground">{label}</span>
            <input
              value={value(key)}
              onChange={(e) => setForm({ ...form, [key]: e.target.value })}
              inputMode="decimal"
              className="w-24 rounded-md border border-border bg-background px-2 py-1 text-[12px] tabular-nums"
            />
          </label>
        ))}
        <Button size="sm" variant="outline" className="w-full" disabled={save.isPending} onClick={() => void submit()}>
          {t("connect.save")}
        </Button>
      </div>
    </Card>
  );
}

/** 条件单 */
export function ConditionalCard() {
  const { t } = useI18n();
  const { toast } = useToast();
  const list = useConditionals();
  const create = useCreateConditional();
  const del = useDeleteConditional();
  const evaluate = useEvaluateConditionals();
  const [form, setForm] = useState({
    symbol: "",
    side: "buy" as "buy" | "sell",
    trigger_type: "price_below",
    trigger_value: "",
    price: "",
    shares: "100",
    mode: "paper" as "paper" | "live",
  });
  const submit = async () => {
    const tv = Number(form.trigger_value);
    const price = Number(form.price);
    const shares = Number(form.shares);
    if (!form.symbol.trim() || !tv || !price || !shares) {
      toast(t("connect.fillRequired"), "error");
      return;
    }
    try {
      await create.mutateAsync({ ...form, symbol: form.symbol.trim(), trigger_value: tv, price, shares });
      toast(t("connect.condCreated"), "ok");
      setForm({ ...form, symbol: "", trigger_value: "", price: "" });
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };
  return (
    <Card className="min-w-0 p-[var(--card-pad)]">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="text-[13px] font-semibold">{t("connect.condTitle")}</div>
        <Button
          size="sm"
          variant="outline"
          disabled={evaluate.isPending}
          onClick={() =>
            void evaluate
              .mutateAsync()
              .then((r) =>
                toast(t("connect.condEvaluated", { checked: r.checked, hit: r.triggered.length }), r.triggered.length ? "ok" : "info"),
              )
              .catch((e) => toast(String(e), "error"))
          }
        >
          <RefreshCw className={cn("mr-1 h-3.5 w-3.5", evaluate.isPending && "animate-spin")} />
          {t("connect.condEvaluate")}
        </Button>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <input
          value={form.symbol}
          onChange={(e) => setForm({ ...form, symbol: e.target.value })}
          placeholder={t("connect.symbolPh")}
          className="rounded-md border border-border bg-background px-2 py-1.5 text-[12px]"
        />
        <select
          value={form.trigger_type}
          onChange={(e) => setForm({ ...form, trigger_type: e.target.value })}
          className="rounded-md border border-border bg-background px-2 py-1.5 text-[12px]"
        >
          <option value="price_below">{t("connect.trigger.price_below")}</option>
          <option value="price_above">{t("connect.trigger.price_above")}</option>
          <option value="pct_change_below">{t("connect.trigger.pct_change_below")}</option>
          <option value="pct_change_above">{t("connect.trigger.pct_change_above")}</option>
        </select>
        <input
          value={form.trigger_value}
          onChange={(e) => setForm({ ...form, trigger_value: e.target.value })}
          inputMode="decimal"
          placeholder={t("connect.triggerValue")}
          className="rounded-md border border-border bg-background px-2 py-1.5 text-[12px]"
        />
        <input
          value={form.price}
          onChange={(e) => setForm({ ...form, price: e.target.value })}
          inputMode="decimal"
          placeholder={t("connect.pricePh")}
          className="rounded-md border border-border bg-background px-2 py-1.5 text-[12px]"
        />
        <input
          value={form.shares}
          onChange={(e) => setForm({ ...form, shares: e.target.value })}
          inputMode="numeric"
          placeholder={t("connect.sharesPh")}
          className="rounded-md border border-border bg-background px-2 py-1.5 text-[12px]"
        />
        <div className="flex flex-wrap items-center gap-1.5">
          <Segmented
            size="sm"
            value={form.side}
            onChange={(v) => setForm({ ...form, side: v })}
            options={[
              { value: "buy", label: t("connect.buy") },
              { value: "sell", label: t("connect.sell") },
            ]}
          />
          <Segmented
            size="sm"
            value={form.mode}
            onChange={(v) => setForm({ ...form, mode: v })}
            options={[
              { value: "paper", label: t("connect.modePaper") },
              { value: "live", label: t("connect.modeLive") },
            ]}
          />
        </div>
      </div>
      <Button size="sm" className="mt-2 w-full" disabled={create.isPending} onClick={() => void submit()}>
        {t("connect.condCreate")}
      </Button>
      <div className="mt-2 border-t border-border/60 pt-2">
        {(list.data ?? []).length === 0 ? (
          <EmptyState mode="compact" text={t("connect.noConditionals")} />
        ) : (
          (list.data ?? []).map((c) => (
            <div
              key={c.id}
              className="flex flex-wrap items-center gap-1.5 border-b border-border/40 py-1.5 text-[11.5px] last:border-0"
            >
              <Badge
                variant={c.status === "watching" ? "outline" : c.status === "triggered" ? "ok" : "muted"}
                className="px-1.5 py-0 text-[10px]"
              >
                {t(`connect.condStatus.${c.status}`)}
              </Badge>
              <span className="font-medium">{c.name || c.symbol}</span>
              <span className="text-muted-foreground">
                {t(`connect.trigger.${c.trigger_type}`)} {c.trigger_value}
              </span>
              <span className="tabular-nums text-muted-foreground">
                {c.side === "buy" ? t("connect.buy") : t("connect.sell")} {c.shares} @ {c.price}
              </span>
              <button
                type="button"
                onClick={() => void del.mutateAsync(c.id)}
                className="ml-auto rounded p-1 text-muted-foreground hover:text-down"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))
        )}
      </div>
      <p className="mt-1 text-[10.5px] leading-relaxed text-muted-foreground">{t("connect.condSafety")}</p>
    </Card>
  );
}

/** 发票归档 */
export function InvoiceCard() {
  const { t } = useI18n();
  const { toast } = useToast();
  const q = useInvoices();
  const upload = useUploadInvoiceText();
  const del = useDeleteInvoice();
  const [text, setText] = useState("");
  const submit = async () => {
    if (!text.trim()) {
      toast(t("connect.invoiceEmpty"), "error");
      return;
    }
    try {
      const res = await upload.mutateAsync({ text });
      toast(res.duplicate ? t("connect.invoiceDuplicate") : t("connect.invoiceSaved"), "ok");
      setText("");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };
  const summary = q.data?.summary;
  return (
    <Card className="min-w-0 p-[var(--card-pad)]">
      <div className="flex items-center gap-1.5 text-[13px] font-semibold">
        <Receipt className="h-4 w-4 text-primary" />
        {t("connect.invoiceTitle")}
      </div>
      <p className="mt-1 text-[10.5px] leading-relaxed text-muted-foreground">{t("connect.invoiceHint")}</p>
      {summary ? (
        <div className="mt-2 grid grid-cols-3 gap-2">
          {[
            { label: t("connect.invoiceCount"), value: String(summary.count) },
            { label: t("connect.invoiceTotal"), value: fmtMoney(summary.total_amount, false, true) },
            { label: t("connect.invoiceTax"), value: fmtMoney(summary.total_tax, false, true) },
          ].map((x) => (
            <div key={x.label} className="rounded-lg bg-muted/25 px-2 py-1.5">
              <div className="text-[10.5px] text-muted-foreground">{x.label}</div>
              <div className="text-[13px] font-semibold tabular-nums">{x.value}</div>
            </div>
          ))}
        </div>
      ) : null}
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={t("connect.invoicePh")}
        className="mt-2 min-h-24 w-full rounded-md border border-border bg-background px-2 py-1.5 font-mono text-[11.5px]"
      />
      <Button size="sm" className="mt-1.5 w-full" disabled={upload.isPending} onClick={() => void submit()}>
        {upload.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
        {t("connect.invoiceParse")}
      </Button>
      <div className="mt-2 border-t border-border/60 pt-2">
        {(q.data?.items ?? []).length === 0 ? (
          <EmptyState mode="compact" text={t("connect.invoiceNone")} />
        ) : (
          (q.data?.items ?? []).slice(0, 8).map((inv) => (
            <div
              key={inv.id}
              className="flex flex-wrap items-center gap-1.5 border-b border-border/40 py-1.5 text-[11px] last:border-0"
            >
              <Badge
                variant={inv.confidence === "high" ? "ok" : inv.confidence === "medium" ? "warn" : "muted"}
                className="px-1.5 py-0 text-[10px]"
              >
                {inv.confidence}
              </Badge>
              <span className="font-medium">{inv.seller || inv.file_name}</span>
              <span className="text-muted-foreground">{inv.invoice_date}</span>
              <span className="tabular-nums">{inv.total_amount != null ? fmtMoney(inv.total_amount) : "-"}</span>
              <span className="text-muted-foreground">{inv.invoice_number}</span>
              <button
                type="button"
                onClick={() => void del.mutateAsync(inv.id)}
                className="ml-auto rounded p-1 text-muted-foreground hover:text-down"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))
        )}
      </div>
    </Card>
  );
}

/** 券商持仓对账导入 */
export function HoldingsImportCard() {
  const { t } = useI18n();
  const { toast } = useToast();
  const importer = useImportHoldings();
  const [content, setContent] = useState("");
  const [result, setResult] = useState<Awaited<ReturnType<typeof importer.mutateAsync>> | null>(null);
  const run = async (apply: boolean) => {
    if (!content.trim()) {
      toast(t("connect.holdingsEmpty"), "error");
      return;
    }
    try {
      const res = await importer.mutateAsync({ content, apply });
      setResult(res);
      toast(
        apply
          ? t("connect.holdingsApplied", { n: res.applied ?? 0 })
          : t("connect.holdingsPreview", { n: res.count }),
        "ok",
      );
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };
  return (
    <Card className="min-w-0 p-[var(--card-pad)]">
      <div className="flex items-center gap-1.5 text-[13px] font-semibold">
        <Banknote className="h-4 w-4 text-primary" />
        {t("connect.holdingsTitle")}
      </div>
      <p className="mt-1 text-[10.5px] leading-relaxed text-muted-foreground">{t("connect.holdingsHint")}</p>
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder={t("connect.holdingsPh")}
        className="mt-2 min-h-32 w-full rounded-md border border-border bg-background px-2 py-1.5 font-mono text-[11px]"
      />
      <div className="mt-1.5 flex gap-2">
        <Button size="sm" variant="outline" disabled={importer.isPending} onClick={() => void run(false)}>
          {t("connect.previewOnly")}
        </Button>
        <Button size="sm" disabled={importer.isPending} onClick={() => void run(true)}>
          {importer.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
          {t("connect.applyImport")}
        </Button>
      </div>
      {result && (
        <div className="mt-2 border-t border-border/60 pt-2">
          <div className="text-[11px] text-muted-foreground">
            {t("connect.holdingsResult", { n: result.count, account: result.account || "-" })}
            {result.skipped ? ` · ${t("connect.holdingsSkipped", { n: result.skipped })}` : ""}
          </div>
          <div className="mt-1 overflow-x-auto scroll-thin">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-left text-[10.5px] text-muted-foreground">
                  <th className="py-1 pr-2 font-normal">{t("connect.colName")}</th>
                  <th className="py-1 pr-2 text-right font-normal">{t("connect.holdShares")}</th>
                  <th className="py-1 pr-2 text-right font-normal">{t("connect.holdCost")}</th>
                  <th className="py-1 text-right font-normal">{t("connect.colPrice")}</th>
                </tr>
              </thead>
              <tbody>
                {result.positions.slice(0, 10).map((p) => (
                  <tr key={p.symbol} className="border-t border-border/40">
                    <td className="py-1 pr-2">
                      <span className="font-medium">{p.name}</span>{" "}
                      <span className="text-muted-foreground">{p.symbol}</span>
                    </td>
                    <td className="py-1 pr-2 text-right tabular-nums">{p.shares}</td>
                    <td className="py-1 pr-2 text-right tabular-nums">{p.cost}</td>
                    <td className="py-1 text-right tabular-nums">{p.last}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.warnings.length > 0 && (
            <div className="mt-1 space-y-0.5">
              {result.warnings.slice(0, 4).map((w) => (
                <div key={w} className="text-[10px] text-amber-600 dark:text-amber-400">
                  {w}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

/** 连接中心深化面板 · 风控：预交易检查、风控参数、条件单。 */

/** 连接中心深化面板（v4.5）：市场温度 / 个股档案 / 预交易检查 / 风控参数 / 条件单 / 发票 / 券商对账。
 *
 * 拆成独立文件：ConnectPage 已 900+ 行，继续内联会让单文件失控；这些面板都只依赖
 * use-connect 的 hooks，彼此独立，按需渲染。
 */

import { useState } from "react";

import { Loader2, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

import { EmptyState } from "@/components/ui/empty-state";
import { Segmented } from "@/components/ui/segmented";
import { useI18n } from "@/lib/i18n";

import { useToast } from "@/lib/toast";
import { cn, errMsg } from "@/lib/utils";
import { useConditionals, useCreateConditional, useDeleteConditional, useEvaluateConditionals, useRiskCheck, useRiskSettings, useSaveRiskSettings, type RiskCheckResult } from "@/lib/use-connect";


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
      toast(errMsg(e), "error");
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
      toast(errMsg(e), "error");
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
      toast(errMsg(e), "error");
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

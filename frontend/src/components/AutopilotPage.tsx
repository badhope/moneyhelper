/** 托管台（4.24.0）。
 *
 * 一屏三件事：
 *   1. 当前三个模式各有多少动作；
 *   2. 每个动作的规则与一次运行结果；
 *   3. 最近决策、边界，以及“我要自己走”的入口。
 *
 * 关键交互：模式切换即保存；“只评估”永远 dry-run；“一键托管”按规则执行，
 * 超出阈值/助理模式会停在“等你确认”，不会偷偷做完。
 */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CalendarCheck,
  CheckCircle2,
  Clock3,
  Loader2,
  Mail,
  ListChecks,
  Play,
  ShieldCheck,
  Sparkles,
  XCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import { fmtMoney } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { DataKind } from "@/lib/views";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type Mode = "manual" | "assist" | "auto";
type Decision = "manual" | "awaiting" | "executed" | "blocked" | "failed";

interface PolicyConfig {
  channel_id?: string;
  max_amount?: number;
  min_confidence?: number;
  [key: string]: unknown;
}

interface Policy {
  action_key: string;
  name: string;
  scope: string;
  description: string;
  boundary: string;
  mode: Mode;
  enabled: boolean;
  config: PolicyConfig;
  updated_at: string;
}

interface Channel {
  channel_id: string;
  label: string;
  kinds: string[];
}

interface DecisionRow {
  id: number;
  action_key: string;
  mode: Mode;
  decision: Decision;
  summary: Record<string, unknown>;
  created_at: string;
}

interface Overview {
  period: string;
  policies: Policy[];
  ready_channels: Channel[];
  stats: { total: number; executed: number; awaiting: number; blocked: number; manual: number };
  mode_counts: Record<Mode, number>;
  recent: DecisionRow[];
}

interface RunResult {
  action_key: string;
  mode: Mode;
  decision: Decision;
  reason?: string;
  period?: string;
  channel_id?: string;
  channel_label?: string;
  packet_id?: string;
  amount?: number;
  max_amount?: number;
  count?: number;
  pending?: number;
  skipped?: number;
  min_confidence?: number;
  requires_confirmation?: boolean;
  confirm_reason?: string;
  dry_run?: boolean;
  outcome?: {
    duplicate?: boolean;
    confirmed?: number;
    delivery?: {
      status?: string;
      receipt?: Record<string, unknown>;
    };
    run?: { status?: string; id?: number; [key: string]: unknown };
    status?: string;
    [key: string]: unknown;
  };
}

const MODE_STYLE: Record<Mode, string> = {
  manual: "border-border bg-muted/50 text-foreground",
  assist: "border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300",
  auto: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
};

const DECISION_STYLE: Record<Decision, string> = {
  manual: "border-border bg-muted/50 text-muted-foreground",
  awaiting: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  executed: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  blocked: "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300",
  failed: "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300",
};

const DECISION_ICON: Record<Decision, typeof CheckCircle2> = {
  manual: Clock3,
  awaiting: AlertTriangle,
  executed: CheckCircle2,
  blocked: ShieldCheck,
  failed: XCircle,
};

const ACTION_LABEL: Record<string, string> = {
  attribution_confirm: "attributionName",
  tax_deliver: "taxName",
  month_end_close: "monthName",
};

const ACTION_DESC: Record<string, string> = {
  attribution_confirm: "attributionDesc",
  tax_deliver: "taxDesc",
  month_end_close: "monthDesc",
};

function actionLabel(t: (key: string) => string, key: string): string {
  const labelKey = ACTION_LABEL[key];
  return labelKey ? t(`autopilot.${labelKey}`) : key;
}

function actionDesc(t: (key: string) => string, key: string): string {
  const descKey = ACTION_DESC[key];
  return descKey ? t(`autopilot.${descKey}`) : "";
}

function ActionCard({
  action,
  channels,
  result,
  busy,
  onMode,
  onSaveConfig,
  onRun,
  onConfirm,
}: {
  action: Policy;
  channels: Channel[];
  result?: RunResult;
  busy: boolean;
  onMode: (mode: Mode, config: PolicyConfig) => void;
  onSaveConfig: (config: PolicyConfig) => void;
  onRun: (dryRun: boolean) => void;
  onConfirm: () => void;
}) {
  const { t } = useI18n();
  const isTax = action.action_key === "tax_deliver";
  const isAttribution = action.action_key === "attribution_confirm";
  const defaultMax = isTax ? 50000 : 10000;
  const [channel, setChannel] = useState(String(action.config.channel_id ?? ""));
  const [maxAmount, setMaxAmount] = useState(String(action.config.max_amount ?? defaultMax));
  const [minConfidence, setMinConfidence] = useState(
    String(action.config.min_confidence ?? 0.7),
  );
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setChannel(String(action.config.channel_id ?? ""));
    setMaxAmount(String(action.config.max_amount ?? defaultMax));
    setMinConfidence(String(action.config.min_confidence ?? 0.7));
    setDirty(false);
  }, [action.config.channel_id, action.config.max_amount, action.config.min_confidence, defaultMax]);

  const configNow = (): PolicyConfig => {
    if (isTax) {
      return {
        ...action.config,
        channel_id: channel,
        max_amount: Number(maxAmount) || 0,
      };
    }
    if (isAttribution) {
      return {
        ...action.config,
        max_amount: Number(maxAmount) || 0,
        min_confidence: Number(minConfidence),
      };
    }
    return action.config;
  };

  const ready = isTax ? channels.length > 0 : true;
  const status = result?.decision;

  return (
    <Card className="relative overflow-hidden border-border/70 p-4">
      <div className="pointer-events-none absolute -right-10 -top-12 h-32 w-32 rounded-full bg-primary/10 blur-3xl" />
      <div className="relative flex items-start gap-3">
        <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          {isTax ? (
            <Mail className="h-4 w-4" />
          ) : isAttribution ? (
            <ListChecks className="h-4 w-4" />
          ) : (
            <CalendarCheck className="h-4 w-4" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <h3 className="text-[14px] font-semibold">{actionLabel(t, action.action_key)}</h3>
            {status ? (
              <Badge className={cn("border px-1.5 py-0 text-[10px]", DECISION_STYLE[status])}>
                {t(`autopilot.decision.${status}`)}
              </Badge>
            ) : (
              <Badge className={cn("border px-1.5 py-0 text-[10px]", ready ? DECISION_STYLE.manual : DECISION_STYLE.blocked)}>
                {ready ? t("autopilot.ready") : t("autopilot.noReadyChannel")}
              </Badge>
            )}
            {!action.enabled ? <Badge variant="muted" className="px-1.5 py-0 text-[10px]">{t("autopilot.disabled")}</Badge> : null}
          </div>
          <p className="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">
            {actionDesc(t, action.action_key)}
          </p>
        </div>
      </div>

      <div className="relative mt-3 grid grid-cols-3 gap-1 rounded-lg bg-muted/40 p-1">
        {(["manual", "assist", "auto"] as Mode[]).map((mode) => (
          <button
            key={mode}
            type="button"
            disabled={busy}
            onClick={() => onMode(mode, configNow())}
            className={cn(
              "rounded-md border px-2 py-1.5 text-[11.5px] font-medium transition disabled:opacity-60",
              action.mode === mode
                ? MODE_STYLE[mode]
                : "border-transparent text-muted-foreground hover:bg-background hover:text-foreground",
            )}
          >
            {t(`autopilot.mode.${mode}`)}
          </button>
        ))}
      </div>
      <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
        {t(`autopilot.mode${action.mode === "manual" ? "Manual" : action.mode === "assist" ? "Assist" : "Auto"}Hint`)}
      </p>

      {isTax && (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <label className="grid gap-1 text-[11px] font-medium text-muted-foreground">
            {t("autopilot.channel")}
            <select
              className="h-9 rounded-md border border-border bg-background px-2 text-[12px] text-foreground"
              value={channel}
              onChange={(e) => {
                setChannel(e.target.value);
                setDirty(true);
                onSaveConfig({
                  ...action.config,
                  channel_id: e.target.value,
                  max_amount: Number(maxAmount) || 0,
                });
              }}
            >
              <option value="">{t("autopilot.channelAuto")}</option>
              {channels.map((c) => (
                <option key={c.channel_id} value={c.channel_id}>
                  {c.label} · {c.channel_id}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-[11px] font-medium text-muted-foreground">
            {t("autopilot.maxAmount")}
            <input
              type="number"
              min={0}
              step={1000}
              className="h-9 rounded-md border border-border bg-background px-2 text-[12px] text-foreground"
              value={maxAmount}
              onChange={(e) => {
                setMaxAmount(e.target.value);
                setDirty(true);
              }}
              onBlur={() => onSaveConfig(configNow())}
            />
          </label>
        </div>
      )}
      {isTax && (
        <p className="mt-1 text-[10.5px] leading-relaxed text-muted-foreground">
          {t("autopilot.maxAmountHint")}
        </p>
      )}

      {isAttribution && (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <label className="grid gap-1 text-[11px] font-medium text-muted-foreground">
            {t("autopilot.batchMaxAmount")}
            <input
              type="number"
              min={0}
              step={1000}
              className="h-9 rounded-md border border-border bg-background px-2 text-[12px] text-foreground"
              value={maxAmount}
              onChange={(e) => {
                setMaxAmount(e.target.value);
                setDirty(true);
              }}
              onBlur={() => onSaveConfig(configNow())}
            />
          </label>
          <label className="grid gap-1 text-[11px] font-medium text-muted-foreground">
            {t("autopilot.minConfidence")}
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              className="h-9 rounded-md border border-border bg-background px-2 text-[12px] text-foreground"
              value={minConfidence}
              onChange={(e) => {
                setMinConfidence(e.target.value);
                setDirty(true);
              }}
              onBlur={() => onSaveConfig(configNow())}
            />
          </label>
        </div>
      )}
      {isAttribution && (
        <p className="mt-1 text-[10.5px] leading-relaxed text-muted-foreground">
          {t("autopilot.minConfidenceHint")}
        </p>
      )}

      {result && (
        <div className={cn("mt-3 rounded-lg border p-2.5 text-[11.5px]", DECISION_STYLE[result.decision])}>
          <div className="flex items-start gap-1.5">
            {(() => {
              const Icon = DECISION_ICON[result.decision];
              return <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" />;
            })()}
            <div className="min-w-0 flex-1">
              {result.decision === "blocked" || result.decision === "failed" ? (
                <p>{t(`autopilot.result${result.decision === "blocked" ? "Blocked" : "Failed"}`, { reason: result.reason ?? "" })}</p>
              ) : result.decision === "awaiting" ? (
                <p>{result.confirm_reason ? t("autopilot.confirmReason", { reason: result.confirm_reason }) : t("autopilot.resultAwaiting")}</p>
              ) : result.decision === "executed" ? (
                <p>
                  {result.outcome?.duplicate
                    ? t("autopilot.resultDuplicate")
                    : isAttribution
                      ? t("autopilot.resultExecutedAttribution", {
                          n: result.outcome?.confirmed ?? result.count ?? 0,
                        })
                      : t("autopilot.resultExecuted")}
                </p>
              ) : (
                <p>
                  {isAttribution
                    ? t("autopilot.resultManualAttribution")
                    : t("autopilot.resultManual")}
                </p>
              )}
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[10.5px] opacity-90">
                {typeof result.amount === "number" && result.amount > 0 && (
                  <span>
                    {t(isAttribution ? "autopilot.attributionAmount" : "autopilot.amount")}{" "}
                    {fmtMoney(result.amount)}
                  </span>
                )}
                {typeof result.count === "number" && result.count > 0 && (
                  <span>{t("autopilot.candidateCount", { n: result.count })}</span>
                )}
                {typeof result.outcome?.confirmed === "number" && result.outcome.confirmed > 0 && (
                  <span>{t("autopilot.confirmedCount", { n: result.outcome.confirmed })}</span>
                )}
                {result.channel_label && <span>{t("autopilot.channelLabel")} {result.channel_label}</span>}
                {result.packet_id && <span>{t("autopilot.packet")} {result.packet_id}</span>}
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {result?.decision === "awaiting" ? (
          <Button size="sm" onClick={onConfirm} disabled={busy}>
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            {t("autopilot.confirmRun")}
          </Button>
        ) : (
          <Button size="sm" onClick={() => onRun(false)} disabled={busy}>
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            {t("autopilot.run")}
          </Button>
        )}
        <Button size="sm" variant="outline" onClick={() => onRun(true)} disabled={busy}>
          {t("autopilot.evaluate")}
        </Button>
        {dirty && (isTax || isAttribution) ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => onSaveConfig(configNow())}
            disabled={busy}
          >
            {t("autopilot.saveRule")}
          </Button>
        ) : null}
      </div>
      <p className="mt-2 text-[10.5px] leading-relaxed text-muted-foreground">{action.boundary}</p>
    </Card>
  );
}

export function AutopilotPage({ onGo }: { onGo: (kind: DataKind) => void }) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  const [results, setResults] = useState<Record<string, RunResult>>({});
  const [lastAll, setLastAll] = useState<RunResult[] | null>(null);
  const [pending, setPending] = useState<string>("");
  const [message, setMessage] = useState("");
  const [messageTone, setMessageTone] = useState<"info" | "error">("info");

  useEffect(() => {
    if (!message || messageTone === "error") return;
    const timer = window.setTimeout(() => setMessage(""), 1800);
    return () => window.clearTimeout(timer);
  }, [message, messageTone]);

  const overview = useQuery({
    queryKey: ["autopilot-overview"],
    queryFn: () => api<Overview>("/api/autopilot/overview"),
  });

  const savePolicy = useMutation({
    mutationFn: (input: { key: string; mode: Mode; enabled: boolean; config: PolicyConfig }) =>
      api(`/api/autopilot/policies/${input.key}`, {
        method: "PUT",
        body: JSON.stringify({ mode: input.mode, enabled: input.enabled, config: input.config }),
      }),
    onSuccess: () => {
      setMessageTone("info");
      setMessage(t("autopilot.saved"));
      void qc.invalidateQueries({ queryKey: ["autopilot-overview"] });
    },
    onError: (err) => {
      setMessageTone("error");
      setMessage(err instanceof Error ? err.message : String(err));
    },
  });

  const runOne = async (key: string, dryRun: boolean, confirm = false) => {
    setPending(key);
    setMessage("");
    setMessageTone("info");
    try {
      const res = await api<RunResult>(`/api/autopilot/actions/${key}/run`, {
        method: "POST",
        body: JSON.stringify({ period, dry_run: dryRun, confirm }),
      });
      setResults((prev) => ({ ...prev, [key]: res }));
      void qc.invalidateQueries({ queryKey: ["autopilot-overview"] });
    } catch (err) {
      setMessageTone("error");
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setPending("");
    }
  };

  const runAll = async (dryRun: boolean) => {
    setPending("all");
    setMessage("");
    setMessageTone("info");
    try {
      const res = await api<{ period: string; results: RunResult[] }>("/api/autopilot/run-all", {
        method: "POST",
        body: JSON.stringify({ period, dry_run: dryRun, confirm: false }),
      });
      setLastAll(res.results);
      setResults((prev) => {
        const next = { ...prev };
        for (const item of res.results) next[item.action_key] = item;
        return next;
      });
      void qc.invalidateQueries({ queryKey: ["autopilot-overview"] });
    } catch (err) {
      setMessageTone("error");
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setPending("");
    }
  };

  const policies = overview.data?.policies ?? [];
  const modeCounts = overview.data?.mode_counts ?? { manual: 0, assist: 0, auto: 0 };
  const stats = overview.data?.stats ?? { total: 0, executed: 0, awaiting: 0, blocked: 0, manual: 0 };
  const channels = overview.data?.ready_channels ?? [];
  const sortedRecent = useMemo(() => overview.data?.recent ?? [], [overview.data?.recent]);

  return (
    <div className="space-y-4">
      <section className="relative overflow-hidden rounded-[var(--radius)] border border-border/70 bg-gradient-to-br from-primary/12 via-background to-sky-500/10 p-4 sm:p-5">
        <div className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-primary/15 blur-3xl" />
        <div className="relative flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.18em] text-primary">
              <Sparkles className="h-3.5 w-3.5" />
              AI Autopilot
            </div>
            <h1 className="mt-1 text-[26px] font-semibold tracking-tight sm:text-[30px]">{t("autopilot.title")}</h1>
            <p className="mt-1 max-w-2xl text-[12.5px] leading-relaxed text-muted-foreground">{t("autopilot.subtitle")}</p>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px]">
              {(["manual", "assist", "auto"] as Mode[]).map((m) => (
                <span key={m} className={cn("rounded-full border px-2 py-0.5", MODE_STYLE[m])}>
                  {t(`autopilot.mode.${m}`)} · {modeCounts[m] ?? 0}
                </span>
              ))}
              <label className="ml-0 sm:ml-2 inline-flex items-center gap-1 rounded-full border border-border bg-background/70 px-2 py-0.5 text-muted-foreground">
                {t("autopilot.period")}
                <input
                  type="month"
                  value={period}
                  onChange={(e) => setPeriod(e.target.value)}
                  className="w-[118px] bg-transparent text-[11px] text-foreground outline-none"
                />
              </label>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <Button onClick={() => void runAll(false)} disabled={pending === "all"}>
              {pending === "all" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Bot className="h-4 w-4" />}
              {t("autopilot.oneClick")}
            </Button>
            <Button variant="outline" onClick={() => void runAll(true)} disabled={pending === "all"}>
              {t("autopilot.evaluate")}
            </Button>
          </div>
        </div>
      </section>

      {overview.isLoading && (
        <Card className="p-4 text-[12px] text-muted-foreground">{t("autopilot.loading")}</Card>
      )}
      {overview.isError && (
        <Card className="border-rose-500/30 p-4 text-[12px] text-rose-700 dark:text-rose-300">
          {t("autopilot.loadFail")}
        </Card>
      )}
      {message && (
        <Card
          className={cn(
            "p-3 text-[12px]",
            messageTone === "error"
              ? "border-rose-500/30 text-rose-700 dark:text-rose-300"
              : "border-sky-500/30 text-sky-700 dark:text-sky-300",
          )}
        >
          {message}
        </Card>
      )}

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[
          ["autopilot.statsTotal", stats.total],
          ["autopilot.statsExecuted", stats.executed],
          ["autopilot.statsAwaiting", stats.awaiting],
          ["autopilot.statsBlocked", stats.blocked],
        ].map(([label, value]) => (
          <Card key={String(label)} className="p-3">
            <div className="text-[10.5px] text-muted-foreground">{t(String(label))}</div>
            <div className="mt-0.5 text-[22px] font-semibold tabular-nums">{Number(value)}</div>
          </Card>
        ))}
      </div>

      <section>
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-1">
          <h2 className="text-[15px] font-semibold">{t("autopilot.listTitle")}</h2>
          <span className="text-[11px] text-muted-foreground">{t("autopilot.listHint")}</span>
        </div>
        {policies.length === 0 && !overview.isLoading ? (
          <Card className="p-4 text-[12px] text-muted-foreground">{t("autopilot.resultEmpty")}</Card>
        ) : (
          <div className="grid gap-3 xl:grid-cols-3">
            {policies.map((action) => (
              <ActionCard
                key={action.action_key}
                action={action}
                channels={channels.filter((c) => c.kinds.includes("tax"))}
                result={results[action.action_key]}
                busy={pending === action.action_key}
                onMode={(mode, config) => {
                  setResults((prev) => {
                    const next = { ...prev };
                    delete next[action.action_key];
                    return next;
                  });
                  setLastAll(null);
                  savePolicy.mutate({
                    key: action.action_key,
                    mode,
                    enabled: true,
                    config,
                  });
                }}
                onSaveConfig={(config) =>
                  savePolicy.mutate({ key: action.action_key, mode: action.mode, enabled: true, config })
                }
                onRun={(dryRun) => void runOne(action.action_key, dryRun, false)}
                onConfirm={() => void runOne(action.action_key, false, true)}
              />
            ))}
          </div>
        )}
      </section>

      {lastAll && (
        <section>
          <div className="mb-2 flex items-center gap-1.5">
            <h2 className="text-[15px] font-semibold">{t("autopilot.resultTitle")}</h2>
            <span className="text-[11px] text-muted-foreground">{lastAll.length} · {period}</span>
          </div>
          <Card className="divide-y divide-border/60 p-0">
            {lastAll.map((r) => {
              const Icon = DECISION_ICON[r.decision];
              return (
                <div key={r.action_key} className="flex flex-wrap items-start gap-2 p-3 text-[12px]">
                  <Icon className="mt-0.5 h-4 w-4 shrink-0" />
                  <span className="font-medium">{actionLabel(t, r.action_key)}</span>
                  <Badge className={cn("border px-1.5 py-0 text-[10px]", DECISION_STYLE[r.decision])}>
                    {t(`autopilot.decision.${r.decision}`)}
                  </Badge>
                  {r.reason && <span className="text-muted-foreground">{r.reason}</span>}
                  {typeof r.amount === "number" && r.amount > 0 && (
                    <span className="text-muted-foreground">{fmtMoney(r.amount)}</span>
                  )}
                </div>
              );
            })}
          </Card>
        </section>
      )}

      <div className="grid gap-3 lg:grid-cols-[1.5fr_1fr]">
        <section className="min-w-0">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-1">
            <h2 className="text-[15px] font-semibold">{t("autopilot.recent")}</h2>
            <span className="text-[11px] text-muted-foreground">{t("autopilot.recentHint")}</span>
          </div>
          {sortedRecent.length === 0 ? (
            <Card className="p-4 text-[12px] text-muted-foreground">{t("autopilot.emptyRecent")}</Card>
          ) : (
            <Card className="divide-y divide-border/60 p-0">
              {sortedRecent.map((d) => {
                const Icon = DECISION_ICON[d.decision];
                return (
                  <div key={d.id} className="flex flex-wrap items-center gap-2 p-2.5 text-[11.5px]">
                    <Icon className="h-3.5 w-3.5 shrink-0" />
                    <Badge className={cn("border px-1.5 py-0 text-[10px]", DECISION_STYLE[d.decision])}>
                      {t(`autopilot.decision.${d.decision}`)}
                    </Badge>
                    <span className="font-medium">{actionLabel(t, d.action_key)}</span>
                    <span className="text-muted-foreground">{d.created_at.slice(0, 16).replace("T", " ")}</span>
                  </div>
                );
              })}
            </Card>
          )}
        </section>

        <aside className="space-y-3">
          <Card className="border-amber-500/25 bg-amber-500/5 p-3">
            <div className="flex items-start gap-2">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
              <p className="text-[11.5px] leading-relaxed text-muted-foreground">{t("autopilot.boundary")}</p>
            </div>
          </Card>
          <Card className="p-3">
            <h3 className="text-[12.5px] font-semibold">{t("autopilot.selfTitle")}</h3>
            <div className="mt-2 grid gap-1.5">
              {[
                ["statements", "autopilot.selfTax"],
                ["external", "autopilot.selfExternal"],
                ["connect", "autopilot.selfConnect"],
                ["ecommerce", "autopilot.selfEcommerce"],
              ].map(([kind, label]) => (
                <button
                  key={kind}
                  type="button"
                  onClick={() => onGo(kind as DataKind)}
                  className="flex items-center justify-between rounded-md border border-border/60 px-2.5 py-2 text-left text-[12px] text-muted-foreground transition hover:bg-accent hover:text-foreground"
                >
                  {t(label)}
                  <ArrowRight className="h-3.5 w-3.5" />
                </button>
              ))}
            </div>
          </Card>
        </aside>
      </div>
    </div>
  );
}

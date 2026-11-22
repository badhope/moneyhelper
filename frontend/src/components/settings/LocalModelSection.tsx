import { useMemo, useState } from "react";
import { ArrowUpRight, ClipboardCopy, Cpu, Download, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { copyText } from "@/lib/clipboard";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { cn, errMsg } from "@/lib/utils";
import {
  LOCAL_ENGINES,
  LOCAL_MODELS,
  findInstalledModel,
  type EngineId,
} from "./local-models";

type ProbeModel = { id: string; owned_by?: string };
type ProbeState = {
  ok: boolean;
  count?: number;
  models?: ProbeModel[];
  error?: string;
};

/** 本地模型入口：选推理端 → 检测本机是否真在跑 → 一键填入 base/model。 */
export function LocalModelSection({
  baseUrl,
  apiKey,
  model,
  onPick,
}: {
  baseUrl: string;
  apiKey: string;
  model: string;
  onPick: (patch: { ai_base_url: string; ai_model: string; ai_api_key?: string }) => void;
}) {
  const { t, lang } = useI18n();
  const { toast } = useToast();
  const current = baseUrl.trim().replace(/\/+$/, "");
  const [engineId, setEngineId] = useState<EngineId>(() => {
    const hit = LOCAL_ENGINES.find((e) => current === e.base);
    return (hit?.id as EngineId) ?? "ollama";
  });
  const [probing, setProbing] = useState(false);
  const [probe, setProbe] = useState<ProbeState | null>(null);

  const engine = useMemo(
    () => LOCAL_ENGINES.find((e) => e.id === engineId) ?? LOCAL_ENGINES[0],
    [engineId],
  );
  const note = (v: { zh: string; en: string }) => (lang === "zh" ? v.zh : v.en);

  // 只有探测成功才把清单当真；失败或未检测时一律不显示“已安装”。
  const installed = probe?.ok && Array.isArray(probe.models) ? probe.models : null;
  const currentModel = model.trim();
  const sameBase = current === engine.base;
  const matched =
    installed && sameBase && currentModel ? findInstalledModel(currentModel, installed) : null;

  const status = probing ? "checking" : probe ? (probe.ok ? "online" : "offline") : "unknown";
  const statusText =
    status === "checking"
      ? t("settings.localModelsStatusChecking")
      : status === "online"
        ? t("settings.localModelsStatusOnline")
        : status === "offline"
          ? t("settings.localModelsStatusOffline")
          : t("settings.localModelsStatusUnknown");
  const statusClass =
    status === "online"
      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
      : status === "offline"
        ? "border-destructive/30 bg-destructive/10 text-destructive"
        : "border-border bg-muted/40 text-muted-foreground";

  const use = (base: string, nextModel: string) => {
    const patch: { ai_base_url: string; ai_model: string; ai_api_key?: string } = {
      ai_base_url: base,
      ai_model: nextModel,
    };
    // 本地端通常不校验 Key，但 llm 配置要求 key 非空才启用；仅在没填过时补一个占位。
    if (!apiKey.trim() || apiKey === "********") patch.ai_api_key = "sk-local";
    onPick(patch);
  };

  const detect = async () => {
    setProbing(true);
    setProbe(null);
    try {
      const r = await api<ProbeState>("/api/models/probe", {
        method: "POST",
        body: JSON.stringify({ base_url: engine.base, api_key: "sk-local" }),
      });
      setProbe(
        r.ok
          ? { ok: true, count: r.count ?? 0, models: Array.isArray(r.models) ? r.models : [] }
          : { ok: false, error: r.error || "unknown", models: [] },
      );
    } catch (e) {
      setProbe({ ok: false, error: errMsg(e), models: [] });
    } finally {
      setProbing(false);
    }
  };

  const copyModel = (m: (typeof LOCAL_MODELS)[number]) => {
    const text =
      engine.id === "ollama"
        ? `ollama pull ${m.endpoints.ollama}`
        : m.endpoints[engine.id];
    if (copyText(text)) toast(t("settings.localModelsCopied"), "ok");
  };

  return (
    <div className="pt-3 mt-1 border-t border-border/60">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-xs font-medium text-foreground/90">
            <Cpu className="h-3.5 w-3.5 text-muted-foreground" />
            {t("settings.localModels")}
          </div>
          <p className="mt-1 text-xs text-muted-foreground/80">{t("settings.localModelsHint")}</p>
        </div>
        <span
          className={cn(
            "shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium",
            statusClass,
          )}
        >
          {statusText}
        </span>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-1.5 sm:grid-cols-4">
        {LOCAL_ENGINES.map((e) => {
          const on = e.id === engineId;
          return (
            <button
              key={e.id}
              type="button"
              aria-pressed={on}
              onClick={() => {
                setEngineId(e.id);
                setProbe(null);
              }}
              className={cn(
                "rounded-lg border px-2.5 py-1.5 text-left text-xs transition-colors",
                on ? "border-primary/40 bg-primary/5 text-foreground" : "border-input/70 text-muted-foreground hover:text-foreground",
              )}
            >
              <span className="font-medium">{e.name}</span>
              <span className="mt-0.5 block truncate text-[10px] opacity-70">{e.base.replace("http://", "")}</span>
            </button>
          );
        })}
      </div>

      <div className="mt-2 rounded-lg border border-input/70 p-2.5 space-y-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <code className="min-w-0 truncate rounded bg-muted px-1.5 py-0.5 text-[10.5px]">{engine.base}</code>
          <Button variant="outline" size="sm" type="button" onClick={() => use(engine.base, engine.defaultModel)}>
            {t("settings.localModelsFill")}
          </Button>
          <Button variant="outline" size="sm" type="button" disabled={probing} onClick={() => void detect()}>
            {probing ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            {probing ? t("settings.localModelsDetecting") : t("settings.localModelsDetect")}
          </Button>
          <a
            href={engine.installUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline"
          >
            {note(engine.installLabel)}
            <ArrowUpRight className="h-3 w-3" />
          </a>
        </div>
        <p className="text-[10.5px] text-muted-foreground/80">{note(engine.note)}</p>

        {currentModel && (
          <div className="flex flex-wrap items-center gap-1.5 text-[10.5px] text-muted-foreground">
            <span>{t("settings.localModelsCurrent", { m: currentModel })}</span>
            {installed && sameBase && (
              <span
                className={cn(
                  "rounded px-1.5 py-0.5 font-medium",
                  matched
                    ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                    : "bg-amber-500/10 text-amber-700 dark:text-amber-300",
                )}
              >
                {matched
                  ? t("settings.localModelsInstalled")
                  : t("settings.localModelsNotInstalled")}
              </span>
            )}
          </div>
        )}

        {probe && (
          <div className="space-y-1.5">
            <div className={cn("text-xs", probe.ok ? "text-emerald-700 dark:text-emerald-300" : "text-destructive")}>
              {probe.ok
                ? t("settings.localModelsConnected", { n: probe.count ?? 0 })
                : t("settings.localModelsFailed", {
                    e: (probe.error ?? "").replace(/^连接失败[：:]\s*/, ""),
                  })}
            </div>
            {probe.ok && installed && installed.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {installed.slice(0, 8).map((m) => (
                  <span
                    key={m.id}
                    className="max-w-full truncate rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
                    title={m.id}
                  >
                    {m.id}
                  </span>
                ))}
                {installed.length > 8 && (
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                    +{installed.length - 8}
                  </span>
                )}
              </div>
            )}
            {probe.ok && installed && installed.length === 0 && (
              <div className="text-[10.5px] text-amber-700 dark:text-amber-300">
                {t("settings.localModelsNoInventory")}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="mt-2 grid grid-cols-1 gap-1.5 sm:grid-cols-2">
        {LOCAL_MODELS.map((m) => (
          <div key={m.id} className="rounded-lg border border-input/70 p-2.5">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <span className="text-xs font-medium text-foreground/90">{m.name}</span>
                <span className="ml-1.5 rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground">{m.params}</span>
              </div>
              <span className="shrink-0 text-[10px] text-muted-foreground/70">{m.size}</span>
            </div>
            <p className="mt-1 text-[10.5px] leading-4 text-muted-foreground/80">{note(m.note)}</p>
            <div className="mt-1.5 flex flex-wrap items-center justify-between gap-1.5">
              <a
                href={m.downloadUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline"
                title={m.downloadUrl}
              >
                <Download className="h-3 w-3" />
                {t("settings.localModelsDownload")}
                <ArrowUpRight className="h-3 w-3" />
              </a>
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="sm" type="button" onClick={() => copyModel(m)}>
                  <ClipboardCopy className="h-3 w-3" />
                  {engine.id === "ollama"
                    ? t("settings.localModelsCopyPull")
                    : t("settings.localModelsCopyName")}
                </Button>
                <Button variant="outline" size="sm" type="button" onClick={() => use(engine.base, m.endpoints[engine.id])}>
                  {t("settings.localModelsFill")}
                </Button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

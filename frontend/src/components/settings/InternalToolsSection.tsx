import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, AlertTriangle, CheckCircle2, Eye, EyeOff, Loader2, PlayCircle, Wrench } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { Section } from "./shared";

interface InternalTool {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
}

interface DiagnosticCheck {
  id: string;
  label: string;
  ok: boolean;
  detail: string;
}

/**
 * 内置优势工具：项目自研的科研/分析工具（确定性计算，不联网）。
 *
 * 这些工具只在应用内部工具面可用，不会进入 MCP Server 的对外清单——界面默认
 * 只显示「有 N 个工具已启用」，具体清单需要点「显示清单」（不对外展示的落点）。
 */
export function InternalToolsSection() {
  const { t } = useI18n();
  const { toast } = useToast();
  const qc = useQueryClient();
  const [revealed, setRevealed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [checks, setChecks] = useState<DiagnosticCheck[] | null>(null);
  const [checking, setChecking] = useState(false);

  const list = useQuery({
    queryKey: ["/api/studio/internal-tools"],
    queryFn: () => api<{ enabled: boolean; tools: InternalTool[]; note: string }>("/api/studio/internal-tools"),
  });
  const wd = useQuery({
    queryKey: ["/api/studio/watchdog"],
    queryFn: () => api<{ status: { running: boolean; last_check_at: string; checks: number; findings: { level: string; message: string }[] }; settings: { enabled: boolean; interval_minutes: number } }>("/api/studio/watchdog"),
  });
  const internal = list.data;
  const enabledCount = (internal?.tools ?? []).filter((x) => x.enabled).length;

  const refresh = async () => {
    await qc.invalidateQueries({ queryKey: ["/api/studio/internal-tools"] });
    await qc.invalidateQueries({ queryKey: ["/api/studio/watchdog"] });
  };

  const toggle = async (id: string, enabled: boolean) => {
    setBusy(true);
    try {
      await api("/api/studio/internal-tools/toggle", {
        method: "POST",
        body: JSON.stringify({ id, enabled }),
      });
      await refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const runDiagnostics = async () => {
    setChecking(true);
    try {
      const r = await api<{ ok: boolean; checks: DiagnosticCheck[] }>("/api/studio/diagnostics");
      setChecks(r.checks);
      toast(r.ok ? t("studio.diagOk") : t("studio.diagIssues"), r.ok ? "ok" : "error");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setChecking(false);
    }
  };

  const runWatchdog = async () => {
    setChecking(true);
    try {
      const r = await api<{ findings: { level: string; message: string }[] }>("/api/studio/watchdog/run", {
        method: "POST",
      });
      await refresh();
      toast(
        r.findings.length ? t("studio.watchdogFindings", { n: r.findings.length }) : t("studio.watchdogClean"),
        r.findings.length ? "error" : "ok",
      );
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setChecking(false);
    }
  };

  const toggleWatchdog = async (enabled: boolean) => {
    try {
      await api("/api/studio/watchdog", { method: "POST", body: JSON.stringify({ enabled }) });
      await refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  return (
    <Section
      title={t("settings.navInternalTools")}
      icon={<Wrench className="w-4 h-4 text-muted-foreground" />}
      desc={t("studio.internalDesc")}
    >
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-2 rounded-lg border border-border px-3 py-2">
          <div className="min-w-0">
            <div className="text-sm font-medium">
              {t("studio.internalEnabled", { n: enabledCount, total: internal?.tools.length ?? 0 })}
            </div>
            <div className="text-[11px] text-muted-foreground">{t("studio.internalVisibility")}</div>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <Button size="sm" variant="ghost" onClick={() => setRevealed((v) => !v)}>
              {revealed ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
              {revealed ? t("studio.hideList") : t("studio.showList")}
            </Button>
            <Switch
              checked={internal?.enabled !== false}
              disabled={busy || !internal}
              onChange={(v) => void toggle("__all__", v)}
              label={t("studio.internalMaster")}
            />
          </div>
        </div>

        {revealed && (
          <ul className="space-y-1.5">
            {(internal?.tools ?? []).map((tool) => (
              <li key={tool.id} className="flex items-start justify-between gap-2 rounded-lg border border-border px-3 py-2">
                <div className="min-w-0">
                  <div className="text-[13px] font-medium">{tool.name}</div>
                  <div className="text-[11px] text-muted-foreground">{tool.description}</div>
                  <div className="mt-0.5 font-mono text-[10px] text-muted-foreground/70">{tool.id}</div>
                </div>
                <Switch
                  checked={tool.enabled}
                  disabled={busy || internal?.enabled === false}
                  onChange={(v) => void toggle(tool.id, v)}
                  label={`${t("studio.toggle")} ${tool.name}`}
                />
              </li>
            ))}
          </ul>
        )}

        <div className="rounded-lg border border-border p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-1.5 text-sm font-medium">
              <Activity className="h-3.5 w-3.5" /> {t("studio.watchdogTitle")}
            </div>
            <Switch
              checked={wd.data?.settings?.enabled !== false}
              onChange={(v) => void toggleWatchdog(v)}
              label={t("studio.watchdogTitle")}
            />
          </div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {t("studio.watchdogDesc", { m: wd.data?.settings?.interval_minutes ?? 15 })}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
            <span>
              {wd.data?.status?.running ? t("studio.watchdogRunning") : t("studio.watchdogStopped")}
              {wd.data?.status?.last_check_at ? ` · ${wd.data.status.last_check_at}` : ""}
            </span>
            <Button size="sm" variant="outline" className="h-7 px-2 text-[11px]" onClick={() => void runWatchdog()} disabled={checking}>
              {checking ? <Loader2 className="h-3 w-3 animate-spin" /> : <PlayCircle className="h-3 w-3" />}
              {t("studio.watchdogRun")}
            </Button>
            <Button size="sm" variant="outline" className="h-7 px-2 text-[11px]" onClick={() => void runDiagnostics()} disabled={checking}>
              <CheckCircle2 className="h-3 w-3" /> {t("studio.diagnostics")}
            </Button>
          </div>
          {checks && (
            <ul className="mt-2 space-y-1">
              {checks.map((c) => (
                <li key={c.id} className="flex items-start gap-1.5 text-[11px]">
                  {c.ok ? (
                    <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-600" />
                  ) : (
                    <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-amber-600" />
                  )}
                  <span className="min-w-0">
                    <span className="font-medium">{c.label}</span>
                    <span className="text-muted-foreground"> · {c.detail}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Section>
  );
}

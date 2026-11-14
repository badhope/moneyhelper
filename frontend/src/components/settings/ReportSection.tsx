import { useCallback, useEffect, useState } from "react";
import { Newspaper, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AiSuggestCard } from "./ai-suggest-card";
import { api } from "@/lib/api";
import { useMutate } from "@/lib/use-mutate";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { fmtDate } from "@/lib/format";
import { isLevelAlert, levelLabel } from "@/lib/level";
import type { RunRecord, SchedulerStatus } from "@/lib/types";
import { Section, inputCls, labelCls } from "./shared";

/** 每日晨报（生成时间 / 立即生成 / 调度状态 / 历史记录折叠） */
export function ReportSection({
  form,
  onField,
  scheduler,
}: {
  form: Record<string, string>;
  onField: (k: string, v: string) => void;
  scheduler: SchedulerStatus;
}) {
  const { t } = useI18n();
  const { toast } = useToast();
  const [reports, setReports] = useState<RunRecord[]>([]);
  const sc = scheduler;

  const loadReports = useCallback(async () => {
    try {
      const d = await api<{ reports: RunRecord[] }>("/api/reports?limit=5");
      setReports(d.reports ?? []);
    } catch {
      /* 晨报历史加载失败不阻塞设置页 */
    }
  }, []);

  useEffect(() => {
    void loadReports();
  }, [loadReports]);

  const generate = useMutate<undefined, { ok: boolean }>({
    fn: async () => {
      const r = await api<{ ok: boolean; skipped?: boolean }>("/api/reports/generate", { method: "POST" });
      if (r.skipped) throw new Error("__SKIPPED__");
      return { ok: r.ok };
    },
    key: undefined,
    silentError: true,
    onSettled: (res, e) => {
      if (e) {
        if (e instanceof Error && e.message === "__SKIPPED__") toast(t("settings.reportNoData"), "error");
        else toast(e instanceof Error ? e.message : String(e), "error");
        return;
      }
      if (!res) return;
      toast(res.ok ? t("settings.reportDone") : t("settings.reportFail"), res.ok ? "ok" : "error");
      void loadReports();
    },
  });

  return (
    <Section title={t("settings.navReport")} icon={<Newspaper className="w-4 h-4 text-muted-foreground" />}>
      <div className="flex items-end gap-2">
        <div className="w-36">
          <label className={labelCls} htmlFor="reportsect-1">{t("settings.reportTime")}</label>
          <input id="reportsect-1" className={inputCls} type="time" value={form.report_time ?? "08:00"} onChange={(e) => onField("report_time", e.target.value)} />
        </div>
        <Button variant="outline" size="sm" onClick={() => generate.mutate(undefined)} disabled={generate.isPending}>
          <RefreshCw className="w-3.5 h-3.5" /> {t("settings.reportGenerate")}
        </Button>
      </div>
      <div className="mt-2 text-xs text-muted-foreground">
        {sc.enabled ? `${t("settings.reportNext")}: ${sc.next_run_at ?? "—"}` : t("settings.reportDisabled")}
        {sc.generated > 0 ? ` · ${t("settings.reportCount", { n: sc.generated })}` : ""}
      </div>

      {/* 关注点：写进 report_focus，晨报生成时会重点结合这一点 */}
      <div className="mt-3">
        <label className={labelCls} htmlFor="report-focus">{t("settings.reportFocus")}</label>
        <div className="flex items-start gap-2">
          <input
            id="report-focus"
            className={inputCls}
            value={form.report_focus ?? ""}
            onChange={(e) => onField("report_focus", e.target.value)}
            placeholder={t("settings.reportFocusPh")}
            maxLength={200}
          />
        </div>
        <div className="mt-1 text-xs text-muted-foreground">{t("settings.reportFocusHint")}</div>
        <div className="mt-2">
          <AiSuggestCard<{ focus: string }>
            title={t("settings.reportAi")}
            hint={t("settings.reportAiHint")}
            endpoint="/api/reports/suggest-focus"
            onAdopt={(s) => {
              onField("report_focus", s.focus);
              toast(t("settings.reportAiApplied"), "ok");
            }}
            renderSuggestion={(s) => <div className="text-xs leading-relaxed">{s.focus}</div>}
          />
        </div>
      </div>
      <details className="mt-3 group">
        <summary className="cursor-pointer list-none text-xs text-muted-foreground hover:text-foreground">
          {t("settings.reportHistory")}{reports.length > 0 ? `（${reports.length}）` : ""}
        </summary>
        {reports.length > 0 && (
          <div className="mt-2 space-y-1.5">
            {reports.map((r) => (
              <details key={r.id} className="rounded-lg border border-border bg-card px-2.5 py-2 text-xs">
                <summary className="flex cursor-pointer items-center justify-between text-muted-foreground">
                  <span>{fmtDate(r.created_at ?? "")}</span>
                  <Badge variant={isLevelAlert(r.level) ? "warn" : "ok"}>{levelLabel(t, r.level)}</Badge>
                </summary>
                <div className="mt-1.5 whitespace-pre-wrap text-foreground">{r.answer}</div>
              </details>
            ))}
          </div>
        )}
      </details>
      <div className="mt-2 text-xs text-muted-foreground">{t("notAdvice")}</div>
    </Section>
  );
}

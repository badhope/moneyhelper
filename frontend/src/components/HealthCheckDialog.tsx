import { useEffect, useState } from "react";
import { HeartPulse, Loader2 } from "lucide-react";
import { SidePanel } from "@/components/ui/side-panel";
import { Badge } from "@/components/ui/badge";
import { fetchHealthCheck } from "@/lib/api";
import type { HealthReport } from "@/lib/types";
import { useI18n } from "@/lib/i18n";
import { errMsg } from "@/lib/utils";

const STATUS_LABEL: Record<string, { text: string; variant: "ok" | "warn" | "danger" }> = {
  good: { text: "hc.good", variant: "ok" },
  warn: { text: "hc.warn", variant: "warn" },
  bad: { text: "hc.bad", variant: "danger" },
};

export function HealthCheckDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useI18n();
  const [report, setReport] = useState<HealthReport | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    let alive = true;
    setReport(null);
    setError("");
    fetchHealthCheck(t("hc.locale"))
      .then((r) => alive && setReport(r))
      .catch((e) => alive && setError(errMsg(e)));
    return () => {
      alive = false;
    };
  }, [open]);

  const scoreColor = report && (report.score >= 80 ? "text-success" : report.score >= 60 ? "text-amber-500" : "text-red-500");

  return (
    <SidePanel
      open={open}
      onClose={() => onOpenChange(false)}
      title={t("hc.title")}
      icon={<HeartPulse className="w-4 h-4 text-primary" />}
      z="z-50"
    >
      {error ? (
        <div className="text-sm text-red-600 dark:text-red-400">{t("hc.error")}: {error}</div>
      ) : !report ? (
        <div className="mt-2 flex items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" /> {t("hc.checking")}
        </div>
      ) : (
        <div className="space-y-3">
          {/* 总分 */}
          <div className="flex items-center justify-between rounded-lg border border-border bg-muted/40 px-3 py-2">
            <span className="text-sm text-muted-foreground">{t("hc.score")}</span>
            <span className={`text-2xl font-semibold tabular-nums ${scoreColor}`}>{report.score}</span>
          </div>
          <p className="text-sm text-balance">{report.summary}</p>

          {/* 各维度 */}
          <div className="space-y-2">
            {report.dimensions.map((d) => {
              const st = STATUS_LABEL[d.status] ?? STATUS_LABEL.good;
              return (
                <div key={d.key} className="rounded-lg border border-border px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">{d.title}</span>
                    <Badge variant={st.variant}>{t(st.text)}</Badge>
                  </div>
                  <p className="mt-1 text-xs text-foreground/80">{d.detail}</p>
                  {d.suggestion && <p className="mt-1 text-xs text-muted-foreground">{t("hc.suggestion")}: {d.suggestion}</p>}
                </div>
              );
            })}
            {report.dimensions.length === 0 && (
              <div className="py-4 text-center text-sm text-muted-foreground">
                {t("hc.notEnough")}
              </div>
            )}
          </div>
          <p className="text-[11px] text-muted-foreground">{t("notAdvice")}</p>
        </div>
      )}
    </SidePanel>
  );
}

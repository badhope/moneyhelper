import { useCallback, useEffect, useState } from "react";
import { RefreshCw, ScrollText, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm";
import { fetchLogs, clearLogs } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { Section } from "./shared";

/** 日志查看：读取后端 moneyhelper.log 最近 N 行，支持刷新与清空 */
export function LogsSection() {
  const { t } = useI18n();
  const [lines, setLines] = useState<string[]>([]);
  // 日志量大时优先看告警：默认只显示 WARNING 及以上，切换「全部」才看 DEBUG 流水
  const [onlyIssues, setOnlyIssues] = useState(true);
  const [loading, setLoading] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);
  const { toast } = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetchLogs(500);
      setLines(r.lines);
    } catch {
      setLines([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const doClear = async () => {
    try {
      const r = await clearLogs();
      toast(`${t("settings.logsCleared")}（${r.cleared_lines} 行）`, "ok");
      setLines([]);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
    setClearOpen(false);
  };

  const isIssue = (l: string) =>
    l.includes("ERROR") || l.includes("CRITICAL") || l.includes("WARNING");
  const visible = onlyIssues ? lines.filter(isIssue) : lines;

  return (
    <Section
      title={t("settings.navLogs")}
      icon={<ScrollText className="w-4 h-4 text-muted-foreground" />}
      desc={t("settings.logsDesc")}
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <div className="inline-flex items-center gap-0.5 rounded-lg bg-muted p-0.5">
          <button
            type="button"
            onClick={() => setOnlyIssues(true)}
            className={
              onlyIssues
                ? "rounded-md bg-card px-2.5 py-1 text-xs font-medium text-foreground shadow-xs"
                : "rounded-md px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground"
            }
          >
            {t("settings.logsProblems")}
          </button>
          <button
            type="button"
            onClick={() => setOnlyIssues(false)}
            className={
              !onlyIssues
                ? "rounded-md bg-card px-2.5 py-1 text-xs font-medium text-foreground shadow-xs"
                : "rounded-md px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground"
            }
          >
            {t("settings.logsAll")}
          </button>
        </div>
        <span className="text-[11px] text-muted-foreground">
          {visible.length} / {lines.length}
        </span>
        <Button size="sm" variant="outline" className="ml-auto" onClick={() => void load()} disabled={loading}>
          <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`} />
          {t("settings.refresh")}
        </Button>
        <Button size="sm" variant="outline" onClick={() => setClearOpen(true)}>
          <Trash2 className="w-3.5 h-3.5 mr-1.5" />
          {t("settings.logsClear")}
        </Button>
      </div>
      <div className="rounded-lg border border-border bg-muted/40 p-3 max-h-96 overflow-auto font-mono text-xs leading-relaxed whitespace-pre-wrap select-all">
        {visible.length === 0 ? (
          <span className="text-muted-foreground">
            {lines.length === 0 ? t("settings.logsEmpty") : t("settings.logsNoProblems")}
          </span>
        ) : (
          visible.map((l, i) => (
            <div
              key={i}
              className={
                l.includes("ERROR") || l.includes("CRITICAL")
                  ? "text-red-500"
                  : l.includes("WARNING")
                    ? "text-amber-500"
                    : ""
              }
            >
              {l}
            </div>
          ))
        )}
      </div>
      <ConfirmDialog
        open={clearOpen}
        onOpenChange={setClearOpen}
        title={t("settings.logsClear")}
        description={t("settings.logsClearConfirm")}
        confirmText={t("settings.confirm")}
        danger
        onConfirm={() => void doClear()}
      />
    </Section>
  );
}

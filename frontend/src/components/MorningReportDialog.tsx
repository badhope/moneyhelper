import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { Loader2, Newspaper } from "lucide-react";
import { SidePanel } from "@/components/ui/side-panel";
import { api } from "@/lib/api";
import { emitInboxRefresh } from "@/lib/inbox";
import { EmptyState } from "@/components/ui/empty-state";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { isLevelAlert, levelLabel } from "@/lib/level";
import { errMsg } from "@/lib/utils";

/** 今日晨报侧面板：手动触发一次晨报（AI 生成 + 数据附注；无 AI 时规则降级），
 *  空库不生成（后端 skipped），markdown 渲染展示；右侧滑出，不遮挡对话。 */
export function MorningReportDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
  const { toast } = useToast();
  const [state, setState] = useState<{ loading: boolean; answer?: string; level?: string; skipped?: boolean }>({
    loading: false,
  });

  useEffect(() => {
    if (!open) return;
    let alive = true;
    setState({ loading: true });
    api<{ ok: boolean; answer?: string; level?: string; skipped?: boolean; reason?: string; error?: string }>("/api/reports/generate", { method: "POST", body: JSON.stringify({}) })
      .then((r) => {
        if (!alive) return;
        setState({ loading: false, answer: r.answer, level: r.level, skipped: r.skipped });
        // 新晨报已归档：刷新收件箱徽标（此面板打开中不会再触发轮询焦点刷新）
        if (!r.skipped) emitInboxRefresh();
      })
      .catch((e) => {
        if (!alive) return;
        setState({ loading: false });
        toast(errMsg(e), "error");
      });
    return () => {
      alive = false;
    };
  }, [open, toast]);

  return (
    <SidePanel
      open={open}
      onClose={() => onOpenChange(false)}
      title={t("report.title")}
      icon={<Newspaper className="w-4 h-4 text-primary" />}
      headerExtra={
        state.level ? (
          <span
            className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${
              isLevelAlert(state.level)
                ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                : "bg-primary/10 text-primary"
            }`}
          >
            {levelLabel(t, state.level)}
          </span>
        ) : undefined
      }
    >
      {state.loading ? (
        <div className="flex h-40 items-center justify-center text-xs text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin mr-2" /> {t("report.generating")}
        </div>
      ) : state.skipped ? (
        <EmptyState mode="compact" text={t("report.noData")} className="py-8" />
      ) : state.answer ? (
        <article className="prose-sm prose-headings:font-semibold prose-p:my-1.5 prose-ul:my-1.5 prose-li:my-0.5 prose-strong:text-foreground max-w-none text-sm leading-relaxed text-muted-foreground [&_h1]:text-base [&_h2]:text-sm [&_h3]:text-sm">
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{state.answer}</ReactMarkdown>
          <p className="mt-3 border-t border-border/60 pt-2 text-[11px] text-muted-foreground/70">{t("notAdvice")}</p>
        </article>
      ) : (
        <EmptyState mode="compact" text={t("report.failed", { e: "" })} className="py-8" />
      )}
    </SidePanel>
  );
}

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { Activity, Inbox, Play, Sunrise, Zap } from "lucide-react";
import { SidePanel } from "@/components/ui/side-panel";
import { EmptyState } from "@/components/ui/empty-state";
import { useI18n } from "@/lib/i18n";
import { fmtDate } from "@/lib/format";
import { levelLabel, isLevelAlert } from "@/lib/level";
import { useAutomation, type AutomationRun } from "@/lib/automation";
import { useScheduledOutputs } from "@/lib/inbox";
import type { ScheduledOutput } from "@/lib/types";

/** 定时产出收件箱：晨报 + 技能触发的统一时间线（最新在前），
 *  打开即整体标读（侧栏徽标随之清零）。 */
export function ScheduledOutputsPanel({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const { outputs, refresh, markAllRead } = useScheduledOutputs();
  const [expanded, setExpanded] = useState<number | null>(null);

  useEffect(() => {
    if (!open) return;
    // 打开时拉最新并整体标读（先拿到列表再写游标，避免把未取到的新产出误标已读）
    void refresh().then((items) => markAllRead(items));
  }, [open, refresh, markAllRead]);

  return (
    <SidePanel
      open={open}
      onClose={onClose}
      title={t("inbox.title")}
      icon={<Inbox className="w-4 h-4 text-primary" />}
      headerExtra={
        outputs && outputs.length > 0 ? (
          <span className="shrink-0 text-[11px] text-muted-foreground">
            {t("inbox.count", { n: outputs.length })}
          </span>
        ) : undefined
      }
    >
      <div className="space-y-5">
        <AutomationSection active={open} />
        <div>
          {outputs === null ? (
            <div className="py-10 text-center text-xs text-muted-foreground">
              {t("app.loading")}
            </div>
          ) : outputs.length === 0 ? (
            <EmptyState mode="compact" text={t("inbox.empty")} className="py-8" />
          ) : (
            <ul className="space-y-2.5">
              {outputs.map((o) => (
                <OutputCard
                  key={o.id}
                  item={o}
                  expanded={expanded === o.id}
                  onToggle={() => setExpanded(expanded === o.id ? null : o.id)}
                />
              ))}
            </ul>
          )}
        </div>
      </div>
    </SidePanel>
  );
}

function AutomationSection({ active }: { active: boolean }) {
  const { t } = useI18n();
  const { workflows, runs, running, run } = useAutomation(active);

  return (
    <section aria-label={t("inbox.autoTitle")}>
      <div className="mb-2 flex items-center gap-2">
        <Activity className="h-3.5 w-3.5 text-primary" />
        <h3 className="text-xs font-semibold text-foreground">{t("inbox.autoTitle")}</h3>
        {runs && runs.length > 0 && (
          <span className="ml-auto text-[11px] text-muted-foreground">
            {t("inbox.autoSteps", { n: runs[0].steps.length })}
          </span>
        )}
      </div>
      <p className="mb-2 text-[11px] leading-relaxed text-muted-foreground">
        {t("inbox.autoHint")}
      </p>
      <div className="space-y-2">
        {workflows.map((w) => (
          <div key={w.key} className="rounded-lg border border-border bg-card/60 px-2.5 py-2">
            <div className="flex items-center gap-2">
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-medium text-foreground">{w.name}</span>
                <span className="block truncate text-[11px] text-muted-foreground">
                  {w.steps.join(" · ")}
                </span>
              </span>
              <button
                type="button"
                onClick={() => void run(w.key)}
                disabled={running !== null}
                className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] text-primary transition-colors hover:bg-primary/10 disabled:opacity-50"
              >
                <Play className="h-3 w-3" />
                {running === w.key ? t("inbox.autoRunning") : t("inbox.autoRun")}
              </button>
            </div>
          </div>
        ))}
      </div>
      {runs === null ? null : runs.length === 0 ? (
        <p className="mt-2 text-[11px] text-muted-foreground">{t("inbox.autoEmpty")}</p>
      ) : (
        <ul className="mt-2 space-y-1.5">
          {runs.slice(0, 4).map((r) => (
            <RunRow key={r.id} run={r} />
          ))}
        </ul>
      )}
    </section>
  );
}

function RunRow({ run }: { run: AutomationRun }) {
  const { t } = useI18n();
  const tone =
    run.status === "done"
      ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
      : run.status === "partial"
        ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
        : run.status === "failed"
          ? "bg-rose-500/15 text-rose-600 dark:text-rose-400"
          : "bg-primary/10 text-primary";
  const label =
    run.status === "done"
      ? t("inbox.autoDone")
      : run.status === "partial"
        ? t("inbox.autoPartial")
        : run.status === "failed"
          ? t("inbox.autoFailed")
          : t("inbox.autoRunning");

  return (
    <li className="flex items-center gap-2 text-[11px]">
      <span className={`shrink-0 rounded-full px-1.5 py-0.5 font-medium ${tone}`}>{label}</span>
      <span className="min-w-0 flex-1 truncate text-muted-foreground">
        {run.workflow_name} · {run.steps.map((s) => s.name).join(" · ")}
      </span>
      <span className="shrink-0 text-muted-foreground">
        {run.duration_ms > 0 ? `${(run.duration_ms / 1000).toFixed(1)}s` : "—"}
      </span>
    </li>
  );
}

function OutputCard({
  item,
  expanded,
  onToggle,
}: {
  item: ScheduledOutput;
  expanded: boolean;
  onToggle: () => void;
}) {
  const { t } = useI18n();
  const isReport = item.kind === "report";
  return (
    <li className="rounded-xl border border-border bg-card p-3">
      <div className="flex items-center gap-2">
        <span
          className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${
            isReport
              ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
              : "bg-sky-500/15 text-sky-600 dark:text-sky-400"
          }`}
        >
          {isReport ? <Sunrise className="w-3 h-3" /> : <Zap className="w-3 h-3" />}
          {isReport ? t("inbox.kindReport") : item.skill_name || t("inbox.kindSkill")}
        </span>
        {item.level && (
          <span
            className={`shrink-0 rounded-full px-1.5 py-0.5 text-[11px] ${
              isLevelAlert(item.level)
                ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                : "bg-primary/10 text-primary"
            }`}
          >
            {levelLabel(t, item.level)}
          </span>
        )}
        <span className="ml-auto shrink-0 text-[11px] text-muted-foreground">{fmtDate(item.created_at)}</span>
      </div>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="mt-1.5 w-full text-left"
      >
        <div className="text-xs text-muted-foreground">{item.question}</div>
        <div
          className={`prose-sm mt-1 max-w-none text-sm leading-relaxed text-foreground/90 ${
            expanded ? "" : "line-clamp-3"
          } [&_h1]:text-base [&_h2]:text-sm [&_h3]:text-sm [&_p]:my-1`}
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>
            {item.answer}
          </ReactMarkdown>
        </div>
        <span className="mt-1 inline-block text-[11px] text-primary">
          {expanded ? t("inbox.collapse") : t("inbox.expand")}
        </span>
      </button>
    </li>
  );
}

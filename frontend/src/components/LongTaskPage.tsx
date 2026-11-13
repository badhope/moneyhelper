import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, FileText, Play, Plus, RefreshCw, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  cancelLongTask,
  createLongTask,
  getLongTask,
  listLongTasks,
  listLongTaskTemplates,
  readLongTaskStage,
  runLongTask,
  type LongTask,
  type LongTaskSummary,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { cn } from "@/lib/utils";

const inputCls =
  "w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring";
const labelCls = "block text-xs text-muted-foreground mb-1";

const STATUS_KEYS: Record<string, string> = {
  pending: "longtask.statusPending",
  running: "longtask.statusRunning",
  done: "longtask.statusDone",
  failed: "longtask.statusFailed",
  cancelled: "longtask.statusCancelled",
  skipped: "longtask.statusSkipped",
};

function StatusPill({ status }: { status: string }) {
  const { t } = useI18n();
  return (
    <span
      className={cn(
        "rounded-full border px-2 py-0.5 text-[11px]",
        status === "done"
          ? "border-emerald-500/40 text-emerald-700"
          : status === "failed"
            ? "border-red-500/40 text-red-700"
            : status === "running"
              ? "border-primary/40 text-primary"
              : "border-border text-muted-foreground",
      )}
    >
      {t(STATUS_KEYS[status] ?? "longtask.statusPending")}
    </span>
  );
}

/**
 * 长任务：把大任务拆成阶段逐段执行，产物落盘可查。
 *
 * 为什么放在主区而不是对话：长任务要连续跑几分钟到几十分钟，
 * 需要看到每阶段状态、失败原因和已产出内容——这些都是结构化状态，
 * 塞进对话流会淹掉。
 */
export function LongTaskPage() {
  const { t } = useI18n();
  const { toast } = useToast();
  const [templates, setTemplates] = useState<{ id: string; label: string; stages: string[] }[]>([]);
  const [tasks, setTasks] = useState<LongTaskSummary[]>([]);
  const [detail, setDetail] = useState<LongTask | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [openStage, setOpenStage] = useState<number | null>(null);
  const [stageText, setStageText] = useState("");
  const [form, setForm] = useState({ kind: "novel", title: "", brief: "" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [tpl, list] = await Promise.all([listLongTaskTemplates(), listLongTasks()]);
      setTemplates(tpl);
      setTasks(list);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const openDetail = async (id: string) => {
    try {
      const task = await getLongTask(id);
      setDetail(task);
      setOpenStage(null);
      setStageText("");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doCreate = async () => {
    if (!form.title.trim() || !form.brief.trim()) return;
    setBusy(true);
    try {
      const r = await createLongTask({
        kind: form.kind,
        title: form.title.trim(),
        brief: form.brief.trim(),
      });
      setForm({ ...form, title: "", brief: "" });
      toast(t("longtask.created"), "ok");
      setDetail(r.task);
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const doRun = async (id: string) => {
    setBusy(true);
    try {
      const r = await runLongTask(id);
      setDetail(r.task);
      toast(t("longtask.finished"), "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const doCancel = async (id: string) => {
    try {
      const r = await cancelLongTask(id);
      setDetail(r.task);
      toast(t("longtask.cancelled"), "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const openArtifact = async (taskId: string, index: number) => {
    if (openStage === index) {
      setOpenStage(null);
      return;
    }
    try {
      const text = await readLongTaskStage(taskId, index);
      setStageText(text || "");
      setOpenStage(index);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const currentTemplate = templates.find((x) => x.id === form.kind);

  return (
    <div className="space-y-3">
      <Card className="p-[var(--card-pad)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-1.5 text-sm font-medium">
              <FileText className="h-4 w-4 text-muted-foreground" />
              {t("longtask.title")}
            </div>
            <div className="mt-1 text-xs text-muted-foreground">{t("longtask.desc")}</div>
          </div>
          <Button size="sm" variant="outline" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={cn("mr-1 h-3.5 w-3.5", loading && "animate-spin")} />
            {t("settings.refresh")}
          </Button>
        </div>
      </Card>

      <Card className="p-[var(--card-pad)]">
        <div className="mb-2 text-sm font-medium">{t("longtask.new")}</div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="w-44">
            <label className={labelCls} htmlFor="lt-kind">{t("longtask.kind")}</label>
            <select
              id="lt-kind"
              className={inputCls}
              value={form.kind}
              onChange={(e) => setForm({ ...form, kind: e.target.value })}
            >
              {templates.map((x) => (
                <option key={x.id} value={x.id}>{x.label}</option>
              ))}
            </select>
          </div>
          <div className="min-w-[220px] flex-1">
            <label className={labelCls} htmlFor="lt-title">{t("longtask.titleLabel")}</label>
            <input
              id="lt-title"
              className={inputCls}
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
            />
          </div>
        </div>
        <div className="mt-2">
          <label className={labelCls} htmlFor="lt-brief">{t("longtask.brief")}</label>
          <textarea
            id="lt-brief"
            className={cn(inputCls, "min-h-[72px]")}
            value={form.brief}
            onChange={(e) => setForm({ ...form, brief: e.target.value })}
          />
        </div>
        {currentTemplate && (
          <div className="mt-2 text-[11.5px] text-muted-foreground">
            {t("longtask.stagesHint")} {currentTemplate.stages.join(" → ")}
          </div>
        )}
        <div className="mt-2">
          <Button size="sm" onClick={() => void doCreate()} disabled={busy}>
            <Plus className="mr-1 h-3.5 w-3.5" />
            {t("longtask.create")}
          </Button>
        </div>
      </Card>

      <Card className="p-[var(--card-pad)]">
        <div className="mb-2 text-sm font-medium">{t("longtask.list")}</div>
        {tasks.length === 0 ? (
          <div className="py-2 text-xs text-muted-foreground">{t("longtask.noTasks")}</div>
        ) : (
          <div className="space-y-1.5">
            {tasks.map((x) => (
              <div
                key={x.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/70 px-3 py-2"
              >
                <button
                  type="button"
                  onClick={() => void openDetail(x.id)}
                  className="min-w-0 text-left"
                >
                  <div className="text-sm font-medium">{x.title}</div>
                  <div className="text-xs text-muted-foreground">
                    {x.done}/{x.total} · {x.created_at}
                  </div>
                </button>
                <div className="flex items-center gap-1.5">
                  <StatusPill status={x.status} />
                  {x.status !== "done" && x.status !== "cancelled" && (
                    <Button size="sm" disabled={busy} onClick={() => void doRun(x.id)}>
                      <Play className="mr-1 h-3.5 w-3.5" />
                      {t("longtask.run")}
                    </Button>
                  )}
                  {x.status === "running" && (
                    <Button size="sm" variant="outline" onClick={() => void doCancel(x.id)}>
                      <Square className="mr-1 h-3.5 w-3.5" />
                      {t("longtask.cancel")}
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {detail && (
        <Card className="p-[var(--card-pad)]">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div className="text-sm font-medium">{detail.title}</div>
            <StatusPill status={detail.status} />
          </div>
          <div className="space-y-1">
            {detail.stages.map((s) => (
              <div key={s.index} className="rounded-lg border border-border/70">
                <button
                  type="button"
                  onClick={() => void openArtifact(detail.id, s.index)}
                  className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
                >
                  <span className="flex min-w-0 items-center gap-1.5 text-sm">
                    {openStage === s.index ? (
                      <ChevronDown className="h-3.5 w-3.5 shrink-0" />
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5 shrink-0" />
                    )}
                    <span className="truncate">{s.name}</span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    {s.chars > 0 && (
                      <span className="text-[11px] text-muted-foreground">{s.chars}</span>
                    )}
                    <StatusPill status={s.status} />
                  </span>
                </button>
                {s.error && (
                  <div className="px-3 pb-2 text-[11.5px] text-red-600">{s.error}</div>
                )}
                {openStage === s.index && (
                  <pre className="max-h-80 overflow-auto whitespace-pre-wrap border-t border-border/70 px-3 py-2 text-[12.5px] leading-relaxed">
                    {stageText || t("longtask.emptyArtifact")}
                  </pre>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

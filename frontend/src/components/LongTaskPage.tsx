import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Download, FileText, Play, Plus, RefreshCw, RotateCcw, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  apiDownloadPost,
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
import { cn, errMsg } from "@/lib/utils";
import { inputCls, labelCls } from "@/components/ui/field";


const STATUS_KEYS: Record<string, string> = {
  pending: "longtask.statusPending",
  running: "longtask.statusRunning",
  done: "longtask.statusDone",
  failed: "longtask.statusFailed",
  cancelled: "longtask.statusCancelled",
  skipped: "longtask.statusSkipped",
};

/** 长任务耗时按人可读格式展示；0/缺失不显示，避免出现“0ms 已完成”的噪声 */
function fmtDuration(ms?: number): string {
  if (!ms || ms < 0) return "";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.round((ms % 60_000) / 1000);
  return `${m}m${s}s`;
}

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
  const [pollingId, setPollingId] = useState<string | null>(null);
  const [form, setForm] = useState({ kind: "novel", title: "", brief: "", success_criteria: "" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [tpl, list] = await Promise.all([listLongTaskTemplates(), listLongTasks()]);
      setTemplates(tpl);
      setTasks(list);
    } catch (e) {
      toast(errMsg(e), "error");
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
      setPollingId(task.status === "running" && task.active !== false ? id : null);
      setOpenStage(null);
      setStageText("");
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };

  // 后台执行 + 轮询：长任务可能跑几十分钟，启动请求立即返回，页面不再被
  // 一次同步 HTTP 请求卡住；每 3 秒刷新阶段状态，终态时给一次明确提示。
  useEffect(() => {
    if (!pollingId) return;
    let disposed = false;
    const tick = async () => {
      try {
        const next = await getLongTask(pollingId);
        if (disposed) return;
        setDetail(next);
        await load();
        const terminal =
          next.status === "done" || next.status === "failed" || next.status === "cancelled";
        const idle = next.active === false;
        if (terminal || idle) {
          setPollingId(null);
          if (terminal) {
            toast(t(next.status === "done" ? "longtask.finished" : next.status === "failed" ? "longtask.failed" : "longtask.cancelled"), next.status === "failed" ? "error" : "ok");
          } else if (next.status === "pending") {
            toast(t("longtask.partialFinished"), "ok");
          }
        }
      } catch (e) {
        if (!disposed) toast(errMsg(e), "error");
      }
    };
    const timer = window.setInterval(() => void tick(), 3000);
    void tick();
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [pollingId, load, t, toast]);

  const doCreate = async () => {
    if (!form.title.trim() || !form.brief.trim()) return;
    setBusy(true);
    try {
      const r = await createLongTask({
        kind: form.kind,
        title: form.title.trim(),
        brief: form.brief.trim(),
        success_criteria: form.success_criteria.trim(),
      });
      setForm({ ...form, title: "", brief: "", success_criteria: "" });
      toast(t("longtask.created"), "ok");
      setDetail(r.task);
      await load();
    } catch (e) {
      toast(errMsg(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const doRun = async (id: string) => {
    setBusy(true);
    try {
      const r = await runLongTask(id, undefined, true);
      setDetail(r.task);
      setPollingId(id);
      toast(t("longtask.started"), "ok");
      await load();
    } catch (e) {
      toast(errMsg(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const doCancel = async (id: string) => {
    try {
      const r = await cancelLongTask(id);
      setDetail(r.task);
      setPollingId(null);
      toast(t("longtask.cancelled"), "ok");
      await load();
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };

  /** 单阶段重跑：只重算目标阶段，已完成的其他阶段与产物保持不动。 */
  const doRetryStage = async (id: string, index: number) => {
    setBusy(true);
    try {
      const r = await runLongTask(id, undefined, true, index);
      setDetail(r.task);
      setPollingId(id);
      toast(t("longtask.stageStarted"), "ok");
      await load();
    } catch (e) {
      toast(errMsg(e), "error");
    } finally {
      setBusy(false);
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
      toast(errMsg(e), "error");
    }
  };

  const currentTemplate = templates.find((x) => x.id === form.kind);
  const stageDone = detail?.stages.filter((s) => s.status === "done").length ?? 0;
  const stageFailed = detail?.stages.filter((s) => s.status === "failed").length ?? 0;
  const stageRetries = detail?.stages.reduce(
    (sum, s) => sum + Math.max(0, (s.attempts ?? 0) - 1),
    0,
  ) ?? 0;

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
        <div className="mt-2">
          <label className={labelCls} htmlFor="lt-criteria">{t("longtask.criteria")}</label>
          <textarea
            id="lt-criteria"
            className={cn(inputCls, "min-h-[56px]")}
            placeholder={t("longtask.criteriaHint")}
            value={form.success_criteria}
            onChange={(e) => setForm({ ...form, success_criteria: e.target.value })}
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
                  {x.status !== "done" && (
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
            <div>
              <div className="text-sm font-medium">{detail.title}</div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                {stageDone}/{detail.stages.length} · {t("longtask.progressDone")}
                {stageFailed > 0 && ` · ${stageFailed} ${t("longtask.progressFailed")}`}
                {stageRetries > 0 && ` · ${stageRetries} ${t("longtask.progressRetried")}`}
              </div>
            </div>
            <StatusPill status={detail.status} />
          </div>
          {detail.success_criteria && (
            <div className="mb-2 rounded-md bg-muted/50 px-2.5 py-1.5 text-[11.5px] text-muted-foreground">
              {t("longtask.criteria")}：{detail.success_criteria}
            </div>
          )}
          {detail.error && (
            <div className="mb-2 rounded-md border border-red-500/30 bg-red-500/5 px-2.5 py-1.5 text-[11.5px] text-red-700">
              {detail.error}
            </div>
          )}
          <div className="space-y-1">
            {detail.stages.map((s) => (
              <div key={s.index} className="rounded-lg border border-border/70">
                <div className="flex items-center gap-1 px-2 py-1">
                  <button
                    type="button"
                    onClick={() => void openArtifact(detail.id, s.index)}
                    className="flex min-w-0 flex-1 items-center justify-between gap-2 px-1 py-1 text-left"
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
                      {(s.attempts ?? 0) > 1 && (
                        <span className="text-[11px] text-amber-700">
                          {t("longtask.attempts", { n: s.attempts ?? 0 })}
                        </span>
                      )}
                      {fmtDuration(s.duration_ms) && (
                        <span className="text-[11px] text-muted-foreground">
                          {fmtDuration(s.duration_ms)}
                        </span>
                      )}
                      {s.chars > 0 && (
                        <span className="text-[11px] text-muted-foreground">{s.chars}</span>
                      )}
                      <StatusPill status={s.status} />
                    </span>
                  </button>
                  {(s.status === "failed" ||
                    s.status === "cancelled" ||
                    s.status === "skipped") && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy}
                      onClick={() => void doRetryStage(detail.id, s.index)}
                    >
                      <RotateCcw className="mr-1 h-3.5 w-3.5" />
                      {t("longtask.stageRetry")}
                    </Button>
                  )}
                </div>
                {s.error && (
                  <div className="px-3 pb-2 text-[11.5px] text-red-600">{s.error}</div>
                )}
                {openStage === s.index && (
                  <div className="border-t border-border/70">
                    {stageText && (
                      <div className="flex justify-end px-3 pt-2">
                        <button
                          type="button"
                          onClick={() =>
                            void apiDownloadPost(
                              "/api/canvas/export",
                              { title: `${detail.title} · ${s.name}`, body: stageText, format: "docx" },
                              `${detail.title}-${s.name}.docx`,
                            ).catch((e) => toast(errMsg(e), "error"))
                          }
                          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground"
                        >
                          <Download className="h-3 w-3" /> {t("longtask.exportWord")}
                        </button>
                      </div>
                    )}
                    <pre className="max-h-80 overflow-auto whitespace-pre-wrap px-3 py-2 text-[12.5px] leading-relaxed">
                      {stageText || t("longtask.emptyArtifact")}
                    </pre>
                  </div>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

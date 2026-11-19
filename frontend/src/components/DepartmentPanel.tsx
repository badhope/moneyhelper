import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { Building2, Check, Clock, Loader2, Send, X } from "lucide-react";
import { SidePanel } from "@/components/ui/side-panel";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { api, apiStream } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { errMsg } from "@/lib/utils";

/** 工单（与后端 dept_models.order_to_dict 对齐） */
export interface DeptOrder {
  id: string;
  dept: "accounting" | "risk" | "invest" | "bookkeeping";
  task: string;
  status: "pending" | "running" | "done" | "failed" | "rejected";
  metrics: Record<string, number>;
  tokens_used: number;
  budget_tokens: number;
  error: string;
}

export interface DeptReport {
  report_id?: string;
  question: string;
  verdict: string;
  report: string;
  orders: DeptOrder[];
  conflicts: { metric: string; detail: string; depts: string[] }[];
  dispatch?: string;
  status?: "pending" | "approved" | "rejected" | "inquired";
  decision_note?: string;
}

const DEPT_ORDER = ["accounting", "risk", "invest", "bookkeeping"] as const;

/** 部门名与图标色（四工位视觉区分） */
const DEPT_META: Record<string, { zh: string; en: string; tint: string }> = {
  accounting: { zh: "会计部", en: "Accounting", tint: "text-amber-600" },
  risk: { zh: "风控部", en: "Risk", tint: "text-red-600" },
  invest: { zh: "投资部", en: "Investing", tint: "text-emerald-600" },
  bookkeeping: { zh: "记账部", en: "Bookkeeping", tint: "text-sky-600" },
};

/**
 * 财务部门实况看板（M3.6）。
 *
 * 交互：输入一句话派工 → 四工位实时显示 running/done → 秘书台出呈批件
 * → 可直接批准/驳回/追问（对应后端 M3.5 的三个审批动作）。
 *
 * 为什么做成面板而非新页面：部门模式是"派完活等结果"的异步动作，
 * 用户派工后往往还想问别的问题。面板不遮挡对话（SidePanel 的既有行为）。
 */
export function DepartmentPanel({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { t, lang } = useI18n();
  const { toast } = useToast();
  const [question, setQuestion] = useState("");
  const [running, setRunning] = useState(false);
  const [orders, setOrders] = useState<DeptOrder[]>([]);
  const [report, setReport] = useState<DeptReport | null>(null);
  const [dispatch, setDispatch] = useState("");
  const [history, setHistory] = useState<DeptReport[]>([]);
  const [note, setNote] = useState("");
  const [noteKind, setNoteKind] = useState<"reject" | "inquire" | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const refreshHistory = useCallback(async () => {
    try {
      const d = await api<{ reports: DeptReport[] }>("/api/department/reports?limit=10");
      setHistory(d.reports ?? []);
    } catch {
      /* 历史加载失败不影响主流程 */
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    void refreshHistory();
    return () => {
      abortRef.current?.abort();
    };
  }, [open, refreshHistory]);

  const run = async () => {
    const q = question.trim();
    if (!q || running) return;
    setRunning(true);
    setOrders([]);
    setReport(null);
    setDispatch("");
    setNote("");
    setNoteKind(null);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      await apiStream(
        "/api/department/stream",
        { question: q, lang },
        (ev) => {
          const kind = String(ev.type ?? "");
          if (kind === "dept_start") {
            setDispatch(String(ev.dispatch ?? ""));
            setOrders((ev.orders as DeptOrder[]) ?? []);
          } else if (kind === "dept" && ev.order) {
            const incoming = ev.order as DeptOrder;
            setOrders((prev) => {
              const idx = prev.findIndex((o) => o.id === incoming.id);
              if (idx < 0) return [...prev, incoming];
              const next = [...prev];
              next[idx] = incoming;
              return next;
            });
          } else if (kind === "dept_report" && ev.report) {
            setReport(ev.report as DeptReport);
            void refreshHistory();
          } else if (kind === "error") {
            toast(String(ev.message ?? "派工失败"), "error");
          }
        },
        ctrl.signal,
      );
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        toast(errMsg(e), "error");
      }
    } finally {
      setRunning(false);
      abortRef.current = null;
    }
  };

  const decide = async (decision: "approve" | "reject" | "inquire") => {
    const rid = report?.report_id;
    if (!rid) return;
    if (decision !== "approve" && !note.trim()) {
      setNoteKind(decision);
      return;
    }
    try {
      const d = await api<{
        ok: boolean;
        report: DeptReport;
        followup_report?: DeptReport;
        error?: string;
      }>(`/api/department/reports/${rid}/decide`, {
        method: "POST",
        body: JSON.stringify({ decision, note: note.trim() }),
      });
      setReport({ ...d.report, status: d.report.status });
      setNote("");
      setNoteKind(null);
      if (d.followup_report) {
        // 追问会产生新呈批件：直接切过去，原呈批件进历史
        setReport(d.followup_report);
        setOrders(d.followup_report.orders ?? []);
        toast(t("dept.inquired"), "ok");
      } else {
        toast(decision === "approve" ? t("dept.approved") : t("dept.rejected"), "ok");
      }
      void refreshHistory();
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };

  return (
    <SidePanel
      open={open}
      onClose={onClose}
      title={t("dept.title")}
      icon={<Building2 className="w-4 h-4 text-primary" />}
    >
      <div className="space-y-4 p-4">
        <p className="text-xs text-muted-foreground">{t("dept.desc")}</p>

        {/* 派工输入 */}
        <div className="flex gap-2">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing) void run();
            }}
            placeholder={t("dept.askPh")}
            disabled={running}
            className="flex-1 rounded-md border border-input bg-background px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-60"
            aria-label={t("dept.askPh")}
          />
          <Button size="sm" onClick={() => void run()} disabled={running || !question.trim()}>
            {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
            <span className="ml-1">{running ? t("dept.running") : t("dept.run")}</span>
          </Button>
        </div>

        {dispatch && (
          <div className="text-[11px] text-muted-foreground">
            {t(`dept.dispatch.${dispatch}`)}
          </div>
        )}

        {/* 四工位 */}
        {orders.length > 0 && (
          <div className="grid grid-cols-2 gap-2" role="list" aria-label={t("dept.title")}>
            {DEPT_ORDER.map((dept) => {
              const o = orders.find((x) => x.dept === dept);
              if (!o) return null;
              const meta = DEPT_META[dept];
              return (
                <div
                  key={o.id}
                  role="listitem"
                  className="rounded-md border border-border bg-card p-2"
                  data-status={o.status}
                >
                  <div className="flex items-center justify-between gap-1">
                    <span className={`text-xs font-medium ${meta.tint}`}>
                      {lang === "zh" ? meta.zh : meta.en}
                    </span>
                    <StatusIcon status={o.status} />
                  </div>
                  <div className="mt-1 line-clamp-2 text-[11px] text-muted-foreground" title={o.task}>
                    {o.task}
                  </div>
                  {o.status === "done" && Object.keys(o.metrics).length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {Object.entries(o.metrics).slice(0, 3).map(([k, v]) => (
                        <span
                          key={k}
                          className="rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground"
                        >
                          {k} {v.toLocaleString()}
                        </span>
                      ))}
                    </div>
                  )}
                  {o.status === "failed" && o.error && (
                    <div className="mt-1 text-[10px] text-red-600">{o.error}</div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* 秘书台：呈批件 */}
        {report && (
          <div className="rounded-md border border-border bg-muted/30 p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-medium">{t("dept.secretary")}</span>
              {report.status && (
                <span className="rounded bg-background px-1.5 py-0.5 text-[10px] text-muted-foreground">
                  {t(`dept.${report.status}`)}
                </span>
              )}
            </div>

            <div className="rounded bg-background p-2 text-[11px]">
              <div className="font-medium">{t("dept.verdict")}</div>
              <div className="mt-0.5 text-foreground/90">{report.verdict}</div>
            </div>

            <div className="mt-2 text-[11px]">
              <div className="font-medium">
                {report.conflicts.length ? t("dept.conflicts") : t("dept.noConflicts")}
              </div>
              {report.conflicts.map((c) => (
                <div key={c.metric} className="mt-0.5 text-red-600">
                  · {c.metric}：{c.detail}
                </div>
              ))}
            </div>

            <button
              type="button"
              className="mt-2 text-[11px] text-primary hover:underline"
              onClick={() => setExpanded(expanded === report.report_id ? null : report.report_id ?? "")}
            >
              {expanded === report.report_id ? t("inbox.collapse") : t("dept.report")}
            </button>
            {expanded === report.report_id && (
              <div className="mt-1 max-h-64 overflow-auto rounded border border-border bg-background p-2 text-[11px]">
                <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>
                  {report.report}
                </ReactMarkdown>
              </div>
            )}

            {/* 审批动作：只有 pending 才显示 */}
            {report.status === "pending" && report.report_id && (
              <div className="mt-3 space-y-2">
                {noteKind && (
                  <input
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder={
                      noteKind === "reject" ? t("dept.rejectNotePh") : t("dept.inquireNotePh")
                    }
                    className="w-full rounded border border-input bg-background px-2 py-1 text-[11px]"
                  />
                )}
                <div className="flex gap-1.5">
                  <Button size="sm" className="h-9 px-3 text-xs md:h-7 md:px-2 md:text-[11px]" onClick={() => void decide("approve")}>
                    <Check className="w-3 h-3 mr-1" />
                    {t("dept.approve")}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-9 px-3 text-xs md:h-7 md:px-2 md:text-[11px]"
                    onClick={() => void decide("reject")}
                  >
                    <X className="w-3 h-3 mr-1" />
                    {t("dept.reject")}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-9 px-3 text-xs md:h-7 md:px-2 md:text-[11px]"
                    onClick={() => void decide("inquire")}
                  >
                    {t("dept.inquire")}
                  </Button>
                </div>
              </div>
            )}

            {report.status && report.status !== "pending" && (
              <div className="mt-2 text-[11px] text-muted-foreground">
                {t("dept.decided")}
                {report.decision_note ? `：${report.decision_note}` : ""}
              </div>
            )}
          </div>
        )}

        {/* 历史呈批件 */}
        <div>
          <div className="mb-1.5 text-xs font-medium">{t("dept.history")}</div>
          {history.length === 0 ? (
            <EmptyState title={t("dept.empty")} />
          ) : (
            <ul className="space-y-1">
              {history.map((r) => (
                <li key={r.report_id}>
                  <button
                    type="button"
                    className="w-full rounded border border-border bg-card px-2 py-1.5 text-left text-[11px] hover:bg-muted/50"
                    onClick={() => {
                      setReport(r);
                      setOrders(r.orders ?? []);
                      setExpanded(null);
                    }}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="line-clamp-1">{r.question}</span>
                      <span className="shrink-0 text-muted-foreground">
                        {t(`dept.${r.status ?? "pending"}`)}
                      </span>
                    </div>
                    <div className="mt-0.5 line-clamp-1 text-muted-foreground">{r.verdict}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </SidePanel>
  );
}

function StatusIcon({ status }: { status: DeptOrder["status"] }) {
  if (status === "running") return <Loader2 className="w-3 h-3 animate-spin text-primary" />;
  if (status === "done") return <Check className="w-3 h-3 text-emerald-600" />;
  if (status === "failed") return <X className="w-3 h-3 text-red-600" />;
  return <Clock className="w-3 h-3 text-muted-foreground" />;
}

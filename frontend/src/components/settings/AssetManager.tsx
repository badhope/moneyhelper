import { useCallback, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download, FileJson, Loader2, Pencil, Plus, RefreshCw, Sparkles, Trash2, Upload, Wand2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { ConfirmDialog } from "@/components/ui/confirm";
import { api } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Section, inputCls, labelCls } from "./shared";

type Kind = "prompts" | "rules" | "hooks" | "roles" | "skills";

interface Asset {
  id: string;
  name: string;
  description?: string;
  enabled?: boolean;
  builtin?: boolean;
  content?: string;
  category?: string;
  priority?: number;
  severity?: string;
  scope?: string;
  event?: string;
  action?: string;
  match?: string;
  payload?: string;
  instructions?: string;
  tools?: unknown;
  temperature?: number;
}

export interface FieldSpec {
  key: keyof Asset;
  labelKey: string;
  type: "text" | "textarea" | "select" | "number";
  options?: { value: string; label: string }[];
  placeholderKey?: string;
  rows?: number;
}

const SCHEMAS: Record<Kind, FieldSpec[]> = {
  prompts: [
    { key: "name", labelKey: "studio.fieldName", type: "text" },
    { key: "description", labelKey: "studio.fieldDesc", type: "text" },
    { key: "content", labelKey: "studio.fieldContent", type: "textarea", rows: 6 },
    { key: "priority", labelKey: "studio.fieldPriority", type: "number" },
  ],
  rules: [
    { key: "name", labelKey: "studio.fieldName", type: "text" },
    { key: "description", labelKey: "studio.fieldDesc", type: "text" },
    {
      key: "severity",
      labelKey: "studio.fieldSeverity",
      type: "select",
      options: [
        { value: "must", label: "must" },
        { value: "should", label: "should" },
        { value: "may", label: "may" },
      ],
    },
    {
      key: "scope",
      labelKey: "studio.fieldScope",
      type: "select",
      options: [
        { value: "all", label: "all" },
        { value: "finance", label: "finance" },
        { value: "research", label: "research" },
      ],
    },
    { key: "content", labelKey: "studio.fieldContent", type: "textarea", rows: 4 },
  ],
  hooks: [
    { key: "name", labelKey: "studio.fieldName", type: "text" },
    { key: "description", labelKey: "studio.fieldDesc", type: "text" },
    {
      key: "event",
      labelKey: "studio.fieldEvent",
      type: "select",
      options: [
        { value: "pre_tool", label: "pre_tool" },
        { value: "pre_prompt", label: "pre_prompt" },
        { value: "post_answer", label: "post_answer" },
      ],
    },
    {
      key: "action",
      labelKey: "studio.fieldAction",
      type: "select",
      options: [
        { value: "block", label: "block" },
        { value: "warn", label: "warn" },
        { value: "log", label: "log" },
        { value: "inject", label: "inject" },
      ],
    },
    { key: "match", labelKey: "studio.fieldMatch", type: "text" },
    { key: "payload", labelKey: "studio.fieldPayload", type: "textarea", rows: 3 },
    { key: "priority", labelKey: "studio.fieldPriority", type: "number" },
  ],
  roles: [
    { key: "name", labelKey: "studio.fieldName", type: "text" },
    { key: "description", labelKey: "studio.fieldDesc", type: "text" },
    { key: "instructions", labelKey: "studio.fieldInstructions", type: "textarea", rows: 6 },
    { key: "temperature", labelKey: "studio.fieldTemperature", type: "number" },
  ],
  skills: [
    { key: "name", labelKey: "studio.fieldName", type: "text" },
    { key: "description", labelKey: "studio.fieldDesc", type: "text" },
    { key: "content", labelKey: "studio.fieldContent", type: "textarea", rows: 5 },
  ],
};

/**
 * 通用资产管理器：提示词 / 约束 / Hook / 角色 / 技能共用。
 *
 * 四条添加通道（每个页面都有）：手写模板、拖拽导入（md/json/yaml/zip）、
 * AI 一键生成、对话内添加（提示用户去问答里说一句话）。列表支持开关/编辑/删除。
 */
export function AssetManager({
  kind,
  titleKey,
  descKey,
  hintKey,
}: {
  kind: Kind;
  titleKey: string;
  descKey: string;
  hintKey?: string;
}) {
  const { t } = useI18n();
  const { toast } = useToast();
  const qc = useQueryClient();
  const fields = SCHEMAS[kind];
  const list = useQuery({
    queryKey: ["/api/studio", kind],
    queryFn: () => api<{ assets: Asset[] }>(`/api/studio/${kind}`).then((r) => r.assets ?? []),
  });
  const assets = list.data ?? [];
  const [mode, setMode] = useState<"none" | "form" | "ai" | "import">("none");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Asset | null>(null);
  const [busy, setBusy] = useState(false);
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiSuggestion, setAiSuggestion] = useState<Asset | null>(null);
  const [importErrors, setImportErrors] = useState<{ file: string; error: string }[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [fileEl, setFileEl] = useState<HTMLInputElement | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [lastRun, setLastRun] = useState<{ id: string; answer: string } | null>(null);

  const refresh = useCallback(
    () => qc.invalidateQueries({ queryKey: ["/api/studio", kind] }),
    [qc, kind],
  );

  const startCreate = async () => {
    try {
      const r = await api<{ template: Record<string, unknown> }>(`/api/studio/templates/${kind}`);
      const next: Record<string, string> = {};
      for (const f of fields) next[f.key as string] = String(r.template[f.key as string] ?? "");
      setDraft(next);
      setEditing(null);
      setMode("form");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const startEdit = (a: Asset) => {
    const next: Record<string, string> = {};
    for (const f of fields) next[f.key as string] = String(a[f.key] ?? "");
    const action = (a as unknown as { action?: { prompt?: string; time?: string; weekdays?: number[] } })
      .action;
    if (kind === "skills" && action) {
      next.action_prompt = String(action.prompt ?? "");
      next.action_time = String(action.time ?? "20:00");
      next.action_weekdays = (action.weekdays ?? []).join(",");
    }
    setDraft(next);
    setEditing(a.id);
    setMode("form");
  };

  /** 技能定时动作（仅 skills）：与后端 normalize_skill_action 同口径。 */
  const skillAction = (): Record<string, unknown> | null => {
    const prompt = (draft.action_prompt ?? "").trim();
    if (!prompt) return null;
    const time = /^([01][0-9]|2[0-3]):[0-5][0-9]$/.test(draft.action_time ?? "")
      ? draft.action_time
      : "20:00";
    const days = (draft.action_weekdays ?? "")
      .split(/[,，\s]+/)
      .map((x) => Number(x))
      .filter((x) => Number.isInteger(x) && x >= 0 && x <= 6);
    return { prompt, time, weekdays: days };
  };

  const runNow = async (a: Asset) => {
    setRunning(a.id);
    try {
      const r = await api<{ ok: boolean; answer?: string; error?: string }>(
        `/api/skills/${encodeURIComponent(a.id)}/run`,
        { method: "POST" },
      );
      if (!r.ok) throw new Error(r.error || t("studio.runFail"));
      setLastRun({ id: a.id, answer: String(r.answer ?? "") });
      toast(t("studio.runOk"), "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setRunning(null);
    }
  };

  const save = async () => {
    setBusy(true);
    try {
      const body: Record<string, unknown> = { ...draft };
      delete body.action_prompt;
      delete body.action_time;
      delete body.action_weekdays;
      if (kind === "prompts" || kind === "hooks") body.priority = Number(draft.priority) || 50;
      if (kind === "roles") body.temperature = Number(draft.temperature) || 0.2;
      if (kind === "skills") body.action = skillAction();
      const path = editing ? `/api/studio/${kind}/${encodeURIComponent(editing)}` : `/api/studio/${kind}`;
      const r = await api<{ ok: boolean; error?: string }>(path, {
        method: editing ? "PATCH" : "POST",
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(r.error || t("studio.saveFail"));
      await refresh();
      setMode("none");
      toast(editing ? t("studio.updated") : t("studio.created"), "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (a: Asset) => {
    try {
      await api(`/api/studio/${kind}/${encodeURIComponent(a.id)}/toggle`, {
        method: "POST",
        body: JSON.stringify({ enabled: !a.enabled }),
      });
      await refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const remove = async (a: Asset) => {
    try {
      // 内置资产：确认框已明确提示，这里按 force 删除（用户可删可关，不是只读）
      const force = a.builtin ? "true" : "false";
      await api(`/api/studio/${kind}/${encodeURIComponent(a.id)}?force=${force}`, { method: "DELETE" });
      await refresh();
      toast(t("studio.deleted", { name: a.name }), "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const uploadFiles = async (files: File[]) => {
    if (!files.length) return;
    setBusy(true);
    setImportErrors([]);
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    fd.append("kind", kind);
    try {
      const r = await api<{ ok: boolean; saved: { name: string }[]; errors: { file: string; error: string }[] }>(
        "/api/studio/import",
        { method: "POST", body: fd },
      );
      setImportErrors(r.errors ?? []);
      await refresh();
      if (r.saved?.length) toast(t("studio.imported", { n: r.saved.length }), "ok");
      if (!r.saved?.length && !r.errors?.length) toast(t("studio.importEmpty"), "error");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const generate = async () => {
    if (!aiPrompt.trim()) return;
    setBusy(true);
    setAiSuggestion(null);
    try {
      const r = await api<{ ok: boolean; suggestion?: Asset; error?: string }>("/api/studio/generate", {
        method: "POST",
        body: JSON.stringify({ kind, prompt: aiPrompt }),
      });
      if (!r.ok || !r.suggestion) throw new Error(r.error || t("studio.aiFail"));
      setAiSuggestion(r.suggestion);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const applySuggestion = async () => {
    if (!aiSuggestion) return;
    setBusy(true);
    try {
      const r = await api<{ ok: boolean; error?: string }>("/api/studio/generate/apply", {
        method: "POST",
        body: JSON.stringify({ kind, asset: aiSuggestion }),
      });
      if (!r.ok) throw new Error(r.error || t("studio.aiFail"));
      await refresh();
      setMode("none");
      setAiSuggestion(null);
      setAiPrompt("");
      toast(t("studio.created"), "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const toolbar = useMemo(
    () => (
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => void startCreate()}>
          <Plus className="h-3.5 w-3.5" /> {t("studio.writeByTemplate")}
        </Button>
        <Button size="sm" variant="outline" onClick={() => setMode(mode === "import" ? "none" : "import")}>
          <Upload className="h-3.5 w-3.5" /> {t("studio.dragImport")}
        </Button>
        <Button size="sm" variant="outline" onClick={() => setMode(mode === "ai" ? "none" : "ai")}>
          <Sparkles className="h-3.5 w-3.5" /> {t("studio.aiGenerate")}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => void refresh()} disabled={busy}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          {t("studio.refresh")}
        </Button>
      </div>
    ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [mode, busy, t],
  );

  return (
    <Section title={t(titleKey)} icon={<Wand2 className="w-4 h-4 text-muted-foreground" />} desc={t(descKey)}>
      <div className="space-y-3">
        {toolbar}
        <p className="text-[11px] text-muted-foreground">{t("studio.chatHint")}</p>

        {mode === "import" && (
          <div
            className={cn(
              "rounded-lg border border-dashed px-3 py-6 text-center transition-colors",
              dragOver ? "border-primary bg-primary/5" : "border-border",
            )}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              void uploadFiles(Array.from(e.dataTransfer.files ?? []));
            }}
          >
            <FileJson className="mx-auto mb-2 h-6 w-6 text-muted-foreground/60" />
            <p className="text-xs text-muted-foreground">{t("studio.dropHint")}</p>
            <div className="mt-2 flex items-center justify-center gap-2">
              <Button size="sm" variant="outline" onClick={() => fileEl?.click()} disabled={busy}>
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
                {t("studio.pickFile")}
              </Button>
              <input
                ref={setFileEl}
                type="file"
                multiple
                className="hidden"
                accept=".md,.markdown,.txt,.json,.yaml,.yml,.zip"
                onChange={(e) => {
                  const files = Array.from(e.target.files ?? []);
                  e.target.value = "";
                  void uploadFiles(files);
                }}
              />
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">{t("studio.formatHint")}</p>
            {importErrors.length > 0 && (
              <ul className="mt-2 space-y-1 text-left">
                {importErrors.map((e, i) => (
                  <li key={i} className="rounded bg-red-500/10 px-2 py-1 text-[11px] text-red-600">
                    {e.file}：{e.error}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {mode === "ai" && (
          <div className="rounded-lg border border-primary/30 bg-primary/5 p-3">
            <textarea
              className={`${inputCls} min-h-20 text-xs`}
              placeholder={t("studio.aiPlaceholder")}
              value={aiPrompt}
              onChange={(e) => setAiPrompt(e.target.value)}
              maxLength={500}
            />
            <div className="mt-2 flex items-center gap-2">
              <Button size="sm" onClick={() => void generate()} disabled={busy || !aiPrompt.trim()}>
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                {t("studio.aiGenerate")}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setMode("none")}>
                {t("studio.cancel")}
              </Button>
            </div>
            {aiSuggestion && (
              <div className="mt-2 rounded-lg border border-border bg-card p-2.5">
                <div className="text-sm font-medium">{aiSuggestion.name}</div>
                <div className="mt-0.5 text-xs text-muted-foreground">{aiSuggestion.description}</div>
                <pre className="mt-1.5 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-muted/50 p-2 text-[11px]">
                  {String(
                    aiSuggestion.content ?? aiSuggestion.instructions ?? aiSuggestion.payload ?? "",
                  )}
                </pre>
                <div className="mt-2 flex gap-2">
                  <Button size="sm" onClick={() => void applySuggestion()} disabled={busy}>
                    {t("studio.apply")}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => void generate()} disabled={busy}>
                    {t("studio.regenerate")}
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}

        {mode === "form" && (
          <div className="rounded-lg border border-border p-3">
            <div className="grid gap-2 sm:grid-cols-2">
              {fields.map((f) => (
                <div key={String(f.key)} className={f.type === "textarea" ? "sm:col-span-2" : ""}>
                  <label className={labelCls}>{t(f.labelKey)}</label>
                  {f.type === "textarea" ? (
                    <textarea
                      className={`${inputCls} text-xs`}
                      rows={f.rows ?? 4}
                      value={draft[f.key as string] ?? ""}
                      onChange={(e) => setDraft((d) => ({ ...d, [f.key as string]: e.target.value }))}
                    />
                  ) : f.type === "select" ? (
                    <select
                      className={inputCls}
                      value={draft[f.key as string] ?? ""}
                      onChange={(e) => setDraft((d) => ({ ...d, [f.key as string]: e.target.value }))}
                    >
                      {(f.options ?? []).map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type={f.type === "number" ? "number" : "text"}
                      className={inputCls}
                      value={draft[f.key as string] ?? ""}
                      onChange={(e) => setDraft((d) => ({ ...d, [f.key as string]: e.target.value }))}
                    />
                  )}
                </div>
              ))}
              {kind === "skills" && (
                <div className="sm:col-span-2 rounded-md border border-dashed border-primary/30 bg-primary/5 p-2.5">
                  <div className="text-[11px] text-muted-foreground">{t("studio.actionHint")}</div>
                  <div className="mt-1 grid gap-2 sm:grid-cols-[1fr_8rem_8rem]">
                    <input
                      className={inputCls}
                      placeholder={t("studio.actionPromptPh")}
                      value={draft.action_prompt ?? ""}
                      maxLength={200}
                      onChange={(e) => setDraft((d) => ({ ...d, action_prompt: e.target.value }))}
                    />
                    <input
                      type="time"
                      className={inputCls}
                      value={draft.action_time ?? "20:00"}
                      onChange={(e) => setDraft((d) => ({ ...d, action_time: e.target.value }))}
                    />
                    <input
                      className={inputCls}
                      placeholder={t("studio.actionWeekdaysPh")}
                      value={draft.action_weekdays ?? ""}
                      onChange={(e) => setDraft((d) => ({ ...d, action_weekdays: e.target.value }))}
                    />
                  </div>
                </div>
              )}
            </div>
            <div className="mt-2 flex items-center gap-2">
              <Button size="sm" onClick={() => void save()} disabled={busy}>
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                {editing ? t("studio.save") : t("studio.create")}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setMode("none")}>
                {t("studio.cancel")}
              </Button>
            </div>
          </div>
        )}

        {hintKey && (
          <p className="rounded-lg bg-muted/50 px-3 py-2 text-[11.5px] leading-relaxed text-muted-foreground">
            {t(hintKey)}
          </p>
        )}

        {list.isPending ? (
          <p className="py-3 text-center text-xs text-muted-foreground">{t("studio.loading")}</p>
        ) : assets.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-xs text-muted-foreground">
            {t("studio.empty")}
          </div>
        ) : (
          <ul className="space-y-1.5">
            {assets.map((a) => (
              <li key={a.id} className="rounded-lg border border-border px-3 py-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-1.5 text-[13px] font-medium">
                      {a.name}
                      {a.builtin && (
                        <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">
                          {t("studio.builtin")}
                        </span>
                      )}
                      {kind === "hooks" && a.action && (
                        <span className="rounded bg-sky-500/10 px-1.5 py-0.5 font-mono text-[10px] text-sky-600 dark:text-sky-400">
                          {a.event}/{a.action}
                        </span>
                      )}
                      {kind === "rules" && a.severity && (
                        <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                          {a.severity}
                        </span>
                      )}
                    </div>
                    <div className="mt-0.5 text-[11.5px] text-muted-foreground">{a.description}</div>
                    {kind === "skills" &&
                      (a as unknown as { action?: { time?: string; weekdays?: number[] } }).action && (
                        <div className="mt-0.5 text-[10.5px] text-sky-600 dark:text-sky-400">
                          {t("studio.scheduled", {
                            time: String(
                              (a as unknown as { action?: { time?: string } }).action?.time ?? "",
                            ),
                            days:
                              (
                                (a as unknown as { action?: { weekdays?: number[] } }).action
                                  ?.weekdays ?? []
                              ).join(",") || t("studio.everyDay"),
                          })}
                        </div>
                      )}
                    {(a.match || a.content) && (
                      <div className="mt-1 line-clamp-2 whitespace-pre-wrap font-mono text-[10.5px] text-muted-foreground/80">
                        {a.match || a.content || a.instructions}
                      </div>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    {kind === "skills" && (a as unknown as { action?: unknown }).action ? (
                      <button
                        type="button"
                        aria-label={`${t("studio.runNow")} ${a.name}`}
                        className="rounded px-1.5 py-0.5 text-[10.5px] text-muted-foreground hover:bg-primary/10 hover:text-primary disabled:opacity-50"
                        disabled={running === a.id}
                        onClick={() => void runNow(a)}
                      >
                        {running === a.id ? t("studio.running") : t("studio.runNow")}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      aria-label={`${t("studio.edit")} ${a.name}`}
                      className="rounded p-1.5 text-muted-foreground hover:bg-primary/10 hover:text-primary"
                      onClick={() => startEdit(a)}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      aria-label={`${t("studio.delete")} ${a.name}`}
                      className="rounded p-1.5 text-muted-foreground hover:bg-red-500/10 hover:text-red-600"
                      onClick={() => setPendingDelete(a)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                    <Switch
                      checked={a.enabled !== false}
                      onChange={() => void toggle(a)}
                      label={`${t("studio.toggle")} ${a.name}`}
                    />
                  </div>
                </div>
                {lastRun?.id === a.id && lastRun.answer && (
                  <div className="mt-1.5 whitespace-pre-wrap rounded-md border border-border bg-muted/30 p-2 text-[11px]">
                    {lastRun.answer.slice(0, 400)}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(v) => {
          if (!v) setPendingDelete(null);
        }}
        title={t("studio.deleteTitle", { name: pendingDelete?.name ?? "" })}
        description={
          pendingDelete?.builtin ? t("studio.deleteBuiltinDesc") : t("studio.deleteDesc")
        }
        confirmText={t("studio.delete")}
        danger
        onConfirm={async () => {
          if (pendingDelete) await remove(pendingDelete);
          setPendingDelete(null);
        }}
      />
    </Section>
  );
}

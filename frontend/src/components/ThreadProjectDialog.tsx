import { useEffect, useMemo, useState } from "react";
import { Brain, Check, FileText, FolderKanban, Loader2, Plus, X } from "lucide-react";
import {
  createChatProject,
  getChatProject,
  getThreadContext,
  listAttachments,
  listChatProjects,
  saveThreadContext,
  updateChatProject,
  type ChatProjectSummary,
  type ThreadContext,
  type AttachmentItem,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { errMsg } from "@/lib/utils";

/** 会话项目卡：固定在当前会话头部的入口，不新增顶层模块。 */
export function ThreadProjectDialog({
  threadId,
  open,
  onClose,
  onSaved,
}: {
  threadId: string;
  open: boolean;
  onClose: () => void;
  onSaved?: (ctx: ThreadContext) => void;
}) {
  const { t: tr } = useI18n();
  const { toast } = useToast();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [instructions, setInstructions] = useState("");
  const [selected, setSelected] = useState<number[]>([]);
  const [memories, setMemories] = useState<string[]>([]);
  const [memoryDraft, setMemoryDraft] = useState("");
  const [files, setFiles] = useState<AttachmentItem[]>([]);
  const [projects, setProjects] = useState<ChatProjectSummary[]>([]);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [projectName, setProjectName] = useState("");
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");

  useEffect(() => {
    if (!open) return;
    let alive = true;
    setLoading(true);
    Promise.all([getThreadContext(threadId), listAttachments(), listChatProjects()])
      .then(([ctx, items, projectList]) => {
        if (!alive) return;
        setInstructions(ctx.instructions || "");
        setSelected((ctx.attachments || []).map((a) => a.id));
        setMemories((ctx.memories || []).map((m) => m.text));
        setFiles(items);
        setProjects(projectList);
        setProjectId(ctx.project_id ?? null);
        setProjectName(ctx.project_name || "");
      })
      .catch((e) => {
        if (alive) toast(errMsg(e), "error");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [open, threadId, toast]);

  const selectedCount = useMemo(() => selected.length, [selected]);

  const chooseProject = async (raw: string) => {
    if (!raw) {
      setProjectId(null);
      setProjectName("");
      return;
    }
    const id = Number(raw);
    try {
      setLoading(true);
      const project = await getChatProject(id);
      setProjectId(project.id);
      setProjectName(project.name);
      setInstructions(project.instructions || "");
      setSelected((project.attachments || []).map((a) => a.id));
      setMemories((project.memories || []).map((m) => m.text));
    } catch (e) {
      toast(errMsg(e), "error");
    } finally {
      setLoading(false);
    }
  };

  const createProject = async () => {
    const name = newProjectName.trim();
    if (!name) {
      toast(tr("project.nameRequired"), "error");
      return;
    }
    try {
      setLoading(true);
      const project = await createChatProject({
        name,
        instructions: instructions.trim(),
        attachment_ids: selected,
        memories,
      });
      setProjects((prev) => [
        {
          id: project.id,
          name: project.name,
          instructions: project.instructions,
          attachment_count: project.attachments.length,
          memory_count: project.memories.length,
          updated_at: project.updated_at,
        },
        ...prev,
      ]);
      setProjectId(project.id);
      setProjectName(project.name);
      setNewProjectOpen(false);
      setNewProjectName("");
      toast(tr("project.created"), "ok");
    } catch (e) {
      toast(errMsg(e), "error");
    } finally {
      setLoading(false);
    }
  };

  const toggleFile = (id: number) => {
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= 10) {
        toast(tr("project.maxFiles"), "error");
        return prev;
      }
      return [...prev, id];
    });
  };

  const addMemory = () => {
    const text = memoryDraft.trim();
    if (!text) return;
    if (memories.length >= 10) {
      toast(tr("project.maxMemories"), "error");
      return;
    }
    if (!memories.includes(text)) setMemories((prev) => [...prev, text]);
    setMemoryDraft("");
  };

  const save = async () => {
    setSaving(true);
    try {
      if (projectId) {
        await updateChatProject(projectId, {
          name: projectName.trim() || tr("project.untitled"),
          instructions: instructions.trim(),
          attachment_ids: selected,
          memories,
        });
      }
      const ctx = await saveThreadContext(threadId, {
        instructions: instructions.trim(),
        attachment_ids: selected,
        memories,
        project_id: projectId,
      });
      onSaved?.(ctx);
      toast(projectId ? tr("project.savedLibrary") : tr("project.saved"), "ok");
      onClose();
    } catch (e) {
      toast(errMsg(e), "error");
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-3 backdrop-blur-[2px]" role="dialog" aria-modal="true">
      <div className="flex max-h-[86vh] w-full max-w-[760px] flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-2xl">
        <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
          <div>
            <h2 className="flex items-center gap-2 text-[15px] font-semibold">
              <Brain className="h-4 w-4 text-primary" />
              {tr("project.title")}
            </h2>
            <p className="mt-0.5 text-[11.5px] text-muted-foreground">{tr("project.desc")}</p>
          </div>
          <button type="button" onClick={onClose} aria-label={tr("project.close")} className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 scroll-thin">
          {loading ? (
            <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> {tr("project.loading")}
            </div>
          ) : (
            <div className="space-y-5">
              <section className="rounded-xl border border-border/80 bg-muted/25 px-3 py-3">
                <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                  <h3 className="flex items-center gap-1.5 text-[13px] font-semibold">
                    <FolderKanban className="h-3.5 w-3.5 text-primary" />
                    {tr("project.library")}
                  </h3>
                  <button
                    type="button"
                    onClick={() => setNewProjectOpen((v) => !v)}
                    className="inline-flex items-center gap-1 rounded-lg border border-border px-2 py-1 text-[11.5px] hover:bg-accent"
                  >
                    <Plus className="h-3 w-3" /> {tr("project.new")}
                  </button>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    value={projectId ?? ""}
                    onChange={(e) => void chooseProject(e.target.value)}
                    className="h-9 min-w-[180px] flex-1 rounded-lg border border-border bg-background px-2 text-[12.5px] outline-none"
                  >
                    <option value="">{tr("project.scopeSession")}</option>
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} · {p.attachment_count}/{p.memory_count}
                      </option>
                    ))}
                  </select>
                  {projectId && (
                    <input
                      value={projectName}
                      onChange={(e) => setProjectName(e.target.value.slice(0, 60))}
                      aria-label={tr("project.name")}
                      className="h-9 min-w-[140px] flex-1 rounded-lg border border-border bg-background px-2.5 text-[12.5px] outline-none"
                    />
                  )}
                </div>
                <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
                  {projectId ? tr("project.linkedHint") : tr("project.libraryHint")}
                </p>
                {newProjectOpen && (
                  <div className="mt-2 flex gap-1.5">
                    <input
                      autoFocus
                      value={newProjectName}
                      onChange={(e) => setNewProjectName(e.target.value.slice(0, 60))}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.nativeEvent.isComposing) void createProject();
                      }}
                      placeholder={tr("project.newNamePh")}
                      className="h-8 min-w-0 flex-1 rounded-lg border border-border bg-background px-2.5 text-[12px] outline-none"
                    />
                    <button type="button" onClick={() => void createProject()} className="h-8 rounded-lg border border-border px-3 text-[12px] hover:bg-accent">
                      {tr("project.create")}
                    </button>
                  </div>
                )}
              </section>

              <section>
                <div className="mb-1.5 flex items-center justify-between">
                  <h3 className="text-[13px] font-semibold">{tr("project.instructions")}</h3>
                  <span className="text-[10.5px] text-muted-foreground">{instructions.length}/2000</span>
                </div>
                <p className="mb-2 text-[11.5px] leading-relaxed text-muted-foreground">{tr("project.instructionsHint")}</p>
                <textarea
                  value={instructions}
                  onChange={(e) => setInstructions(e.target.value.slice(0, 2000))}
                  rows={4}
                  placeholder={tr("project.instructionsPh")}
                  className="w-full resize-y rounded-xl border border-border bg-background px-3 py-2 text-[13px] leading-relaxed outline-none focus:ring-2 focus:ring-ring"
                />
              </section>

              <section>
                <div className="mb-1.5 flex items-center justify-between">
                  <h3 className="text-[13px] font-semibold">{tr("project.files")}</h3>
                  <span className="text-[10.5px] text-muted-foreground">
                    {tr("project.filesCount", { n: selectedCount })}
                  </span>
                </div>
                <p className="mb-2 text-[11.5px] leading-relaxed text-muted-foreground">{tr("project.filesHint")}</p>
                {files.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-border px-3 py-5 text-center text-[12px] text-muted-foreground">
                    {tr("project.noFiles")}
                  </div>
                ) : (
                  <div className="grid gap-1.5 sm:grid-cols-2">
                    {files.map((f) => {
                      const on = selected.includes(f.id);
                      return (
                        <button
                          key={f.id}
                          type="button"
                          onClick={() => toggleFile(f.id)}
                          className={`flex min-w-0 items-center gap-2 rounded-xl border px-2.5 py-2 text-left transition-colors ${
                            on ? "border-primary/40 bg-primary/[0.06]" : "border-border hover:bg-accent"
                          }`}
                        >
                          <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                          <span className="min-w-0 flex-1 truncate text-[12px]">{f.filename}</span>
                          {on ? <Check className="h-3.5 w-3.5 shrink-0 text-primary" /> : <Plus className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />}
                        </button>
                      );
                    })}
                  </div>
                )}
              </section>

              <section>
                <div className="mb-1.5 flex items-center justify-between">
                  <h3 className="text-[13px] font-semibold">{tr("project.memories")}</h3>
                  <span className="text-[10.5px] text-muted-foreground">{memories.length}/10</span>
                </div>
                <p className="mb-2 text-[11.5px] leading-relaxed text-muted-foreground">{tr("project.memoriesHint")}</p>
                <div className="mb-2 flex gap-1.5">
                  <input
                    value={memoryDraft}
                    onChange={(e) => setMemoryDraft(e.target.value.slice(0, 200))}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.nativeEvent.isComposing) {
                        e.preventDefault();
                        addMemory();
                      }
                    }}
                    placeholder={tr("project.memoryPh")}
                    className="h-9 min-w-0 flex-1 rounded-lg border border-border bg-background px-2.5 text-[12.5px] outline-none focus:ring-2 focus:ring-ring"
                  />
                  <button type="button" onClick={addMemory} className="h-9 rounded-lg border border-border px-3 text-[12px] hover:bg-accent">
                    {tr("project.addMemory")}
                  </button>
                </div>
                {memories.length > 0 && (
                  <ul className="space-y-1.5">
                    {memories.map((m) => (
                      <li key={m} className="flex items-start gap-2 rounded-lg bg-muted/40 px-2.5 py-1.5 text-[12px] leading-relaxed">
                        <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-primary" />
                        <span className="min-w-0 flex-1 break-words">{m}</span>
                        <button
                          type="button"
                          onClick={() => setMemories((prev) => prev.filter((x) => x !== m))}
                          aria-label={tr("project.removeMemory")}
                          className="rounded p-0.5 text-muted-foreground hover:text-red-600"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
          <button type="button" onClick={onClose} className="rounded-lg px-3 py-1.5 text-[12.5px] text-muted-foreground hover:bg-accent">
            {tr("project.cancel")}
          </button>
          <button
            type="button"
            onClick={save}
            disabled={loading || saving}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3.5 py-1.5 text-[12.5px] font-medium text-primary-foreground disabled:opacity-40"
          >
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {tr("project.save")}
          </button>
        </div>
      </div>
    </div>
  );
}

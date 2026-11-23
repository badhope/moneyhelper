import { useEffect, useState } from "react";
import { Check, Download, Eye, FolderDown, Loader2, PencilLine, X } from "lucide-react";
import { saveBlob, uploadAttachment } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { errMsg } from "@/lib/utils";
import { MarkdownPreview } from "@/components/workbench/MarkdownPreview";

function safeName(s: string) {
  const base = (s || "canvas").replace(/[\\/:*?"<>|]+/g, "-").trim().slice(0, 80);
  return base || "canvas";
}

/** 回答画布：把一条回答变成可编辑、可预览、可下载、可存入工作台的产物。 */
export function CanvasDialog({
  open,
  title,
  text,
  onClose,
}: {
  open: boolean;
  title: string;
  text: string;
  onClose: () => void;
}) {
  const { t: tr } = useI18n();
  const { toast } = useToast();
  const [tab, setTab] = useState<"edit" | "preview">("edit");
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName(title || tr("canvas.untitled"));
    setBody(text || "");
    setTab("edit");
    setSaved(false);
  }, [open, title, text, tr]);

  const download = () => {
    saveBlob(new Blob([body], { type: "text/markdown;charset=utf-8" }), `${safeName(name)}.md`);
  };

  const saveToWorkbench = async () => {
    setSaving(true);
    try {
      const f = new File([body], `${safeName(name)}.md`, { type: "text/markdown" });
      await uploadAttachment(f);
      setSaved(true);
      toast(tr("canvas.savedWorkbench"), "ok");
    } catch (e) {
      toast(errMsg(e), "error");
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-3 backdrop-blur-[2px]" role="dialog" aria-modal="true">
      <div className="flex h-[88vh] w-full max-w-[980px] flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-2xl">
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
          <PencilLine className="h-4 w-4 shrink-0 text-primary" />
          <input
            value={name}
            onChange={(e) => setName(e.target.value.slice(0, 80))}
            aria-label={tr("canvas.title")}
            className="h-8 min-w-0 flex-1 basis-[240px] rounded-lg border border-transparent bg-transparent px-2 text-[15px] font-semibold outline-none hover:border-border focus:border-border"
          />
          <div className="flex rounded-lg border border-border p-0.5 text-[12px]">
            <button
              type="button"
              onClick={() => setTab("edit")}
              className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 ${tab === "edit" ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}
            >
              <PencilLine className="h-3 w-3" /> {tr("canvas.edit")}
            </button>
            <button
              type="button"
              onClick={() => setTab("preview")}
              className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 ${tab === "preview" ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}
            >
              <Eye className="h-3 w-3" /> {tr("canvas.preview")}
            </button>
          </div>
          <button type="button" onClick={onClose} aria-label={tr("canvas.close")} className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-hidden bg-background">
          {tab === "edit" ? (
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              spellCheck={false}
              className="h-full w-full resize-none bg-background px-5 py-4 font-mono text-[13px] leading-[1.75] outline-none"
            />
          ) : (
            <div className="h-full overflow-y-auto px-5 py-4 scroll-thin">
              <MarkdownPreview text={body} />
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-3">
          <span className="text-[11px] text-muted-foreground">{tr("canvas.hint", { n: body.length })}</span>
          <div className="ml-auto flex items-center gap-2">
            <button type="button" onClick={download} className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-[12.5px] hover:bg-accent">
              <Download className="h-3.5 w-3.5" /> {tr("canvas.download")}
            </button>
            <button
              type="button"
              onClick={saveToWorkbench}
              disabled={saving || saved}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3.5 py-1.5 text-[12.5px] font-medium text-primary-foreground disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : saved ? <Check className="h-3.5 w-3.5" /> : <FolderDown className="h-3.5 w-3.5" />}
              {saved ? tr("canvas.saved") : tr("canvas.saveToWorkbench")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

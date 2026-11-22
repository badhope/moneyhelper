import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, FileText, Loader2, Trash2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm";
import type { AttachmentItem } from "@/lib/api";
import { api, listAttachments, SLOW_REQUEST_TIMEOUT_MS, uploadAttachment } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { cn, errMsg } from "@/lib/utils";
import { Section } from "./shared";

/**
 * 知识库：把文档标记为「入库」，问答时按 BM25 检索相关片段。
 *
 * 与「长期记忆」的分工：记忆是用户主动记住的短句（偏好/家庭），
 * 知识库是上传的长文档（保单、合同、产品说明），必须切片检索。
 */
export function KnowledgeSection() {
  const { t } = useI18n();
  const { toast } = useToast();
  const qc = useQueryClient();
  const [uploading, setUploading] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<AttachmentItem | null>(null);

  const list = useQuery({
    queryKey: ["/api/attachments"],
    // 复用 lib/api 的 listAttachments（原为手写同路径请求）
    queryFn: () => listAttachments(),
  });
  const items = list.data ?? [];
  const indexedCount = items.filter((a) => a.indexed).length;

  const refresh = () => qc.invalidateQueries({ queryKey: ["/api/attachments"] });

  const upload = async (file: File) => {
    setUploading(true);
    try {
      // 复用 lib/api 的上传封装（原为手写 FormData，与 uploadAttachment 完全重复）
      const r = await uploadAttachment(file);
      // 上传即入库：用户来知识库页就是为了让文档可被检索
      if (r?.id)
        await api(
          `/api/attachments/${r.id}/index`,
          { method: "POST", body: JSON.stringify({ indexed: true }) },
          // 建索引要跑切分 + 向量化，20s 不够
          { timeoutMs: SLOW_REQUEST_TIMEOUT_MS },
        );
      await refresh();
      toast(t("knowledge.added", { name: file.name }), "ok");
    } catch (e) {
      toast(errMsg(e), "error");
    } finally {
      setUploading(false);
    }
  };

  const toggle = async (a: AttachmentItem) => {
    try {
      await api(
        `/api/attachments/${a.id}/index`,
        { method: "POST", body: JSON.stringify({ indexed: !a.indexed }) },
        { timeoutMs: SLOW_REQUEST_TIMEOUT_MS }, // 建/删索引同样是慢操作
      );
      toast(t(a.indexed ? "knowledge.unindexedOk" : "knowledge.indexedOk"), "ok");
      await refresh();
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };

  const remove = async (a: AttachmentItem) => {
    try {
      await api(`/api/attachments/${a.id}`, { method: "DELETE" });
      await refresh();
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };

  return (
    <Section
      title={t("settings.navKnowledge")}
      icon={<BookOpen className="w-4 h-4 text-muted-foreground" />}
      desc={t("knowledge.desc")}
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <label
            className={cn(
              "inline-flex h-8 cursor-pointer items-center gap-2 rounded-md border border-border px-3 text-xs font-medium transition-colors hover:bg-accent",
              uploading && "pointer-events-none opacity-60",
            )}
          >
            {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
            {t("knowledge.upload")}
            <input
              type="file"
              className="hidden"
              accept=".txt,.md,.csv,.json,.log"
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) void upload(f);
              }}
            />
          </label>
          <span className="text-[11px] text-muted-foreground">
            {t("knowledge.counter", { n: indexedCount, total: items.length })}
          </span>
        </div>

        {list.isPending ? (
          <p className="py-4 text-center text-xs text-muted-foreground">{t("knowledge.loading")}</p>
        ) : items.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border px-3 py-8 text-center">
            <BookOpen className="mx-auto mb-2 h-5 w-5 text-muted-foreground/50" />
            <p className="text-xs text-muted-foreground">{t("knowledge.empty")}</p>
          </div>
        ) : (
          <ul className="space-y-1.5">
            {items.map((a) => (
              <li
                key={a.id}
                className="flex items-center gap-2 rounded-lg border border-border px-3 py-2"
              >
                <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13px]">{a.filename}</div>
                  <div className="text-[11px] text-muted-foreground">
                    {(a.size / 1024).toFixed(1)} KB
                    {a.indexed ? ` · ${t("knowledge.indexed")}` : ` · ${t("knowledge.notIndexed")}`}
                  </div>
                </div>
                <Button size="sm" variant={a.indexed ? "default" : "outline"} className="h-7 shrink-0 px-2 text-[11px]" onClick={() => void toggle(a)}>
                  {a.indexed ? t("knowledge.removeFromIndex") : t("knowledge.addToIndex")}
                </Button>
                <button
                  type="button"
                  aria-label={t("knowledge.delete", { name: a.filename })}
                  title={t("knowledge.delete", { name: a.filename })}
                  className="shrink-0 rounded p-1.5 text-muted-foreground hover:bg-red-500/10 hover:text-red-600"
                  onClick={() => setPendingDelete(a)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}

        <p className="rounded-lg bg-muted/50 px-3 py-2 text-[11.5px] leading-relaxed text-muted-foreground">
          {t("knowledge.note")}
        </p>
      </div>

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(v) => { if (!v) setPendingDelete(null); }}
        title={t("knowledge.deleteTitle", { name: pendingDelete?.filename ?? "" })}
        description={t("knowledge.deleteDesc")}
        confirmText={t("knowledge.deleteConfirm")}
        danger
        onConfirm={async () => {
          if (pendingDelete) await remove(pendingDelete);
          setPendingDelete(null);
        }}
      />
    </Section>
  );
}

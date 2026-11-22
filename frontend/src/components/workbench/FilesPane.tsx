import { useEffect, useRef, useState } from "react";
import {
  Braces, Download, FileCode2, FileImage, FileSpreadsheet, FileText, Loader2, RefreshCw,
  Search, Trash2, Upload,
} from "lucide-react";
import { searchAttachments } from "@/lib/api";
import type { AttachmentHit, AttachmentItem } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { CHAT_ATTACHMENT_ACCEPT, hasFileDrag, pickAttachmentFiles } from "@/lib/chat-attachments";

function FileIcon({ name }: { name: string }) {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "csv") return <FileSpreadsheet className="h-4 w-4" />;
  if (ext === "json") return <Braces className="h-4 w-4" />;
  if (ext === "html" || ext === "htm") return <FileCode2 className="h-4 w-4" />;
  if (["png", "jpg", "jpeg", "webp", "gif"].includes(ext)) return <FileImage className="h-4 w-4" />;
  return <FileText className="h-4 w-4" />;
}

function MatchSnippet({ text, q }: { text: string; q: string }) {
  const idx = text.toLowerCase().indexOf(q.toLowerCase());
  if (idx < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="rounded bg-primary/15 px-0.5 text-foreground">
        {text.slice(idx, idx + q.length)}
      </mark>
      {text.slice(idx + q.length)}
    </>
  );
}

function sizeLabel(n: number) {
  if (!Number.isFinite(n) || n <= 0) return "0 B";
  if (n < 1024) return `${n} B`;
  return `${(n / 1024).toFixed(1)} KB`;
}

/** 文件栏：只列对话里上传过的文档，点一行进预览。
 *  不做「全盘文件系统」——浏览器拿不到本机目录，伪装成文件管理器只会误导。 */
export function FilesPane({
  items,
  pending,
  error,
  selectedId,
  uploading,
  onRetry,
  onOpen,
  onUpload,
  onDownload,
  onDeleteRequest,
}: {
  items: AttachmentItem[];
  pending: boolean;
  error: unknown;
  selectedId: number | null;
  uploading: boolean;
  onRetry: () => void;
  onOpen: (item: AttachmentItem) => void;
  onUpload: (files: File[]) => void;
  onDownload: (item: AttachmentItem) => void;
  onDeleteRequest: (item: AttachmentItem) => void;
}) {
  const { t } = useI18n();
  const { toast } = useToast();
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<AttachmentHit[]>([]);
  const [searchPending, setSearchPending] = useState(false);
  const [searchFailed, setSearchFailed] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const queryTrim = query.trim();
  const localShown = items.filter((a) =>
    !queryTrim ? true : a.filename.toLowerCase().includes(queryTrim.toLowerCase()),
  );

  // 文件名即时过滤；停手 300ms 再查正文，命中片段随结果返回。
  useEffect(() => {
    if (!queryTrim) {
      setHits([]);
      setSearchPending(false);
      setSearchFailed(false);
      return;
    }
    let alive = true;
    setHits([]);
    setSearchPending(true);
    setSearchFailed(false);
    const timer = window.setTimeout(() => {
      void searchAttachments(queryTrim, 30)
        .then((rows) => {
          if (alive) setHits(rows);
        })
        .catch(() => {
          if (!alive) return;
          setHits([]);
          setSearchFailed(true);
        })
        .finally(() => {
          if (alive) setSearchPending(false);
        });
    }, 300);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
    // 删除/刷新文件后重新搜一次，避免命中列表停在已删记录上
  }, [queryTrim, items]);

  const serverReady = !searchPending && !searchFailed;
  const shown: (AttachmentItem & Partial<Pick<AttachmentHit, "snippet" | "match">>)[] =
    !queryTrim ? items : serverReady ? hits : localShown;

  const addFiles = (files: File[]) => {
    const { accepted, rejected } = pickAttachmentFiles(files);
    if (rejected.length) {
      toast(`${t("workbench.unsupported")}：${rejected.slice(0, 3).join("、")}`, "error");
    }
    if (accepted.length) onUpload(accepted);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 space-y-2 border-b border-border/60 px-3 py-2.5">
        <div className="flex items-center gap-1.5">
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("workbench.search")}
              aria-label={t("workbench.search")}
              className="h-8 w-full rounded-md border border-border bg-background pl-7 pr-2 text-xs outline-none transition-colors placeholder:text-muted-foreground/70 focus:border-primary/50"
            />
          </div>
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            aria-label={t("workbench.upload")}
            title={t("workbench.upload")}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-50"
          >
            {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
          </button>
          <button
            type="button"
            onClick={onRetry}
            aria-label={t("workbench.refresh")}
            title={t("workbench.refresh")}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", pending && "animate-spin")} />
          </button>
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            accept={CHAT_ATTACHMENT_ACCEPT}
            multiple
            onChange={(e) => {
              const picked = Array.from(e.target.files ?? []);
              e.target.value = "";
              if (picked.length) addFiles(picked);
            }}
          />
        </div>
        <div className="flex items-center justify-between text-[11px] text-muted-foreground">
          <span>{t("workbench.fileCount", { n: items.length })}</span>
          {queryTrim && (
            <span className="inline-flex items-center gap-1">
              {searchPending && <Loader2 className="h-3 w-3 animate-spin" />}
              {t("workbench.matchCount", { n: shown.length })}
            </span>
          )}
        </div>
      </div>

      <div
        className="relative min-h-0 flex-1 overflow-y-auto scroll-thin p-2"
        onDragEnter={(e) => {
          if (!hasFileDrag(e.dataTransfer.types)) return;
          e.preventDefault();
          setDragging(true);
        }}
        onDragOver={(e) => {
          if (!hasFileDrag(e.dataTransfer.types)) return;
          e.preventDefault();
          e.dataTransfer.dropEffect = "copy";
          if (!dragging) setDragging(true);
        }}
        onDragLeave={(e) => {
          const next = e.relatedTarget as Node | null;
          if (next && e.currentTarget.contains(next)) return;
          setDragging(false);
        }}
        onDrop={(e) => {
          if (!hasFileDrag(e.dataTransfer.types)) return;
          e.preventDefault();
          setDragging(false);
          addFiles(Array.from(e.dataTransfer.files ?? []));
        }}
      >
        {dragging && (
          <div className="pointer-events-none absolute inset-2 z-10 flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-primary/45 bg-card/95 text-center">
            <Upload className="mb-1.5 h-5 w-5 text-primary" />
            <span className="text-[13px] font-medium">{t("workbench.dropTitle")}</span>
            <span className="mt-0.5 text-[11px] text-muted-foreground">{t("workbench.dropHint")}</span>
          </div>
        )}
        {pending ? (
          <div className="flex items-center justify-center gap-2 py-10 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {t("workbench.loading")}
          </div>
        ) : error ? (
          <div className="px-3 py-10 text-center">
            <p className="text-xs text-red-600 dark:text-red-400">{t("workbench.filesError")}</p>
            <button
              type="button"
              onClick={onRetry}
              className="mt-2 rounded-md border border-border px-2.5 py-1 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              {t("workbench.retry")}
            </button>
          </div>
        ) : items.length === 0 ? (
          <div className="px-4 py-12 text-center">
            <FileText className="mx-auto mb-2 h-6 w-6 text-muted-foreground/40" />
            <p className="text-xs text-muted-foreground">{t("workbench.filesEmpty")}</p>
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="mt-3 inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-[11px] text-foreground/80 hover:bg-accent"
            >
              <Upload className="h-3 w-3" /> {t("workbench.upload")}
            </button>
            <p className="mt-2 text-[11px] text-muted-foreground/80">{t("workbench.filesEmptyHint")}</p>
          </div>
        ) : queryTrim && searchPending && shown.length === 0 ? (
          <div className="flex items-center justify-center gap-2 px-4 py-10 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {t("workbench.searching")}
          </div>
        ) : queryTrim && searchFailed && shown.length === 0 ? (
          <p className="px-4 py-10 text-center text-xs text-muted-foreground">{t("workbench.searchFailed")}</p>
        ) : shown.length === 0 ? (
          <p className="px-4 py-10 text-center text-xs text-muted-foreground">{t("workbench.noMatch")}</p>
        ) : (
          <ul className="space-y-1">
            {shown.map((a) => (
              <li key={a.id}>
                <div
                  className={cn(
                    "group flex items-center rounded-lg transition-colors hover:bg-accent/70",
                    selectedId === a.id && "bg-primary/[0.07] ring-1 ring-primary/20",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => onOpen(a)}
                    aria-current={selectedId === a.id ? "true" : undefined}
                    className="flex min-w-0 flex-1 items-start gap-2 rounded-lg px-2.5 py-2 text-left"
                  >
                    <span className="mt-0.5 shrink-0 text-muted-foreground">
                      <FileIcon name={a.filename} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] text-foreground/90">{a.filename}</span>
                      <span className="mt-0.5 block truncate text-[10.5px] text-muted-foreground">
                        {sizeLabel(a.size)} · {fmtDate(a.created_at)}
                      </span>
                      {a.match === "content" && a.snippet ? (
                        <span className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">
                          <MatchSnippet text={a.snippet} q={queryTrim} />
                        </span>
                      ) : null}
                    </span>
                    {a.indexed ? (
                      <span className="mt-0.5 shrink-0 rounded bg-primary/10 px-1 py-0.5 text-[10px] text-primary">
                        {t("workbench.indexed")}
                      </span>
                    ) : null}
                  </button>
                  <div className="mr-1 flex shrink-0 items-center gap-0.5 opacity-100 transition-opacity [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100 [@media(hover:hover)]:group-focus-within:opacity-100">
                    <button
                      type="button"
                      onClick={() => onDownload(a)}
                      aria-label={t("workbench.download")}
                      title={t("workbench.download")}
                      className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-background hover:text-foreground"
                    >
                      <Download className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => onDeleteRequest(a)}
                      aria-label={t("workbench.delete")}
                      title={t("workbench.delete")}
                      className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/40"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

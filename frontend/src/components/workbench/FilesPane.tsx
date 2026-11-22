import { useRef, useState } from "react";
import {
  Braces, FileCode2, FileSpreadsheet, FileText, Loader2, RefreshCw, Search, Upload,
} from "lucide-react";
import type { AttachmentItem } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

function FileIcon({ name }: { name: string }) {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "csv") return <FileSpreadsheet className="h-4 w-4" />;
  if (ext === "json") return <Braces className="h-4 w-4" />;
  if (ext === "html" || ext === "htm") return <FileCode2 className="h-4 w-4" />;
  return <FileText className="h-4 w-4" />;
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
}: {
  items: AttachmentItem[];
  pending: boolean;
  error: unknown;
  selectedId: number | null;
  uploading: boolean;
  onRetry: () => void;
  onOpen: (item: AttachmentItem) => void;
  onUpload: (file: File) => void;
}) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const shown = items.filter((a) =>
    !query.trim() ? true : a.filename.toLowerCase().includes(query.trim().toLowerCase()),
  );

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
            accept=".txt,.md,.csv,.json,.log,.html,.htm"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) onUpload(f);
            }}
          />
        </div>
        <div className="flex items-center justify-between text-[11px] text-muted-foreground">
          <span>{t("workbench.fileCount", { n: items.length })}</span>
          {query.trim() && <span>{t("workbench.matchCount", { n: shown.length })}</span>}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto scroll-thin p-2">
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
        ) : shown.length === 0 ? (
          <p className="px-4 py-10 text-center text-xs text-muted-foreground">{t("workbench.noMatch")}</p>
        ) : (
          <ul className="space-y-1">
            {shown.map((a) => (
              <li key={a.id}>
                <button
                  type="button"
                  onClick={() => onOpen(a)}
                  aria-current={selectedId === a.id ? "true" : undefined}
                  className={cn(
                    "flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-accent/70",
                    selectedId === a.id && "bg-primary/[0.07] ring-1 ring-primary/20",
                  )}
                >
                  <span className="mt-0.5 shrink-0 text-muted-foreground">
                    <FileIcon name={a.filename} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] text-foreground/90">{a.filename}</span>
                    <span className="mt-0.5 block truncate text-[10.5px] text-muted-foreground">
                      {sizeLabel(a.size)} · {fmtDate(a.created_at)}
                    </span>
                  </span>
                  {a.indexed ? (
                    <span className="mt-0.5 shrink-0 rounded bg-primary/10 px-1 py-0.5 text-[10px] text-primary">
                      {t("workbench.indexed")}
                    </span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

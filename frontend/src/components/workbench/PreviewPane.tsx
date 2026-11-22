import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, Copy, Download, FileText, Loader2 } from "lucide-react";
import { apiBlob, getAttachment, saveBlob, type AttachmentItem } from "@/lib/api";
import { copyText } from "@/lib/clipboard";
import { fmtDate } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { cn } from "@/lib/utils";

const MarkdownPreview = lazy(() =>
  import("@/components/workbench/MarkdownPreview").then((m) => ({ default: m.MarkdownPreview })),
);

function extOf(name: string) {
  return name.split(".").pop()?.toLowerCase() ?? "";
}

/** 轻量 CSV 解析：支持引号里的逗号与换行；只取前 40 行做预览。 */
function parseCsv(text: string, maxRows = 40): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    if (quoted) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i += 1;
        } else quoted = false;
      } else cell += c;
      continue;
    }
    if (c === '"') quoted = true;
    else if (c === ",") {
      row.push(cell);
      cell = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i += 1;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
      if (rows.length >= maxRows) break;
    } else cell += c;
  }
  if (cell !== "" || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

function CsvTable({ text }: { text: string }) {
  const { t } = useI18n();
  const rows = parseCsv(text);
  if (rows.length === 0) return <p className="text-xs text-muted-foreground">{t("workbench.previewEmpty")}</p>;
  const [head, ...body] = rows;
  return (
    <div className="min-w-0">
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full border-collapse text-[11.5px]">
          <thead className="bg-muted/50">
            <tr>
              {head.map((h, i) => (
                <th key={i} className="whitespace-nowrap border-b border-border px-2 py-1.5 text-left font-medium">
                  {h || "—"}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((r, i) => (
              <tr key={i} className="odd:bg-background even:bg-muted/20">
                {head.map((_, j) => (
                  <td key={j} className="max-w-[12rem] truncate border-b border-border/60 px-2 py-1.5">
                    {r[j] ?? ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">{t("workbench.csvRows", { n: body.length })} · {t("workbench.csvScroll")}</p>
    </div>
  );
}

export function PreviewPane({
  selected,
  onOpenFiles,
}: {
  selected: AttachmentItem | null;
  onOpenFiles: () => void;
}) {
  const { t } = useI18n();
  const { toast } = useToast();
  const [copied, setCopied] = useState(false);

  const detail = useQuery({
    queryKey: ["/api/attachments", selected?.id],
    queryFn: () => getAttachment(selected!.id),
    enabled: Boolean(selected),
    staleTime: 60_000,
  });

  const isImage = selected?.kind === "image" || (selected?.mime ?? "").startsWith("image/");
  const isPdf = selected?.kind === "pdf" || selected?.mime === "application/pdf";
  const binary = isImage || isPdf;
  const rawQ = useQuery({
    queryKey: ["/api/attachments", selected?.id, "raw"],
    queryFn: () => apiBlob(`/api/attachments/${selected!.id}/raw`),
    enabled: Boolean(selected && binary),
    staleTime: 30_000,
    retry: false,
  });
  const rawUrl = useMemo(
    () => (rawQ.data ? URL.createObjectURL(rawQ.data) : ""),
    [rawQ.data],
  );
  useEffect(() => () => {
    if (rawUrl) URL.revokeObjectURL(rawUrl);
  }, [rawUrl]);

  if (!selected) {
    return (
      <div className="flex h-full flex-col items-center justify-center px-6 text-center">
        <FileText className="mb-3 h-7 w-7 text-muted-foreground/40" />
        <p className="text-sm font-medium text-foreground/80">{t("workbench.previewNoFile")}</p>
        <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{t("workbench.previewNoFileHint")}</p>
        <button
          type="button"
          onClick={onOpenFiles}
          className="mt-4 rounded-md border border-border px-3 py-1.5 text-xs text-foreground/80 transition-colors hover:bg-accent"
        >
          {t("workbench.goFiles")}
        </button>
      </div>
    );
  }

  const content = detail.data?.content ?? "";
  const ext = extOf(selected.filename);

  const copy = () => {
    if (copyText(content)) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
      toast(t("workbench.copied"), "ok");
    } else toast(t("workbench.copyFailed"), "error");
  };
  const download = () => {
    if (binary) {
      if (rawQ.data) saveBlob(rawQ.data, selected.filename);
      else toast(t("workbench.readFailed"), "error");
      return;
    }
    saveBlob(new Blob([content], { type: "text/plain;charset=utf-8" }), selected.filename);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 border-b border-border/60 px-3 py-2">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="truncate text-[13px] font-medium" title={selected.filename}>
              {selected.filename}
            </div>
            <div className="mt-0.5 text-[10.5px] text-muted-foreground">
              {(selected.size / 1024).toFixed(1)} KB · {fmtDate(selected.created_at)}
              {selected.indexed ? ` · ${t("workbench.indexed")}` : ""}
            </div>
          </div>
          <button
            type="button"
            onClick={copy}
            disabled={!content || binary}
            aria-label={t("workbench.copy")}
            title={t("workbench.copy")}
            className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-40"
          >
            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          </button>
          <button
            type="button"
            onClick={download}
            disabled={binary ? !rawQ.data : !content}
            aria-label={t("workbench.download")}
            title={t("workbench.download")}
            className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-40"
          >
            <Download className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto scroll-thin p-3">
        {detail.isPending ? (
          <div className="flex items-center justify-center gap-2 py-12 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> {t("workbench.reading")}
          </div>
        ) : detail.isError ? (
          <div className="py-12 text-center">
            <p className="text-xs text-red-600 dark:text-red-400">{t("workbench.readFailed")}</p>
            <button
              type="button"
              onClick={() => void detail.refetch()}
              className="mt-2 rounded-md border border-border px-2.5 py-1 text-[11px] text-muted-foreground hover:bg-accent"
            >
              {t("workbench.retry")}
            </button>
          </div>
        ) : binary ? (
          rawQ.isPending ? (
            <div className="flex items-center justify-center gap-2 py-12 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> {t("workbench.reading")}
            </div>
          ) : rawQ.isError || !rawUrl ? (
            <div className="py-12 text-center">
              <p className="text-xs text-red-600 dark:text-red-400">{t("workbench.readFailed")}</p>
              <button
                type="button"
                onClick={() => void rawQ.refetch()}
                className="mt-2 rounded-md border border-border px-2.5 py-1 text-[11px] text-muted-foreground hover:bg-accent"
              >
                {t("workbench.retry")}
              </button>
            </div>
          ) : isImage ? (
            <div className="flex min-h-[18rem] items-center justify-center overflow-auto rounded-lg border border-border bg-muted/20 p-2">
              <img
                src={rawUrl}
                alt={selected.filename}
                className="max-h-[68vh] max-w-full rounded object-contain"
              />
            </div>
          ) : isPdf ? (
            <iframe
              title={selected.filename}
              src={rawUrl}
              className="h-[68vh] w-full rounded-lg border border-border bg-white"
            />
          ) : (
            <p className="py-10 text-center text-xs text-muted-foreground">{t("workbench.previewEmpty")}</p>
          )
        ) : !content.trim() ? (
          <p className="py-10 text-center text-xs text-muted-foreground">{t("workbench.previewEmpty")}</p>
        ) : ext === "md" || ext === "markdown" ? (
          <Suspense fallback={<div className="py-8 text-center text-xs text-muted-foreground">{t("workbench.reading")}</div>}>
            <MarkdownPreview text={content} />
          </Suspense>
        ) : ext === "csv" ? (
          <CsvTable text={content} />
        ) : ext === "json" ? (
          <pre className="whitespace-pre-wrap break-words font-mono text-[11.5px] leading-relaxed text-foreground/85">
            {(() => {
              try {
                return JSON.stringify(JSON.parse(content), null, 2);
              } catch {
                return content;
              }
            })()}
          </pre>
        ) : ext === "html" || ext === "htm" ? (
          <div className="flex h-full min-h-[18rem] flex-col">
            <p className="mb-2 text-[11px] text-muted-foreground">{t("workbench.htmlNoScript")}</p>
            <iframe
              title={selected.filename}
              srcDoc={content}
              sandbox=""
              className="min-h-[20rem] w-full flex-1 rounded-lg border border-border bg-white"
            />
          </div>
        ) : (
          <pre className="whitespace-pre-wrap break-words text-[12px] leading-relaxed text-foreground/85">
            {content}
          </pre>
        )}

        {!binary && detail.data && content.length >= 6000 && (
          <p className={cn("mt-3 rounded-md bg-amber-500/10 px-2 py-1.5 text-[10.5px] text-amber-700 dark:text-amber-400")}>
            {t("workbench.truncated")}
          </p>
        )}
      </div>
    </div>
  );
}

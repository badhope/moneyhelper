/** 连接中心深化面板 · 单据：发票（文本/图片识别）、持仓导入、PDF 账单。 */

/** 连接中心深化面板（v4.5）：市场温度 / 个股档案 / 预交易检查 / 风控参数 / 条件单 / 发票 / 券商对账。
 *
 * 拆成独立文件：ConnectPage 已 900+ 行，继续内联会让单文件失控；这些面板都只依赖
 * use-connect 的 hooks，彼此独立，按需渲染。
 */

import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Banknote, Loader2, Receipt, Trash2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

import { EmptyState } from "@/components/ui/empty-state";

import { useI18n } from "@/lib/i18n";
import { Table } from "@/components/ui/table";
import { useToast } from "@/lib/toast";
import { fmtMoney, pnlClass } from "@/lib/format";
import { cn, errMsg } from "@/lib/utils";
import { useImportHoldings, useInvoices, useDeleteInvoice, useUploadInvoiceText, useVisionStatus, useUploadInvoiceImage, useUploadStatementPdf } from "@/lib/use-connect";


/** 发票归档 */
export function InvoiceCard() {
  const { t } = useI18n();
  const { toast } = useToast();
  const qc = useQueryClient();
  const q = useInvoices();
  const upload = useUploadInvoiceText();
  const del = useDeleteInvoice();
  const [text, setText] = useState("");
  const submit = async () => {
    if (!text.trim()) {
      toast(t("connect.invoiceEmpty"), "error");
      return;
    }
    try {
      const res = await upload.mutateAsync({ text });
      toast(res.duplicate ? t("connect.invoiceDuplicate") : t("connect.invoiceSaved"), "ok");
      setText("");
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };
  const summary = q.data?.summary;
  return (
    <Card className="min-w-0 p-[var(--card-pad)]">
      <div className="flex items-center gap-1.5 text-[13px] font-semibold">
        <Receipt className="h-4 w-4 text-primary" />
        {t("connect.invoiceTitle")}
      </div>
      <p className="mt-1 text-[10.5px] leading-relaxed text-muted-foreground">{t("connect.invoiceHint")}</p>
      {summary ? (
        <div className="mt-2 grid grid-cols-3 gap-2">
          {[
            { label: t("connect.invoiceCount"), value: String(summary.count) },
            { label: t("connect.invoiceTotal"), value: fmtMoney(summary.total_amount, false, true) },
            { label: t("connect.invoiceTax"), value: fmtMoney(summary.total_tax, false, true) },
          ].map((x) => (
            <div key={x.label} className="rounded-lg bg-muted/25 px-2 py-1.5">
              <div className="text-[10.5px] text-muted-foreground">{x.label}</div>
              <div className="text-[13px] font-semibold tabular-nums">{x.value}</div>
            </div>
          ))}
        </div>
      ) : null}
      <ImageInvoiceInput onParsed={() => void qc.invalidateQueries({ queryKey: ["/api/connect/invoices"] })} />
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={t("connect.invoicePh")}
        className="mt-2 min-h-24 w-full rounded-md border border-border bg-background px-2 py-1.5 font-mono text-[11.5px]"
      />
      <Button size="sm" className="mt-1.5 w-full" disabled={upload.isPending} onClick={() => void submit()}>
        {upload.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
        {t("connect.invoiceParse")}
      </Button>
      <div className="mt-2 border-t border-border/60 pt-2">
        {(q.data?.items ?? []).length === 0 ? (
          <EmptyState mode="compact" text={t("connect.invoiceNone")} />
        ) : (
          (q.data?.items ?? []).slice(0, 8).map((inv) => (
            <div
              key={inv.id}
              className="flex flex-wrap items-center gap-1.5 border-b border-border/40 py-1.5 text-[11px] last:border-0"
            >
              <Badge
                variant={inv.confidence === "high" ? "ok" : inv.confidence === "medium" ? "warn" : "muted"}
                className="px-1.5 py-0 text-[10px]"
              >
                {inv.confidence}
              </Badge>
              <span className="font-medium">{inv.seller || inv.file_name}</span>
              <span className="text-muted-foreground">{inv.invoice_date}</span>
              <span className="tabular-nums">{inv.total_amount != null ? fmtMoney(inv.total_amount) : "-"}</span>
              <span className="text-muted-foreground">{inv.invoice_number}</span>
              <button
                type="button"
                onClick={() => void del.mutateAsync(inv.id)}
                className="ml-auto rounded p-1 text-muted-foreground hover:text-down"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))
        )}
      </div>
    </Card>
  );
}

/** 券商持仓对账导入 */
export function HoldingsImportCard() {
  const { t } = useI18n();
  const { toast } = useToast();
  const importer = useImportHoldings();
  const [content, setContent] = useState("");
  const [result, setResult] = useState<Awaited<ReturnType<typeof importer.mutateAsync>> | null>(null);
  const run = async (apply: boolean) => {
    if (!content.trim()) {
      toast(t("connect.holdingsEmpty"), "error");
      return;
    }
    try {
      const res = await importer.mutateAsync({ content, apply });
      setResult(res);
      toast(
        apply
          ? t("connect.holdingsApplied", { n: res.applied ?? 0 })
          : t("connect.holdingsPreview", { n: res.count }),
        "ok",
      );
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };
  return (
    <Card className="min-w-0 p-[var(--card-pad)]">
      <div className="flex items-center gap-1.5 text-[13px] font-semibold">
        <Banknote className="h-4 w-4 text-primary" />
        {t("connect.holdingsTitle")}
      </div>
      <p className="mt-1 text-[10.5px] leading-relaxed text-muted-foreground">{t("connect.holdingsHint")}</p>
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder={t("connect.holdingsPh")}
        className="mt-2 min-h-32 w-full rounded-md border border-border bg-background px-2 py-1.5 font-mono text-[11px]"
      />
      <div className="mt-1.5 flex gap-2">
        <Button size="sm" variant="outline" disabled={importer.isPending} onClick={() => void run(false)}>
          {t("connect.previewOnly")}
        </Button>
        <Button size="sm" disabled={importer.isPending} onClick={() => void run(true)}>
          {importer.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
          {t("connect.applyImport")}
        </Button>
      </div>
      {result && (
        <div className="mt-2 border-t border-border/60 pt-2">
          <div className="text-[11px] text-muted-foreground">
            {t("connect.holdingsResult", { n: result.count, account: result.account || "-" })}
            {result.skipped ? ` · ${t("connect.holdingsSkipped", { n: result.skipped })}` : ""}
          </div>
          <div className="mt-1 overflow-x-auto scroll-thin">
            <Table size="2xs">
              <thead>
                <tr className="text-left text-[10.5px] text-muted-foreground">
                  <th className="py-1 pr-2 font-normal">{t("connect.colName")}</th>
                  <th className="py-1 pr-2 text-right font-normal">{t("connect.holdShares")}</th>
                  <th className="py-1 pr-2 text-right font-normal">{t("connect.holdCost")}</th>
                  <th className="py-1 text-right font-normal">{t("connect.colPrice")}</th>
                </tr>
              </thead>
              <tbody>
                {result.positions.slice(0, 10).map((p) => (
                  <tr key={p.symbol} className="border-t border-border/40">
                    <td className="py-1 pr-2">
                      <span className="font-medium">{p.name}</span>{" "}
                      <span className="text-muted-foreground">{p.symbol}</span>
                    </td>
                    <td className="py-1 pr-2 text-right tabular-nums">{p.shares}</td>
                    <td className="py-1 pr-2 text-right tabular-nums">{p.cost}</td>
                    <td className="py-1 text-right tabular-nums">{p.last}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
          {result.warnings.length > 0 && (
            <div className="mt-1 space-y-0.5">
              {result.warnings.slice(0, 4).map((w) => (
                <div key={w} className="text-[10px] text-amber-600 dark:text-amber-400">
                  {w}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}


/** 发票图片上传（v4.6）：二维码优先，OCR 兜底；能力缺失时给安装提示 */
function ImageInvoiceInput({ onParsed }: { onParsed: () => void }) {
  const { t } = useI18n();
  const { toast } = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const vision = useVisionStatus();
  const upload = useUploadInvoiceImage();
  const [hint, setHint] = useState("");

  const pick = async (file: File) => {
    try {
      const res = await upload.mutateAsync(file);
      if (!res.ok) {
        setHint(res.install_hint || t("connect.imageFail"));
        toast(res.install_hint || t("connect.imageFail"), "info");
        return;
      }
      setHint("");
      toast(
        `${t("connect.imageOk")} · ${res.method}${res.duplicate ? ` · ${t("connect.invoiceDuplicate")}` : ""}`,
        "ok",
      );
      onParsed();
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };

  const cap = vision.data;
  return (
    <div className="mt-2 rounded-lg border border-dashed border-border/70 px-2 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={upload.isPending}
          onClick={() => inputRef.current?.click()}
          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11.5px] hover:bg-accent disabled:opacity-50"
        >
          {upload.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Receipt className="h-3.5 w-3.5" />}
          {t("connect.uploadImage")}
        </button>
        <span className="text-[10.5px] text-muted-foreground">
          {t("connect.visionQr")}: {cap?.qr.available ? cap.qr.decoders.join("/") : t("connect.notInstalled")}
          {" · "}
          {t("connect.visionOcr")}: {cap?.ocr.available ? cap.ocr.engines.join("/") : t("connect.notInstalled")}
        </span>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void pick(f);
          e.target.value = "";
        }}
      />
      {hint ? <div className="mt-1 text-[10.5px] text-amber-600 dark:text-amber-400">{hint}</div> : null}
    </div>
  );
}

/** PDF 对账单导入（v4.6） */
export function PdfStatementCard() {
  const { t } = useI18n();
  const { toast } = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const upload = useUploadStatementPdf();
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof upload.mutateAsync>> | null>(null);
  const [file, setFile] = useState<File | null>(null);

  const pick = (f: File) => {
    setFile(f);
    void upload
      .mutateAsync({ file: f, apply: false })
      .then(setPreview)
      .catch((e) => toast(errMsg(e), "error"));
  };

  const apply = async () => {
    if (!file) return;
    try {
      const res = await upload.mutateAsync({ file, apply: true });
      setPreview(res);
      toast(t("connect.pdfImported", { n: res.imported ?? 0, d: res.duplicated ?? 0 }), "ok");
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };

  return (
    <Card className="min-w-0 p-[var(--card-pad)]">
      <div className="flex items-center gap-1.5 text-[13px] font-semibold">
        <Banknote className="h-4 w-4 text-primary" />
        {t("connect.pdfTitle")}
      </div>
      <p className="mt-1 text-[10.5px] leading-relaxed text-muted-foreground">{t("connect.pdfHint")}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={upload.isPending}
          onClick={() => inputRef.current?.click()}
          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11.5px] hover:bg-accent disabled:opacity-50"
        >
          {upload.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          {t("connect.choosePdf")}
        </button>
        {preview && preview.ok && preview.count > 0 ? (
          <Button size="sm" onClick={() => void apply()} disabled={upload.isPending}>
            {t("connect.applyImport")}
          </Button>
        ) : null}
        {file ? <span className="text-[10.5px] text-muted-foreground">{file.name}</span> : null}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) pick(f);
          e.target.value = "";
        }}
      />
      {preview ? (
        <div className="mt-2 border-t border-border/60 pt-2">
          <div className="text-[11px] text-muted-foreground">
            {t("connect.pdfResult", { n: preview.count, m: preview.method || "-" })}
          </div>
          {preview.warnings.length ? (
            <div className="mt-1 space-y-0.5">
              {preview.warnings.slice(0, 3).map((w) => (
                <div key={w} className="text-[10px] text-amber-600 dark:text-amber-400">
                  {w}
                </div>
              ))}
            </div>
          ) : null}
          {preview.rows.length ? (
            <div className="mt-1 max-h-40 overflow-y-auto scroll-thin">
              <Table size="2xs">
                <tbody>
                  {preview.rows.slice(0, 20).map((r, i) => (
                    <tr key={`${r.date}-${i}`} className="border-t border-border/40">
                      <td className="py-1 pr-2 tabular-nums">{r.date}</td>
                      <td className="py-1 pr-2">{r.item}</td>
                      <td className={cn("py-1 text-right tabular-nums", pnlClass(r.amount))}>
                        {fmtMoney(r.amount, true)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}

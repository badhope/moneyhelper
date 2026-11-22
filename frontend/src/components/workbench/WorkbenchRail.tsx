import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Eye, Files, Globe2, X } from "lucide-react";
import {
  apiBlob,
  deleteAttachment,
  getAttachment,
  listAttachments,
  saveBlob,
  setAttachmentIndexed,
  uploadAttachment,
  type AttachmentItem,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useMediaQuery } from "@/lib/use-media-query";
import { useResizableWidth } from "@/lib/use-resizable-width";
import { useToast } from "@/lib/toast";
import { cn, errMsg } from "@/lib/utils";
import { ConfirmDialog } from "@/components/ui/confirm";
import { FilesPane } from "@/components/workbench/FilesPane";
import { PreviewPane } from "@/components/workbench/PreviewPane";
import { BrowserPane } from "@/components/workbench/BrowserPane";

export type WorkbenchTab = "files" | "preview" | "browser";

/** 对话右侧的工作台：文件 / 预览 / 浏览器。
 *
 * 三件事共用一条竖栏，而不是三个悬浮按钮：
 * - 文件：对话里上传的 txt/md/csv/json，随时回看，不必重新翻消息；
 * - 预览：选中文件后按类型渲染（Markdown/CSV 表格/JSON/HTML 沙箱）；
 * - 浏览器：回答里的外链直接在这里打开，不离开当前对话。
 */
export function WorkbenchRail({
  open,
  onClose,
  externalUrl,
  attachmentRequest,
}: {
  open: boolean;
  onClose: () => void;
  /** 回答内链接触发：{url,id}，id 变化即重新导航。 */
  externalUrl: { url: string; id: number } | null;
  /** 聊天附件胶囊触发：requestId 变化即切到该附件预览。 */
  attachmentRequest: { attachmentId: number; requestId: number } | null;
}) {
  const { t } = useI18n();
  const { toast } = useToast();
  const qc = useQueryClient();
  const isWide = useMediaQuery("(min-width: 1024px)", false);
  const [tab, setTab] = useState<WorkbenchTab>("files");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [indexingId, setIndexingId] = useState<number | null>(null);
  const [pendingDelete, setPendingDelete] = useState<AttachmentItem | null>(null);

  const nav = useResizableWidth({
    storageKey: "wo.workbenchWidth",
    defaultWidth: 360,
    min: 300,
    max: 560,
    direction: "right",
  });

  const list = useQuery({
    queryKey: ["/api/attachments"],
    queryFn: () => listAttachments(),
    staleTime: 30_000,
  });
  const items = list.data ?? [];
  const selected = items.find((a) => a.id === selectedId) ?? null;

  // 第一次打开时自动选中最新文件，预览页不至于是空的；文件被删后跟随列表回落。
  useEffect(() => {
    if (items.length === 0) {
      if (selectedId !== null) setSelectedId(null);
      return;
    }
    // 刚点击附件但列表还在刷新：先等目标出现，别立刻回落到第一条。
    if (attachmentRequest?.attachmentId === selectedId && !items.some((a) => a.id === selectedId)) return;
    if (!items.some((a) => a.id === selectedId)) setSelectedId(items[0].id);
  }, [items, selectedId, attachmentRequest?.attachmentId]);

  useEffect(() => {
    if (!externalUrl?.id) return;
    setTab("browser");
  }, [externalUrl?.id]);

  useEffect(() => {
    if (!attachmentRequest?.requestId) return;
    setSelectedId(attachmentRequest.attachmentId);
    setTab("preview");
    // 胶囊可能刚上传完成，列表还停在旧缓存；按 id 先选，再拉最新列表。
    void qc.invalidateQueries({ queryKey: ["/api/attachments"] });
  }, [attachmentRequest?.requestId, attachmentRequest?.attachmentId, qc]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // 手机/平板是覆盖层：锁背景滚动，避免右栏里滑到一半露出下面的对话。
  useEffect(() => {
    if (!open || isWide) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open, isWide]);

  const upload = async (files: File[]) => {
    if (!files.length) return;
    setUploading(true);
    try {
      const results = await Promise.allSettled(
        files.map(async (file) => ({ file, result: await uploadAttachment(file) })),
      );
      const ok = results.flatMap((r) => (r.status === "fulfilled" ? [r.value] : []));
      const failed = results.find((r) => r.status === "rejected");
      await qc.invalidateQueries({ queryKey: ["/api/attachments"] });
      const latest = ok.at(-1)?.result;
      if (latest?.id) {
        setSelectedId(latest.id);
        setTab("preview");
      }
      const noText = ok.filter((item) => item.result.text_extracted === false);
      if (ok.length === 1 && noText.length === 1) {
        toast(t("workbench.pdfNoText", { name: ok[0].file.name }), "error");
      } else if (ok.length === 1) {
        toast(t("workbench.uploaded", { name: ok[0].file.name }), "ok");
      } else if (ok.length > 1) {
        toast(t("workbench.uploadedMany", { n: ok.length }), "ok");
        if (noText.length) toast(t("workbench.pdfNoTextMany", { n: noText.length }), "error");
      }
      if (failed?.status === "rejected") toast(errMsg(failed.reason), "error");
    } finally {
      setUploading(false);
    }
  };

  const downloadFile = async (item: AttachmentItem) => {
    try {
      if (item.has_data) {
        saveBlob(await apiBlob(`/api/attachments/${item.id}/raw`), item.filename);
        return;
      }
      const detail = await getAttachment(item.id);
      if (detail.has_data) {
        saveBlob(await apiBlob(`/api/attachments/${item.id}/raw`), item.filename);
        return;
      }
      saveBlob(
        new Blob([detail.content ?? ""], { type: "text/plain;charset=utf-8" }),
        item.filename,
      );
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };

  const toggleIndex = async (item: AttachmentItem) => {
    if (item.has_text === false || indexingId !== null) return;
    setIndexingId(item.id);
    try {
      await setAttachmentIndexed(item.id, !item.indexed);
      await qc.invalidateQueries({ queryKey: ["/api/attachments"] });
      toast(
        t(item.indexed ? "workbench.indexRemoveOk" : "workbench.indexAddOk", { name: item.filename }),
        "ok",
      );
    } catch (e) {
      toast(errMsg(e), "error");
    } finally {
      setIndexingId(null);
    }
  };

  const removeFile = async (item: AttachmentItem) => {
    try {
      await deleteAttachment(item.id);
      await qc.invalidateQueries({ queryKey: ["/api/attachments"] });
      if (selectedId === item.id) setSelectedId(null);
      toast(t("workbench.deleted", { name: item.filename }), "ok");
    } catch (e) {
      toast(errMsg(e), "error");
    }
  };

  const TABS: { key: WorkbenchTab; label: string; icon: typeof Files }[] = [
    { key: "files", label: t("workbench.files"), icon: Files },
    { key: "preview", label: t("workbench.preview"), icon: Eye },
    { key: "browser", label: t("workbench.browser"), icon: Globe2 },
  ];

  const body = (
    <>
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border/70 px-3">
        <span className="text-[13px] font-semibold">{t("workbench.title")}</span>
        {items.length > 0 && (
          <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
            {t("workbench.fileCount", { n: items.length })}
          </span>
        )}
        <button
          type="button"
          onClick={onClose}
          aria-label={t("workbench.close")}
          title={t("workbench.close")}
          className="ml-auto inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div role="tablist" aria-label={t("workbench.title")} className="grid shrink-0 grid-cols-3 gap-1 border-b border-border/60 p-1.5">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={cn(
              "inline-flex h-8 items-center justify-center gap-1.5 rounded-md text-[12px] transition-colors",
              tab === key
                ? "bg-primary/10 font-medium text-primary"
                : "text-muted-foreground hover:bg-accent hover:text-foreground",
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}
      </div>

      <div className="flex min-h-0 flex-1 flex-col">
        {tab === "files" && (
          <FilesPane
            items={items}
            pending={list.isPending}
            error={list.error}
            selectedId={selectedId}
            uploading={uploading}
            onRetry={() => void list.refetch()}
            onOpen={(item: AttachmentItem) => {
              setSelectedId(item.id);
              setTab("preview");
            }}
            onUpload={(files) => void upload(files)}
            onDownload={(item) => void downloadFile(item)}
            onDeleteRequest={setPendingDelete}
            onToggleIndex={(item) => void toggleIndex(item)}
            indexingId={indexingId}
          />
        )}
        {tab === "preview" && (
          <PreviewPane
            selected={selected}
            onOpenFiles={() => setTab("files")}
            onToggleIndex={(item) => void toggleIndex(item)}
            indexing={indexingId === selected?.id}
          />
        )}
        {tab === "browser" && <BrowserPane request={externalUrl} />}
      </div>
      {pendingDelete && (
        <ConfirmDialog
          open
          onOpenChange={(o) => { if (!o) setPendingDelete(null); }}
          title={t("workbench.deleteTitle", { name: pendingDelete.filename })}
          description={t("workbench.deleteDesc")}
          confirmText={t("workbench.delete")}
          danger
          onConfirm={() => {
            const item = pendingDelete;
            setPendingDelete(null);
            void removeFile(item);
          }}
        />
      )}
    </>
  );

  if (!open) return null;

  if (isWide) {
    return (
      <aside
        role="complementary"
        aria-label={t("workbench.title")}
        className="relative flex h-full shrink-0 flex-col border-l border-border bg-sidebar animate-fade-in"
        style={{ width: nav.width }}
      >
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label={t("workbench.resize")}
          aria-valuenow={nav.width}
          className={cn(
            "absolute -left-1 top-0 z-10 h-full w-2 cursor-col-resize transition-colors hover:bg-primary/30",
            nav.dragging && "bg-primary/40",
          )}
          {...nav.handleProps}
        />
        {body}
      </aside>
    );
  }

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-40"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      >
        <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} aria-hidden />
        <motion.aside
          role="dialog"
          aria-modal="true"
          aria-label={t("workbench.title")}
          initial={{ x: "100%" }}
          animate={{ x: 0 }}
          exit={{ x: "100%" }}
          transition={{ type: "spring", stiffness: 420, damping: 42 }}
          className="absolute right-0 top-0 flex h-full w-[92vw] max-w-[420px] flex-col border-l border-border bg-card shadow-lift"
          style={{
            paddingTop: "env(safe-area-inset-top)",
            paddingBottom: "env(safe-area-inset-bottom)",
          }}
        >
          {body}
        </motion.aside>
      </motion.div>
    </AnimatePresence>
  );
}

import { memo, useEffect, useRef, useState, type RefObject } from "react";
import {
  ArrowUp,
  AtSign,
  BarChart3,
  Globe,
  FileText,
  CreditCard,
  LayoutDashboard,
  Link2,
  Mic,
  Paperclip,
  Plus,
  Settings,
  Square,
  Telescope,
  Upload,
  Wallet,
  X,
} from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { cn, errMsg } from "@/lib/utils";
import { useToast } from "@/lib/toast";
import type { BootstrapData, RunAttachment } from "@/lib/types";
import { listAttachments } from "@/lib/api";
import { filterMentionFiles, mentionSpan, stripMention } from "@/components/chat-mentions";
import {
  CHAT_ATTACHMENT_ACCEPT,
  hasFileDrag,
  pickAttachmentFiles,
} from "@/lib/chat-attachments";

export interface ChatInputProps {
  input: string;
  onInputChange: (v: string) => void;
  busy: boolean;
  listening: boolean;
  voiceOn: boolean;
  llmConfigured: boolean;
  inputRef: RefObject<HTMLTextAreaElement | null>;
  onToggleVoice: () => void;
  onSend: () => void;
  onStop: () => void;
  onOpenSettings: () => void;
  onSlashCommand: (id: string) => void;
  /** 当前生效的模型名（composer 显示，对标 ChatGPT） */
  modelName?: string;
  /** 模型目录 + 已点亮清单（P0 模型点亮）：输入区只显示已点亮的模型 */
  modelCatalog?: BootstrapData["model_catalog"];
  enabledModels?: string[];
  /** 快捷切换模型：写入设置 ai_base_url + ai_model */
  onSwitchModel?: (base: string, model: string) => void;
  /** 联网搜索开关：开启后后端优先调用 web_search 并标注来源 */
  webSearch?: boolean;
  onToggleWebSearch?: () => void;
  /** 深度研究：强制联网 + 四节报告结构 + 更多工具轮次 */
  deepResearch?: boolean;
  onToggleDeepResearch?: () => void;
  /** 回答长度：简洁 / 标准 / 详尽 */
  answerMode?: "concise" | "standard" | "detailed";
  onAnswerModeChange?: (v: "concise" | "standard" | "detailed") => void;
  /** @提及附件：已选附件列表 + 上传/移除 */
  attachments?: RunAttachment[];
  onAddAttachment?: (file: File) => Promise<unknown>;
  /** 从工作台已有文件里引用一条，不复制、不重新上传。 */
  onReferenceAttachment?: (file: RunAttachment) => void;
  onRemoveAttachment?: (id: number) => void;
  /** 点附件胶囊：打开工作台预览。 */
  onOpenAttachment?: (id: number) => void;
}

const SLASH_ITEMS = [
  { id: "go-overview", key: "cmd.goOverview", icon: LayoutDashboard },
  { id: "go-holdings", key: "cmd.goHoldings", icon: Wallet },
  { id: "go-market", key: "cmd.goMarket", icon: BarChart3 },
  { id: "go-ledger", key: "cmd.goLedger", icon: CreditCard },
  { id: "go-settings", key: "cmd.goSettings", icon: Settings },
  { id: "new-session", key: "cmd.newSession", icon: Plus },
] as const;

/**
 * 输入区（ChatGPT 式 composer）：
 * 一个圆角容器托住全部控件——附件在左上、文本域居中、语音/发送在右下，
 * 获得焦点时整块抬升为白色浮层（阴影 + 边框），而不是给 textarea 单独描边。
 */
export const ChatInput = memo(
  ({
    input,
    onInputChange,
    busy,
    listening,
    voiceOn,
    inputRef,
    onToggleVoice,
    onSend,
    onStop,
    onSlashCommand,
    webSearch,
    onToggleWebSearch,
    deepResearch,
    onToggleDeepResearch,
    answerMode = "standard",
    onAnswerModeChange,
    attachments,
    onAddAttachment,
    onReferenceAttachment,
    onRemoveAttachment,
    onOpenAttachment,
    llmConfigured,
    onOpenSettings,
    modelName,
    modelCatalog,
    enabledModels,
    onSwitchModel,
  }: ChatInputProps) => {
    const { t: tr } = useI18n();
    const { toast } = useToast();
    const fileRef = useRef<HTMLInputElement>(null);
    // 模型快捷切换：只列「已点亮」的模型，避免下拉里一堆没 key 的选项。
    // 设置页文案承诺过「点亮后出现在输入框下拉」，此前这个下拉根本不存在。
    const modelOptions = (modelCatalog ?? []).filter(
      (m) => !enabledModels?.length || enabledModels.includes(m.model),
    );
    const [uploading, setUploading] = useState(false);
    const [focused, setFocused] = useState(false);
    const [dragging, setDragging] = useState(false);
    // @ 引用工作台文件：弹出面板只在输入尾部出现 `@关键词` 时打开
    const [mentionFiles, setMentionFiles] = useState<RunAttachment[]>([]);
    const [mentionLoading, setMentionLoading] = useState(false);
    const [mentionIdx, setMentionIdx] = useState(0);

    const slashQ = input.startsWith("/") ? input.trim().slice(1).toLowerCase() : "";
    const slashItems = SLASH_ITEMS.filter((it) => tr(it.key).toLowerCase().includes(slashQ));
    const slashOpen = input.startsWith("/") && slashItems.length > 0;
    const [activeIdx, setActiveIdx] = useState(0);
    useEffect(() => setActiveIdx(0), [slashQ]);

    const mention = mentionSpan(input);
    const mentionActive = mention !== null;
    const mentionQ = mention?.query ?? "";
    const mentionOptions = filterMentionFiles(mentionFiles, mentionQ);
    useEffect(() => setMentionIdx(0), [mentionQ]);

    // 只在面板打开时拉一次工作台清单；切换对话/重传文件后下一次打开会重新取。
    useEffect(() => {
      if (!mentionActive) return;
      let alive = true;
      setMentionLoading(true);
      listAttachments()
        .then((items) => {
          if (!alive) return;
          setMentionFiles(
            items.map((a) => ({ id: a.id, filename: a.filename, kind: a.kind, mime: a.mime })),
          );
        })
        .catch(() => {
          if (alive) setMentionFiles([]);
        })
        .finally(() => {
          if (alive) setMentionLoading(false);
        });
      return () => {
        alive = false;
      };
    }, [mentionActive]);

    const chooseMention = (file: RunAttachment) => {
      const span = mentionSpan(input);
      if (!span) return;
      onReferenceAttachment?.({ ...file, ref: true });
      onInputChange(stripMention(input, span.start));
      setMentionIdx(0);
      inputRef.current?.focus();
    };

    const pick = (it: (typeof SLASH_ITEMS)[number]) => {
      onInputChange("");
      onSlashCommand(it.id);
      inputRef.current?.focus();
    };

    useEffect(() => {
      const el = inputRef.current;
      if (!el) return;
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 168)}px`;
    }, [input, inputRef]);

    const canSend = Boolean(input.trim()) && !busy;
    const hasAttachments = Boolean(attachments && attachments.length > 0);
    const hasImageAttachment = Boolean(attachments?.some((a) => a.kind === "image"));

    /** 文件选择、粘贴、拖拽共用；多选用 allSettled，不让一个坏文件拖垮整批。 */
    const addFiles = async (files: File[]) => {
      if (!files.length || !onAddAttachment) return;
      const { accepted, rejected } = pickAttachmentFiles(files);
      if (rejected.length) {
        toast(`${tr("chat.attachUnsupported")}：${rejected.slice(0, 3).join("、")}`, "error");
      }
      if (!accepted.length) return;
      setUploading(true);
      try {
        const results = await Promise.allSettled(accepted.map((f) => onAddAttachment(f)));
        const failed = results.find((r) => r.status === "rejected");
        if (failed?.status === "rejected") toast(errMsg(failed.reason), "error");
      } finally {
        setUploading(false);
      }
    };

    return (
      <div className="shrink-0 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:px-4 sm:pb-4">
        <div className="mx-auto w-full max-w-[48rem]">
          {slashOpen && (
            <div className="mb-2 overflow-hidden rounded-xl border border-border bg-popover p-1 shadow-lift">
              {slashItems.map((it, i) => {
                const Icon = it.icon;
                return (
                  <button
                    key={it.id}
                    type="button"
                    onMouseEnter={() => setActiveIdx(i)}
                    onClick={() => pick(it)}
                    className={cn(
                      "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm transition-colors",
                      i === activeIdx ? "bg-accent text-foreground" : "text-muted-foreground",
                    )}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    <span className="min-w-0 flex-1 truncate">{tr(it.key)}</span>
                    <kbd className="rounded border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      ↵
                    </kbd>
                  </button>
                );
              })}
            </div>
          )}

          {mentionActive && (
            <div
              data-testid="file-mentions"
              className="mb-2 overflow-hidden rounded-xl border border-border bg-popover shadow-lift"
            >
              <div className="flex items-center justify-between border-b border-border/60 px-3 py-2 text-[11px] text-muted-foreground">
                <span className="inline-flex items-center gap-1.5">
                  <AtSign className="h-3.5 w-3.5" />
                  {tr("chat.referenceFile")}
                </span>
                {mentionLoading && <span>{tr("chat.referenceLoading")}</span>}
              </div>
              {mentionOptions.length > 0 ? (
                <div className="max-h-56 overflow-y-auto p-1">
                  {mentionOptions.map((file, i) => {
                    const picked = attachments?.some((a) => a.id === file.id);
                    return (
                      <button
                        key={file.id}
                        type="button"
                        onMouseDown={(e) => e.preventDefault()}
                        onMouseEnter={() => setMentionIdx(i)}
                        onClick={() => chooseMention(file)}
                        className={cn(
                          "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors",
                          i === mentionIdx ? "bg-accent text-foreground" : "text-muted-foreground",
                        )}
                      >
                        <FileText className="h-4 w-4 shrink-0" />
                        <span className="min-w-0 flex-1 truncate text-[13px]">{file.filename}</span>
                        {picked ? (
                          <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">
                            {tr("chat.referenceAdded")}
                          </span>
                        ) : (
                          <span className="shrink-0 text-[10px] uppercase text-muted-foreground/70">
                            {file.kind}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              ) : (
                <div className="px-3 py-3 text-[12px] text-muted-foreground">
                  {mentionLoading ? tr("chat.referenceLoading") : tr("chat.referenceEmpty")}
                </div>
              )}
            </div>
          )}

          <div
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
              void addFiles(Array.from(e.dataTransfer.files ?? []));
            }}
            className={cn(
              "relative rounded-[26px] border bg-card px-3 py-2.5 transition-shadow",
              focused || hasAttachments || input
                ? "border-border shadow-[0_2px_10px_rgb(0_0_0/0.06)]"
                : "border-transparent bg-muted/60 shadow-none",
            )}
          >
            {dragging && (
              <div className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center rounded-[26px] border-2 border-dashed border-primary/45 bg-card/95 text-center">
                <Upload className="mb-1.5 h-5 w-5 text-primary" />
                <span className="text-[13px] font-medium text-foreground">{tr("chat.dropHere")}</span>
                <span className="mt-0.5 text-[11px] text-muted-foreground">{tr("chat.dropHint")}</span>
              </div>
            )}

            {hasAttachments && (
              <div className="mb-1.5 flex flex-wrap gap-1.5 px-0.5">
                {attachments!.map((a) => (
                  <span
                    key={a.id}
                    className="inline-flex max-w-full items-center gap-1 rounded-lg border border-border bg-background py-1 pl-2 pr-1 text-[12px] text-foreground/80"
                  >
                    <button
                      type="button"
                      onClick={() => onOpenAttachment?.(a.id)}
                      title={tr("chat.openAttachment")}
                      className="inline-flex min-w-0 items-center gap-1.5 rounded text-left hover:text-primary"
                    >
                      {a.ref ? (
                        <Link2 className="h-3 w-3 shrink-0 text-primary/70" />
                      ) : (
                        <Paperclip className="h-3 w-3 shrink-0 text-muted-foreground" />
                      )}
                      <span className="max-w-[11rem] truncate">{a.filename}</span>
                      {a.ref && (
                        <span className="rounded bg-primary/10 px-1 text-[10px] text-primary">
                          {tr("chat.referenceBadge")}
                        </span>
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => onRemoveAttachment?.(a.id)}
                      aria-label={tr("chat.removeAttachment")}
                      className="rounded p-0.5 text-muted-foreground hover:text-red-600"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}

            {hasImageAttachment && (
              <div className="mb-1.5 flex items-start gap-1.5 rounded-lg bg-primary/5 px-2 py-1.5 text-[11.5px] leading-relaxed text-muted-foreground">
                <span className="mt-0.5 shrink-0 rounded bg-primary/10 px-1 py-0.5 text-[10px] font-medium text-primary">
                  {tr("chat.imageBadge")}
                </span>
                <span>{tr("chat.visionHint")}</span>
              </div>
            )}

            <div className="flex items-end gap-1.5">
              {/* 模型快捷切换：只在有多个已点亮模型时出现，单模型不占地方 */}
              {onSwitchModel && modelOptions.length > 1 && (
                <label className="mb-0.5 shrink-0 max-sm:hidden" title={tr("chat.switchModel")}>
                  <span className="sr-only">{tr("chat.switchModel")}</span>
                  <select
                    value={modelOptions.find((m) => m.model === modelName)?.id ?? ""}
                    onChange={(e) => {
                      const picked = modelOptions.find((m) => m.id === e.target.value);
                      if (picked) void onSwitchModel(picked.base, picked.model);
                    }}
                    className="h-9 max-w-[10rem] cursor-pointer truncate rounded-full border border-border/70 bg-transparent px-2 text-[12px] text-foreground/75 focus:outline-none focus:ring-2 focus:ring-ring"
                  >
                    {modelOptions.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {onToggleDeepResearch && (
                <button
                  type="button"
                  aria-label={tr("chat.deepResearch")}
                  aria-pressed={Boolean(deepResearch)}
                  title={tr("chat.deepResearchHint")}
                  onClick={onToggleDeepResearch}
                  className={cn(
                    "mb-0.5 inline-flex h-9 shrink-0 items-center justify-center gap-1 rounded-full px-2 transition-colors",
                    deepResearch
                      ? "bg-primary/10 text-primary"
                      : "text-foreground/55 hover:bg-accent hover:text-foreground",
                  )}
                >
                  <Telescope className="h-[17px] w-[17px]" />
                  <span className="text-[12px] font-medium max-sm:hidden">
                    {tr("chat.deepResearch")}
                  </span>
                </button>
              )}
              {onAnswerModeChange && (
                <select
                  value={answerMode}
                  onChange={(e) => onAnswerModeChange(e.target.value as "concise" | "standard" | "detailed")}
                  aria-label={tr("chat.answerMode")}
                  title={tr("chat.answerModeHint")}
                  className="mb-0.5 h-9 max-w-[5.5rem] shrink-0 cursor-pointer truncate rounded-full border border-border/70 bg-transparent px-2 text-[12px] text-foreground/75 focus:outline-none focus:ring-2 focus:ring-ring max-sm:max-w-[4.2rem]"
                >
                  <option value="concise">{tr("chat.answerMode.concise")}</option>
                  <option value="standard">{tr("chat.answerMode.standard")}</option>
                  <option value="detailed">{tr("chat.answerMode.detailed")}</option>
                </select>
              )}
              <button
                type="button"
                aria-label={tr("chat.webSearch")}
                aria-pressed={Boolean(webSearch)}
                title={tr("chat.webSearchHint")}
                onClick={onToggleWebSearch}
                className={cn(
                  "mb-0.5 inline-flex h-9 shrink-0 items-center justify-center gap-1 rounded-full px-2 transition-colors",
                  webSearch
                    ? "bg-primary/10 text-primary"
                    : "text-foreground/55 hover:bg-accent hover:text-foreground",
                )}
              >
                <Globe className="h-[17px] w-[17px]" />
                <span className="text-[12px] font-medium max-sm:hidden">
                  {tr("chat.webSearch")}
                </span>
                <span className="text-[12px] font-medium sm:hidden">
                  {tr("chat.webSearchShort")}
                </span>
              </button>
              <label
                className="mb-0.5 inline-flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-full text-foreground/55 transition-colors hover:bg-accent hover:text-foreground"
                title={tr("chat.attachHint")}
              >
                <Paperclip className="h-[18px] w-[18px]" />
                <span className="sr-only">{tr("chat.attach")}</span>
                <input
                  type="file"
                  ref={fileRef}
                  className="hidden"
                  accept={CHAT_ATTACHMENT_ACCEPT}
                  multiple
                  onChange={(e) => {
                    const picked = Array.from(e.target.files ?? []);
                    if (picked.length) void addFiles(picked);
                    e.target.value = "";
                  }}
                />
              </label>

              <button
                type="button"
                aria-label={tr("chat.referenceFile")}
                aria-pressed={mentionActive}
                title={tr("chat.referenceHint")}
                onClick={() => {
                  const next = input && !input.endsWith(" ") ? `${input} @` : `${input}@`;
                  onInputChange(next);
                  inputRef.current?.focus();
                }}
                className={cn(
                  "mb-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-colors",
                  mentionActive
                    ? "bg-primary/10 text-primary"
                    : "text-foreground/55 hover:bg-accent hover:text-foreground",
                )}
              >
                <AtSign className="h-[18px] w-[18px]" />
              </button>

              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => onInputChange(e.target.value)}
                onFocus={() => setFocused(true)}
                onBlur={() => setFocused(false)}
                onPaste={(e) => {
                  const pasted = Array.from(e.clipboardData.files ?? []);
                  if (!pasted.length) return;
                  // 截图粘贴通常没有文本；纯图片时吞掉默认行为，避免多插一个换行。
                  if (!e.clipboardData.getData("text/plain")) e.preventDefault();
                  void addFiles(pasted);
                }}
                onKeyDown={(e) => {
                  if (mentionActive) {
                    if (e.key === "ArrowDown") {
                      e.preventDefault();
                      setMentionIdx((i) => (i + 1) % Math.max(1, mentionOptions.length));
                      return;
                    }
                    if (e.key === "ArrowUp") {
                      e.preventDefault();
                      setMentionIdx(
                        (i) => (i - 1 + Math.max(1, mentionOptions.length)) % Math.max(1, mentionOptions.length),
                      );
                      return;
                    }
                    if (e.key === "Enter") {
                      e.preventDefault();
                      const picked = mentionOptions[mentionIdx];
                      if (picked) chooseMention(picked);
                      return;
                    }
                    if (e.key === "Escape") {
                      e.preventDefault();
                      const span = mentionSpan(input);
                      if (span) onInputChange(stripMention(input, span.start));
                      return;
                    }
                  }
                  if (slashOpen) {
                    if (e.key === "ArrowDown") {
                      e.preventDefault();
                      setActiveIdx((i) => (i + 1) % slashItems.length);
                      return;
                    }
                    if (e.key === "ArrowUp") {
                      e.preventDefault();
                      setActiveIdx((i) => (i - 1 + slashItems.length) % slashItems.length);
                      return;
                    }
                    if (e.key === "Enter") {
                      e.preventDefault();
                      pick(slashItems[activeIdx]);
                      return;
                    }
                    if (e.key === "Escape") {
                      e.preventDefault();
                      const slashIdx = input.indexOf("/");
                      onInputChange(
                        slashIdx >= 0 ? input.slice(0, slashIdx) + input.slice(slashIdx + 1) : input,
                      );
                      return;
                    }
                  }
                  // 输入法组合期（中文拼音未上屏）按 Enter 不发送
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    onSend();
                  }
                }}
                rows={1}
                placeholder={tr("chat.inputPh")}
                aria-label={tr("chat.inputPh")}
                className="max-h-[168px] min-h-[24px] min-w-0 flex-1 resize-none self-center overflow-y-auto scroll-thin bg-transparent py-1.5 text-[16px] leading-6 outline-none placeholder:text-muted-foreground/80"
              />

              {voiceOn && (
                <button
                  type="button"
                  aria-label={tr("chat.voiceInput")}
                  onClick={onToggleVoice}
                  className={cn(
                    "mb-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-colors hover:bg-accent",
                    listening ? "bg-primary/10 text-primary" : "text-foreground/55 hover:text-foreground",
                  )}
                >
                  <Mic className="h-[18px] w-[18px]" />
                </button>
              )}

              {busy ? (
                <button
                  type="button"
                  onClick={onStop}
                  aria-label={tr("chat.stop")}
                  className="mb-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-foreground text-background transition-opacity hover:opacity-80"
                >
                  <Square className="h-3.5 w-3.5 fill-current" />
                </button>
              ) : (
                <button
                  type="button"
                  onClick={onSend}
                  disabled={!canSend}
                  aria-label={tr("chat.send")}
                  className={cn(
                    "mb-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-all",
                    canSend
                      ? "bg-primary text-primary-foreground hover:bg-primary/90"
                      : "cursor-not-allowed bg-muted text-muted-foreground/50",
                  )}
                >
                  <ArrowUp className="h-[18px] w-[18px]" strokeWidth={2.4} />
                </button>
              )}
            </div>
          </div>

          <div className="mt-2 flex items-center justify-center gap-3 px-1 text-center text-[11px] text-muted-foreground">
            {!llmConfigured ? (
              <span className="inline-flex items-center gap-1">
                {tr("chat.noAiShort")}
                <button
                  type="button"
                  onClick={onOpenSettings}
                  className="font-medium text-primary hover:underline"
                >
                  {tr("chat.goSetup")}
                </button>
              </span>
            ) : (
              <span className="inline-flex flex-wrap items-center justify-center gap-x-2 gap-y-1">
                <span>{tr("chat.enterHint")}</span>
                <span className="hidden sm:inline">·</span>
                <span className="hidden sm:inline">{tr("chat.slashHint")}</span>
                {onReferenceAttachment && (
                  <>
                    <span className="hidden sm:inline">·</span>
                    <span className="hidden sm:inline">{tr("chat.referenceHint")}</span>
                  </>
                )}
                {uploading && <span>· {tr("chat.attach")}…</span>}
              </span>
            )}
          </div>
        </div>
      </div>
    );
  },
);

ChatInput.displayName = "ChatInput";

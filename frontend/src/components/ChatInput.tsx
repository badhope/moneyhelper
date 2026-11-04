import { memo, useEffect, useRef, useState, type RefObject } from "react";
import {
  ArrowUp,
  BarChart3,
  CreditCard,
  LayoutDashboard,
  Mic,
  Paperclip,
  Plus,
  Settings,
  Square,
  Wallet,
  X,
} from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { useToast } from "@/lib/toast";
import type { BootstrapData } from "@/lib/types";

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
  /** @提及附件：已选附件列表 + 上传/移除 */
  attachments?: { id: number; filename: string; kind: string }[];
  onAddAttachment?: (file: File) => Promise<unknown>;
  onRemoveAttachment?: (id: number) => void;
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
    attachments,
    onAddAttachment,
    onRemoveAttachment,
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

    const slashQ = input.startsWith("/") ? input.trim().slice(1).toLowerCase() : "";
    const slashItems = SLASH_ITEMS.filter((it) => tr(it.key).toLowerCase().includes(slashQ));
    const slashOpen = input.startsWith("/") && slashItems.length > 0;
    const [activeIdx, setActiveIdx] = useState(0);
    useEffect(() => setActiveIdx(0), [slashQ]);

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

          <div
            className={cn(
              "rounded-[26px] border bg-card px-3 py-2.5 transition-shadow",
              focused || hasAttachments || input
                ? "border-border shadow-[0_2px_10px_rgb(0_0_0/0.06)]"
                : "border-transparent bg-muted/60 shadow-none",
            )}
          >
            {hasAttachments && (
              <div className="mb-1.5 flex flex-wrap gap-1.5 px-0.5">
                {attachments!.map((a) => (
                  <span
                    key={a.id}
                    className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-border bg-background px-2 py-1 text-[12px] text-foreground/80"
                  >
                    <Paperclip className="h-3 w-3 shrink-0 text-muted-foreground" />
                    <span className="max-w-[11rem] truncate">{a.filename}</span>
                    <button
                      type="button"
                      onClick={() => onRemoveAttachment?.(a.id)}
                      aria-label={tr("chat.removeAttachment")}
                      className="rounded text-muted-foreground hover:text-red-600"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}

            <div className="flex items-end gap-1.5">
              {/* 模型快捷切换：只在有多个已点亮模型时出现，单模型不占地方 */}
              {onSwitchModel && modelOptions.length > 1 && (
                <label className="mb-0.5 shrink-0" title={tr("chat.switchModel")}>
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
              <label
                className="mb-0.5 inline-flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-full text-foreground/55 transition-colors hover:bg-accent hover:text-foreground"
                title={tr("chat.attach")}
              >
                <Paperclip className="h-[18px] w-[18px]" />
                <span className="sr-only">{tr("chat.attach")}</span>
                <input
                  type="file"
                  ref={fileRef}
                  className="hidden"
                  accept=".txt,.md,.json,.csv,.log"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) {
                      setUploading(true);
                      onAddAttachment?.(f)
                        .catch((err) => toast(err instanceof Error ? err.message : String(err), "error"))
                        .finally(() => setUploading(false));
                    }
                    e.target.value = "";
                  }}
                />
              </label>

              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => onInputChange(e.target.value)}
                onFocus={() => setFocused(true)}
                onBlur={() => setFocused(false)}
                onKeyDown={(e) => {
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
                className="max-h-[168px] min-h-[24px] flex-1 resize-none self-center overflow-y-auto scroll-thin bg-transparent py-1.5 text-[16px] leading-6 outline-none placeholder:text-muted-foreground/80"
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

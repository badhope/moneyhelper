import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, BarChart3, Clock3, CreditCard, Download, Gauge, Search, Sparkles, Trash2, Wallet, X, type LucideIcon } from "lucide-react";
import { useBootstrap, useDashboard, store } from "@/lib/store";
import { useI18n } from "@/lib/i18n";
import { api, saveBlob } from "@/lib/api";
import { copyText } from "@/lib/clipboard";
import { fmtTokens } from "@/lib/format";
import type { AgentToolStep, AgentPlanStep } from "@/lib/types";
import type { ChatMessage, StepInfo } from "@/components/ChatMessageBubble";
import { ChatInput } from "@/components/ChatInput";
import { ChatMessageBubble } from "@/components/ChatMessageBubble";
import { FinishedMessages } from "@/components/FinishedMessages";
import { useChatView } from "@/components/chat-view-state";
import { useToast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { requestOpenAttachment } from "@/lib/workbench";

/** 搜索命中：把关键词附近 60 字截出来，避免结果行被超长回答撑爆。 */
function snippet(text: string, q: string): string {
  const lower = text.toLowerCase();
  const i = lower.indexOf(q.trim().toLowerCase());
  if (i < 0) return text.slice(0, 80);
  return `${i > 24 ? "…" : ""}${text.slice(Math.max(0, i - 24), i + 56)}${i + 56 < text.length ? "…" : ""}`;
}

/** 空态示例：4 个真实可执行的起点，带图标走"建议卡"而不是零散胶囊。 */
const SUGGESTIONS = [
  { key: "chat.capHold1", icon: BarChart3 },
  { key: "chat.capBook1", icon: CreditCard },
  { key: "chat.sSpend", icon: Wallet },
  { key: "chat.capAct1", icon: Sparkles },
] as const;

export function ChatView({
  threadId,
  locateRunId,
  onLocateDone,
  onNewSession,
  onOpenSettings,
  onNavigate,
  onDeleteSession,
  sessionId,
  onForked,
}: {
  threadId: string;
  locateRunId?: number | null;
  onLocateDone?: () => void;
  onNewSession: () => void;
  onOpenSettings: () => void;
  onDeleteSession?: () => void;
  onNavigate: (tab: string) => void;
  /** 当前会话 id（分支接口按 id 调用；尚未落库的临时线程为空） */
  sessionId?: number;
  /** 分支创建成功：切到新线程 */
  onForked?: (threadId: string) => void;
}) {
  const { t: tr } = useI18n();
  const { bootstrap } = useBootstrap();
  const { dashboard } = useDashboard();
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const { toast } = useToast();
  const [findOpen, setFindOpen] = useState(false);
  const [findQ, setFindQ] = useState("");
  const findInputRef = useRef<HTMLInputElement>(null);

  const {
    messages, input, setInput, attachments,
    showSteps, exportOn, scrolledUp, handleListScroll,
    voiceOn, voiceOutputOn, suggestions, hasData, webSearch, setWebSearch,
    stream, streamingMsg, finishedMessages,
    bubbleCallbacks, listening, scrollNow, stableEdit,
    stableSend, stableSendInput, stableStop, stableToggleVoice,
    uploadAttachment, removeAttachment, refreshBootstrap,
    usage,
  } = useChatView({ threadId, locateRunId, onLocateDone, inputRef, listRef });

  const forkMessage = async (m: ChatMessage) => {
    if (!sessionId || !m.runId) return;
    try {
      const r = await api<{ thread_id: string }>(`/api/sessions/${sessionId}/fork`, {
        method: "POST",
        body: JSON.stringify({ run_id: m.runId }),
      });
      await store.refreshSessions();
      onForked?.(r.thread_id);
      toast(tr("chat.forked"), "ok");
    } catch {
      toast(tr("chat.error"), "error");
    }
  };

  const findResults = useMemo(() => {
    const q = findQ.trim().toLowerCase();
    if (!q) return [];
    return messages
      .filter((m) => (m.text || "").toLowerCase().includes(q))
      .slice(-20)
      .reverse();
  }, [messages, findQ]);

  const jumpToMessage = (id: number) => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-msg-id="${id}"]`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("locate-flash");
    window.setTimeout(() => el.classList.remove("locate-flash"), 1800);
    setFindOpen(false);
    setFindQ("");
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "f") {
        e.preventDefault();
        setFindOpen(true);
        window.setTimeout(() => findInputRef.current?.focus(), 0);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const copyMessageLink = (m: ChatMessage) => {
    if (!m.runId) return;
    const url = new URL("/", window.location.origin);
    url.searchParams.set("thread", threadId);
    url.searchParams.set("run", String(m.runId));
    if (copyText(url.toString())) toast(tr("chat.linkCopied"), "ok");
    else toast(tr("chat.error"), "error");
  };

  const exportConversation = () => {
    const lines = [`# ${tr("chat.exportTitle")}`, "", `- ${tr("chat.exportTime", { t: new Date().toLocaleString() })}`, ""];
    for (const m of messages) {
      const body = (m.text || "").trim();
      if (!body) continue;
      lines.push(m.role === "user" ? "## 👤" : "## Moneyhelper", "", body, "");
    }
    const md = lines.join("\n");
    saveBlob(
      new Blob([md], { type: "text/markdown;charset=utf-8" }),
      `moneyhelper-${threadId.slice(0, 8)}.md`,
    );
    toast(tr("chat.exportDone"), "ok");
  };

  const empty = messages.length === 0;
  // 空态展示：优先用后端根据真实账本生成的建议，没有则回落到通用起点
  const starters: { key: string; icon: LucideIcon }[] =
    suggestions.length > 0
      ? suggestions.slice(0, 4).map((k) => ({ key: k, icon: Sparkles }))
      : SUGGESTIONS.map((s) => ({ key: s.key, icon: s.icon }));

  // 上下文条：持仓数 / 会话轮次 / 数据更新时间
  const holdingsCount = (dashboard?.positions ?? []).filter((p) => p.kind !== "现金").length;
  const updatedLabel = new Date().toLocaleTimeString(tr("chat.locale") === "zh" ? "zh-CN" : "en-US", {
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="relative min-h-0 flex-1">
          <div
            ref={listRef}
            onScroll={handleListScroll}
            className="h-full overflow-y-auto scroll-thin"
          >
            <div className="mx-auto w-full max-w-[48rem] px-4 pb-10 pt-4 sm:px-6">
              {/* 上下文条：明确告诉用户助手此刻看的是哪份数据、多久之前。
                  没有它，"我的持仓怎么样" 回答里的数字缺少可信度锚点。 */}
              {!empty && (
                // sticky 而不是普通行：上下文条是"这份回答基于哪份数据"的锚点，
                // 长回答往下滚时它必须一直可见，否则锚点只存在于第一屏。
                // top-0（不是负值）：负偏移会把条带推到滚动容器上沿之外，
                // 被 48px 顶栏盖住 16px，滚动后只剩一条灰边。
                <div className="sticky top-0 z-10 -mx-4 mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border/60 bg-background/95 px-4 pb-2 pt-2 text-[11px] text-muted-foreground backdrop-blur sm:-mx-6 sm:px-6">
                  <span className="inline-flex items-center gap-1">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                    {tr("chat.ctxLocal")}
                  </span>
                  <span>{tr("chat.ctxHoldings", { n: holdingsCount })}</span>
                  <span>{tr("chat.ctxTurns", { n: messages.length })}</span>
                  {/* harness：上下文用量。只在有真实计量时出现——模板降级轮
                      没有 token 数据，显示 0 反而误导。 */}
                  {usage && usage.tokens_total > 0 && (
                    <span
                      className="inline-flex items-center gap-1 tabular-nums"
                      title={tr("chat.ctxUsageHint", {
                        in: String(usage.tokens_in),
                        out: String(usage.tokens_out),
                      })}
                    >
                      <Gauge className="h-3 w-3" />
                      {fmtTokens(usage.tokens_total)}
                      {usage.compacted && (
                        <span className="rounded bg-primary/10 px-1 text-[10px] text-primary">
                          {tr("chat.ctxCompacted")}
                        </span>
                      )}
                    </span>
                  )}
                  <span className="ml-auto inline-flex items-center gap-1">
                    <Clock3 className="h-3 w-3" />
                    {tr("chat.ctxUpdated", { t: updatedLabel })}
                  </span>
                  {messages.length > 0 && (
                    <button
                      type="button"
                      onClick={() => {
                        setFindOpen((v) => !v);
                        if (!findOpen) window.setTimeout(() => findInputRef.current?.focus(), 0);
                      }}
                      aria-label={tr("chat.findInChat")}
                      title={`${tr("chat.findInChat")} · Ctrl+F`}
                      className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                    >
                      <Search className="h-3 w-3" />
                    </button>
                  )}
                  {messages.length > 0 && (
                    <button
                      type="button"
                      onClick={exportConversation}
                      aria-label={tr("chat.exportSession")}
                      title={tr("chat.exportSession")}
                      className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                    >
                      <Download className="h-3 w-3" />
                      <span className="hidden sm:inline">{tr("chat.exportSession")}</span>
                    </button>
                  )}
                  {onDeleteSession && (
                    <button
                      type="button"
                      onClick={onDeleteSession}
                      aria-label={tr("chat.deleteChat")}
                      title={tr("chat.deleteChat")}
                      className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-muted-foreground transition-colors hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/40"
                    >
                      <Trash2 className="h-3 w-3" />
                      <span className="sm:hidden">{tr("chat.deleteShort")}</span>
<span className="hidden sm:inline">{tr("chat.deleteChat")}</span>
                    </button>
                  )}
                  {findOpen && (
                    <div className="relative order-last w-full pt-1">
                      <div className="flex items-center gap-1.5 rounded-md border border-border bg-card px-2 py-1">
                        <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        <input
                          ref={findInputRef}
                          value={findQ}
                          onChange={(e) => setFindQ(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Escape") {
                              setFindOpen(false);
                              setFindQ("");
                            }
                            if (e.key === "Enter" && findResults[0]) jumpToMessage(findResults[0].id);
                          }}
                          placeholder={tr("chat.findPh")}
                          className="h-6 min-w-0 flex-1 bg-transparent text-xs outline-none"
                        />
                        <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
                          {findQ.trim() ? findResults.length : ""}
                        </span>
                        <button
                          type="button"
                          onClick={() => { setFindOpen(false); setFindQ(""); }}
                          aria-label={tr("chat.cancel")}
                          className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </div>
                      {findQ.trim() && (
                        <div className="absolute left-0 right-0 top-full z-20 mt-1 max-h-64 overflow-y-auto rounded-md border border-border bg-background py-1 shadow-lg scroll-thin">
                          {findResults.length === 0 ? (
                            <p className="px-3 py-4 text-center text-xs text-muted-foreground">
                              {tr("chat.findNoMatch")}
                            </p>
                          ) : (
                            findResults.map((m) => (
                              <button
                                key={m.id}
                                type="button"
                                onClick={() => jumpToMessage(m.id)}
                                className="flex w-full items-start gap-2 px-2.5 py-1.5 text-left hover:bg-accent"
                              >
                                <span className={cn(
                                  "mt-0.5 shrink-0 rounded px-1 py-0.5 text-[9.5px]",
                                  m.role === "user"
                                    ? "bg-muted text-muted-foreground"
                                    : "bg-primary/10 text-primary",
                                )}>
                                  {m.role === "user" ? tr("chat.you") : "MH"}
                                </span>
                                <span className="line-clamp-2 min-w-0 text-[11.5px] leading-relaxed text-foreground/80">
                                  {snippet(m.text, findQ)}
                                </span>
                              </button>
                            ))
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
              {empty ? (
                <div className="flex min-h-[calc(100dvh-16rem)] flex-col items-center justify-center py-10 text-center">
                  <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
                    <Sparkles className="h-6 w-6 text-primary" />
                  </div>
                  <h1 className="text-balance text-[26px] font-semibold leading-tight tracking-tight sm:text-[30px]">
                    {tr("chat.heroQuestion")}
                  </h1>
                  <p className="mt-2 max-w-md text-sm text-muted-foreground">
                    {hasData ? tr("chat.heroMotto") : tr("chat.heroEmptyHint")}
                  </p>

                  <div className="mt-8 grid w-full max-w-lg grid-cols-1 gap-1 sm:grid-cols-2">
                    {starters.map(({ key, icon: Icon }) => (
                      <button
                        key={key}
                        type="button"
                        disabled={stream.isPending}
                        onClick={() => void stableSend(tr(key))}
                        className="group flex items-center gap-3 rounded-xl border border-border/80 px-3.5 py-3 text-left transition-colors hover:border-border hover:bg-accent/60 disabled:opacity-50"
                      >
                        <Icon className="h-4 w-4 shrink-0 text-muted-foreground group-hover:text-primary" />
                        <span className="min-w-0 text-[13.5px] leading-snug text-foreground/85">
                          {tr(key)}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="space-y-6 pt-2">
                  <FinishedMessages
                    messages={finishedMessages}
                    busy={stream.isPending}
                    showSteps={showSteps}
                    exportOn={exportOn}
                    voiceOn={voiceOutputOn}
                    onNavigate={onNavigate}
                    onFork={forkMessage}
                    onCopyLink={copyMessageLink}
                    onEdit={stableEdit}
                    {...bubbleCallbacks}
                  />
                  {streamingMsg && (
                    <ChatMessageBubble
                      message={streamingMsg}
                      busy={stream.isPending}
                      streaming
                      showSteps={showSteps}
                      exportOn={exportOn}
                      voiceOn={voiceOutputOn}
                      onNavigate={onNavigate}
                      onFork={forkMessage}
                    onCopyLink={copyMessageLink}
                      {...bubbleCallbacks}
                    />
                  )}
                </div>
              )}
            </div>
          </div>

          {scrolledUp && (
            <button
              type="button"
              aria-label={tr("chat.scrollLatest")}
              onClick={scrollNow}
              className="absolute bottom-3 left-1/2 z-10 flex h-9 w-9 -translate-x-1/2 items-center justify-center rounded-full border border-border bg-card text-foreground/70 shadow-lift transition-colors hover:text-foreground"
            >
              <ArrowDown className="h-4 w-4" />
            </button>
          )}
        </div>

        <ChatInput
          input={input}
          onInputChange={setInput}
          busy={stream.isPending}
          listening={listening}
          voiceOn={voiceOn}
          webSearch={webSearch}
          onToggleWebSearch={() => setWebSearch((v) => !v)}
          llmConfigured={!!bootstrap?.health?.llm_configured}
          inputRef={inputRef}
          onToggleVoice={stableToggleVoice}
          onSend={stableSendInput}
          onStop={stableStop}
          onOpenSettings={onOpenSettings}
          attachments={attachments}
          onAddAttachment={(f) => uploadAttachment(f).then(() => void store.bump())}
          onRemoveAttachment={removeAttachment}
          onOpenAttachment={requestOpenAttachment}
          onSlashCommand={(id) => {
            if (id === "new-session") onNewSession();
            else onNavigate(id.replace(/^go-/, ""));
          }}
          modelName={bootstrap?.health?.model}
          modelCatalog={bootstrap?.model_catalog}
          enabledModels={bootstrap?.enabled_models}
          onSwitchModel={async (base, model) => {
            try {
              await api("/api/settings", {
                method: "PUT",
                body: JSON.stringify({ settings: { ai_base_url: base, ai_model: model } }),
              });
              await refreshBootstrap();
            } catch {
              /* 切换失败保持现状 */
            }
          }}
        />
      </div>
    </div>
  );
}

export type { AgentToolStep, ChatMessage, StepInfo, AgentPlanStep };

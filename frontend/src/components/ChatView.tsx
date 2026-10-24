import { useRef } from "react";
import { ArrowDown, BarChart3, Clock3, CreditCard, Sparkles, Wallet, type LucideIcon } from "lucide-react";
import { useBootstrap, useDashboard, store } from "@/lib/store";
import { useI18n } from "@/lib/i18n";
import { api } from "@/lib/api";
import type { AgentToolStep, AgentPlanStep } from "@/lib/types";
import type { ChatMessage, StepInfo } from "@/components/ChatMessageBubble";
import { ChatInput } from "@/components/ChatInput";
import { ChatMessageBubble } from "@/components/ChatMessageBubble";
import { FinishedMessages } from "@/components/FinishedMessages";
import { useChatView } from "@/components/chat-view-state";

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
}: {
  threadId: string;
  locateRunId?: number | null;
  onLocateDone?: () => void;
  onNewSession: () => void;
  onOpenSettings: () => void;
  onNavigate: (tab: string) => void;
}) {
  const { t: tr } = useI18n();
  const { bootstrap } = useBootstrap();
  const { dashboard } = useDashboard();
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const {
    messages, input, setInput, attachments,
    showSteps, exportOn, scrolledUp, handleListScroll,
    voiceOn, suggestions, hasData,
    stream, streamingMsg, finishedMessages,
    bubbleCallbacks, listening, scrollNow,
    stableSend, stableSendInput, stableStop, stableToggleVoice,
    uploadAttachment, removeAttachment, refreshBootstrap,
  } = useChatView({ threadId, locateRunId, onLocateDone, inputRef, listRef });

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
                  <span className="ml-auto inline-flex items-center gap-1">
                    <Clock3 className="h-3 w-3" />
                    {tr("chat.ctxUpdated", { t: updatedLabel })}
                  </span>
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
                    onNavigate={onNavigate}
                    {...bubbleCallbacks}
                  />
                  {streamingMsg && (
                    <ChatMessageBubble
                      message={streamingMsg}
                      busy={stream.isPending}
                      streaming
                      showSteps={showSteps}
                      exportOn={exportOn}
                      onNavigate={onNavigate}
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
          llmConfigured={!!bootstrap?.health?.llm_configured}
          inputRef={inputRef}
          onToggleVoice={stableToggleVoice}
          onSend={stableSendInput}
          onStop={stableStop}
          onOpenSettings={onOpenSettings}
          attachments={attachments}
          onAddAttachment={(f) => uploadAttachment(f).then(() => void store.bump())}
          onRemoveAttachment={removeAttachment}
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

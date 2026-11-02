import { memo, useState } from "react";
import { ChatMessageBubble, type ChatMessage } from "./ChatMessageBubble";
import { useI18n } from "@/lib/i18n";

export interface FinishedMessagesProps {
  /** messages with the streaming item excluded */
  messages: ChatMessage[];
  busy: boolean;
  showSteps: boolean;
  exportOn: boolean;
  voiceOn?: boolean;
  onToggleSteps: () => void;
  onNavigate: (tab: string) => void;
  onRegenerate: (msg: ChatMessage) => void;
  onExport: (msg: ChatMessage, action: "copy" | "download") => void;
  onDecidePending: (msg: ChatMessage, decision: "confirm" | "cancel") => void;
}

/** 默认窗口大小：只渲染最近 WINDOW 条，更早的按需展开（DOM 有界，长会话不掉帧） */
const WINDOW = 30;
const WINDOW_STEP = 50;

/**
 * FinishedMessages：已完成消息整体块。
 *
 * 窗口化渲染：历史很长时只挂载最近 WINDOW 条（Markdown 解析 + 语法高亮成本高，
 * 全量 map 在几百条后滚动明显卡顿），顶部提供「查看更早的 N 条」逐步展开。
 *
 * 自定义 areEqual：仅当 messages 内容引用变化（增删消息 / 某条消息被 patch）
 * 或低频共享状态（busy / showSteps / exportOn / onNavigate）变化时重渲染；
 * 流式 token 期间只有被排除的 streamingId 那条消息在变，本块引用不变 → 跳过。
 */
const FINISHED_ARE_EQUAL = (prev: FinishedMessagesProps, next: FinishedMessagesProps): boolean => {
  if (prev.messages.length !== next.messages.length) return false;
  for (let i = 0; i < prev.messages.length; i++) {
    if (prev.messages[i] !== next.messages[i]) return false;
  }
  return (
    prev.busy === next.busy &&
    prev.showSteps === next.showSteps &&
    prev.exportOn === next.exportOn &&
    prev.voiceOn === next.voiceOn &&
    prev.onNavigate === next.onNavigate
  );
};

function EarlierGate({ hidden, onExpand }: { hidden: number; onExpand: () => void }) {
  const { t } = useI18n();
  return (
    <div className="flex justify-center py-2">
      <button
        type="button"
        onClick={onExpand}
        className="rounded-full border border-border bg-card px-3 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
      >
        {t("chat.showEarlier", { n: hidden })}
      </button>
    </div>
  );
}

export const FinishedMessages = memo(
  ({ messages, busy, showSteps, exportOn, voiceOn = false, onToggleSteps, onNavigate, onRegenerate, onExport, onDecidePending }: FinishedMessagesProps) => {
    const [visibleCount, setVisibleCount] = useState(WINDOW);
    const hidden = Math.max(0, messages.length - visibleCount);
    const shown = hidden > 0 ? messages.slice(hidden) : messages;
    return (
      <>
        {hidden > 0 && (
          <EarlierGate hidden={hidden} onExpand={() => setVisibleCount((c) => c + WINDOW_STEP)} />
        )}
        {shown.map((m) => (
          <div key={m.id} data-run-id={m.runId}>
            <ChatMessageBubble
              message={m}
              busy={busy}
              showSteps={showSteps}
              exportOn={exportOn}
              voiceOn={voiceOn}
              onToggleSteps={onToggleSteps}
              onNavigate={onNavigate}
              onRegenerate={onRegenerate}
              onExport={onExport}
              onDecidePending={onDecidePending}
            />
          </div>
        ))}
      </>
    );
  },
  FINISHED_ARE_EQUAL,
);

FinishedMessages.displayName = "FinishedMessages";

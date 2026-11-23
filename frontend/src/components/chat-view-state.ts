import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, apiStream, deleteAttachment, saveBlob, uploadAttachment } from "@/lib/api";
import { useStreamingMutate } from "@/lib/use-streaming-mutate";
import { store, useDashboard, useBootstrap, useSessionUsage } from "@/lib/store";
import { BRAND } from "@/lib/brand";
import { copyText } from "@/lib/clipboard";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import type { AgentToolStep, AgentPlanStep, RunAttachment } from "@/lib/types";
import type { ChatMessage, StepInfo } from "@/components/ChatMessageBubble";
import {
  useChatHistory,
  useAutoFocus,
  useThrottledScroll,
  useVoiceInput,
  useSuggestions,
  nextMsgId,
  streamEventPatch,
  buildExportMd,
  runDecidePending,
} from "@/components/chat-view-hooks";

/**
 * ChatView 的全部逻辑：消息列表 / 流式问答 / HITL / 历史定位 / 导出 / 稳定回调。
 * 组件本身只剩 JSX 渲染层，所有状态与行为都由本 hook 持有并暴露。
 */
export function useChatView({
  threadId,
  locateRunId,
  onLocateDone,
  inputRef,
  listRef,
}: {
  threadId: string;
  locateRunId?: number | null;
  onLocateDone?: () => void;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  listRef: React.RefObject<HTMLDivElement | null>;
}) {
  const { dashboard } = useDashboard();
  const { bootstrap } = useBootstrap();
  const { toast } = useToast();
  const { t: tr } = useI18n();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<RunAttachment[]>([]);
  const [showSteps, setShowSteps] = useState(false);
  // 联网搜索开关：只在用户显式开启时走外网，默认关（隐私优先）
  const [webSearch, setWebSearch] = useState(false)
  // 深度研究 / 回答长度：只影响本轮生成，按浏览器记住，不写进设置页
  const [deepResearch, setDeepResearchState] = useState<boolean>(() => {
    try { return localStorage.getItem("mh.deepResearch") === "1"; } catch { return false; }
  })
  const [answerMode, setAnswerModeState] = useState<"concise" | "standard" | "detailed">(() => {
    try {
      const v = localStorage.getItem("mh.answerMode");
      return v === "concise" || v === "detailed" ? v : "standard";
    } catch { return "standard"; }
  })
  const setDeepResearch = (v: boolean) => {
    setDeepResearchState(v);
    try { localStorage.setItem("mh.deepResearch", v ? "1" : "0"); } catch { /* 隐私模式忽略 */ }
  }
  const setAnswerMode = (v: "concise" | "standard" | "detailed") => {
    setAnswerModeState(v);
    try { localStorage.setItem("mh.answerMode", v); } catch { /* 隐私模式忽略 */ }
  };
  const [showSessions, setShowSessions] = useState(false);
  const [sessionSearch, setSessionSearch] = useState("");

  const settings = bootstrap?.settings ?? {};
  const voiceOn = settings.voice_input === "on";
  const voiceOutputOn = settings.voice_output === "on";
  const exportOn = settings.show_export === "on";
  const suggestionsOn = settings.show_suggestions === "on";

  const patchMsg = (id: number, patch: Partial<ChatMessage>) =>
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...patch } : m)));

  const stream = useStreamingMutate<{
    question: string;
    thread_id: string;
    regenerate: boolean;
    lang: string;
    attachments: string[];
    web_search: boolean;
    deep_research: boolean;
    answer_mode: "concise" | "standard" | "detailed";
  }>({
    run: (payload, onEvent, signal) =>
      apiStream("/api/ask", { ...payload, thread_id: threadId }, onEvent, signal),
    onSettled: (_payload, _aborted, err) => {
      // 首条消息发出后会话才真正落库（标题也会被首个问题覆盖），此时刷新侧栏
      void store.refreshSessions();
      if (err) {
        setMessages((prev) => {
          const out = [...prev];
          for (let i = out.length - 1; i >= 0; i--) {
            if (out[i].role === "assistant") {
              out[i] = { ...out[i], error: (err as Error).message };
              break;
            }
          }
          return out;
        });
      }
    },
  });
  const streamRef = useRef(stream);
  streamRef.current = stream;

  const { scrollNow, scrollSoon } = useThrottledScroll(listRef);

  // 上滚检测
  const [scrolledUp, setScrolledUp] = useState(false);
  const handleListScroll = useCallback(() => {
    const el = listRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    setScrolledUp(!nearBottom);
  }, [listRef]);

  useChatHistory({ threadId, bootstrap, setMessages, setShowSteps, listRef, abort: stream.stop });
  useAutoFocus(inputRef, threadId);
  // harness：会话 token 用量（轮次变化时由 queryKey/staleTime 触发刷新）
  const { usage } = useSessionUsage(threadId);

  // 历史跳转定位
  const locatedRef = useRef(false);
  useEffect(() => {
    if (!locateRunId) {
      locatedRef.current = false;
      return;
    }
    if (messages.length === 0) return;
    const el = listRef.current?.querySelector(`[data-run-id="${locateRunId}"]`) as HTMLElement | null;
    if (!el || locatedRef.current) return;
    locatedRef.current = true;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("locate-flash");
    const timer = window.setTimeout(() => el.classList.remove("locate-flash"), 1800);
    onLocateDone?.();
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages, locateRunId]);

  const send = async (
    text: string,
    opts?: { regenerate?: boolean; attachments?: RunAttachment[] },
  ) => {
    const q = text.trim();
    if (!q || stream.isPending) return;
    const regen = opts?.regenerate ?? false;
    const sentAttachments = (opts?.attachments ?? attachments).map((a) => ({ ...a }));
    if (!regen) setInput("");

    let asstMsg: ChatMessage;
    if (regen) {
      asstMsg = { id: nextMsgId(), role: "assistant", text: "", q, steps: [], tools: [] };
      setMessages((prev) => {
        const out = [...prev];
        for (let i = out.length - 1; i >= 0; i--) {
          if (out[i].role === "assistant") {
            out[i] = asstMsg;
            break;
          }
        }
        return out;
      });
    } else {
      const userMsg: ChatMessage = {
        id: nextMsgId(),
        role: "user",
        text: q,
        steps: [],
        tools: [],
        attachments: sentAttachments,
      };
      asstMsg = { id: nextMsgId(), role: "assistant", text: "", q, steps: [], tools: [] };
      setMessages((prev) => [...prev, userMsg, asstMsg]);
    }
    scrollNow();

    const acc = {
      text: "",
      steps: [] as StepInfo[],
      tools: [] as AgentToolStep[],
      plan: undefined as { steps: AgentPlanStep[]; mode: string; route: string } | undefined,
      thinking: [] as string[],
      agentStatus: undefined as "running" | "done" | undefined,
      cards: [] as { kind: string; data: Record<string, unknown> }[],
    };
    let cleared = false;
    stream.mutate({
      payload: {
        question: q,
        thread_id: threadId,
        regenerate: regen,
        lang: tr("chat.locale"),
        attachments: sentAttachments.map((a) => String(a.id)),
        web_search: webSearch,
        deep_research: deepResearch,
        answer_mode: answerMode,
      },
      onEvent: (ev: Record<string, unknown>) => {
        if (!cleared) {
          setAttachments([]);
          cleared = true;
        }
        const patch = streamEventPatch(acc, ev);
        if (patch) patchMsg(asstMsg.id, patch);
        scrollSoon();
      },
    });
    // 网络错误或 stream.mutate 本身抛异常时立即清空，用户可直接重试
    if (!cleared) setAttachments([]);
  };

  const { listening, toggleVoice } = useVoiceInput(setInput);
  const suggestions = useSuggestions(dashboard, suggestionsOn);
  const hasData =
    (dashboard?.positions.length ?? 0) > 0 || (dashboard?.transactions.length ?? 0) > 0;

  const exportAnswer = async (m: ChatMessage, action: "copy" | "download") => {
    const md = buildExportMd(m, tr);
    try {
      if (action === "copy") {
        if (!copyText(md)) throw new Error("clipboard unavailable");
        toast(tr("chat.copied"), "ok");
      } else {
        saveBlob(
          new Blob([md], { type: "text/markdown;charset=utf-8" }),
          `${BRAND.name}-${new Date().toISOString().slice(0, 10)}.md`,
        );
        toast(tr("chat.downloaded"), "ok");
      }
    } catch {
      toast(tr("chat.exportFail"), "error");
    }
  };

  const decidePending = async (m: ChatMessage, decision: "confirm" | "cancel") => {
    const { reply } = await runDecidePending(m, decision, patchMsg, scrollNow);
    if (reply) setMessages((prev) => [...prev, reply]);
  };

  /** 编辑用户消息并重发：先截断该轮及之后的历史，再用新问题重新提问。 */
  const editAndResend = async (m: ChatMessage, text: string, runId: number) => {
    const q = text.trim();
    if (!q || stream.isPending) return;
    try {
      await api("/api/history/truncate", {
        method: "POST",
        body: JSON.stringify({ thread_id: threadId, run_id: runId }),
      });
    } catch {
      toast(tr("chat.editFailed"), "error");
      return;
    }
    setMessages((prev) => {
      const idx = prev.findIndex((x) => x.id === m.id);
      return idx >= 0 ? prev.slice(0, idx) : prev;
    });
    await sendRef.current(q, { attachments: m.attachments ?? [] });
  };

  // 稳定化回调
  const sendRef = useRef(send); sendRef.current = send;
  const exportRef = useRef(exportAnswer); exportRef.current = exportAnswer;
  const decideRef = useRef(decidePending); decideRef.current = decidePending;
  const toggleVoiceRef = useRef(toggleVoice); toggleVoiceRef.current = toggleVoice;
  const toggleStepsRef = useRef(() => setShowSteps((v) => !v));
  toggleStepsRef.current = () => setShowSteps((v) => !v);
  const toggleSessionsRef = useRef(() => setShowSessions((v) => !v));
  toggleSessionsRef.current = () => setShowSessions((v) => !v);
  const closeSessionsRef = useRef(() => setShowSessions(false));
  closeSessionsRef.current = () => setShowSessions(false);
  const liveInput = useRef(""); liveInput.current = input;
  const stopRef = useRef(stream.stop); stopRef.current = stream.stop;

  const stableSend = useCallback(
    (text: string, opts?: { regenerate?: boolean; attachments?: RunAttachment[] }) =>
      sendRef.current(text, opts),
    [],
  );
  const editRef = useRef(editAndResend); editRef.current = editAndResend;
  const stableEdit = useCallback(
    (m: ChatMessage, text: string, runId: number) => editRef.current(m, text, runId),
    [],
  );
  const stableRegenerate = useCallback(
    (m: ChatMessage) => {
      if (streamRef.current.isPending) return;
      void sendRef.current(m.q ?? "", { regenerate: true });
    },
    [],
  );
  const stableExport = useCallback(
    (m: ChatMessage, action: "copy" | "download") => exportRef.current(m, action),
    [],
  );
  const stableDecide = useCallback(
    (m: ChatMessage, decision: "confirm" | "cancel") => decideRef.current(m, decision),
    [],
  );
  const stableToggleVoice = useCallback(() => toggleVoiceRef.current(), []);
  const stableToggleSteps = useCallback(() => toggleStepsRef.current(), []);
  const stableToggleSessions = useCallback(() => toggleSessionsRef.current(), []);
  const stableCloseSessions = useCallback(() => closeSessionsRef.current(), []);
  const stableSendInput = useCallback(() => void sendRef.current(liveInput.current), []);
  const stableStop = useCallback(() => stopRef.current(), []);

  const lastMsg = messages.length > 0 ? messages[messages.length - 1] : null;
  const streamingId: number | null =
    stream.isPending && lastMsg && lastMsg.role === "assistant" ? lastMsg.id : null;

  const finishedMessages = useMemo(
    () => (streamingId != null ? messages.filter((m) => m.id !== streamingId) : messages),
    [messages, streamingId],
  );
  const streamingMsg = streamingId != null ? lastMsg : null;

  const panelMsg: ChatMessage | null =
    streamingMsg ??
    (() => {
      for (let i = messages.length - 1; i >= 0; i--) {
        const m = messages[i];
        if (m.role === "assistant" && (m.plan || (m.tools && m.tools.length > 0))) return m;
      }
      return null;
    })();

  const bubbleCallbacks = useMemo(
    () => ({
      onToggleSteps: stableToggleSteps,
      onRegenerate: stableRegenerate,
      onExport: stableExport,
      onDecidePending: stableDecide,
    }),
    [stableToggleSteps, stableRegenerate, stableExport, stableDecide],
  );

  return {
    // state
    messages, setMessages, input, setInput, attachments, setAttachments,
    webSearch, setWebSearch,
    deepResearch, setDeepResearch, answerMode, setAnswerMode,
    showSteps, showSessions, sessionSearch, setSessionSearch,
    scrolledUp, handleListScroll,
    // derived
    settings, voiceOn, voiceOutputOn, exportOn, suggestions, hasData,
    // harness：会话 token 用量（轮次变化后重新拉取，失败静默）
    usage,
    // stream
    stream, streamingMsg, finishedMessages, panelMsg,
    // callbacks
    send, stableSend, stableEdit, stableRegenerate, stableExport, stableDecide,
    stableToggleVoice, stableToggleSteps, stableToggleSessions,
    stableCloseSessions, stableSendInput, stableStop,
    bubbleCallbacks, listening, scrollNow,
    // helpers
    uploadAttachment: async (f: File) => {
      const r = await uploadAttachment(f);
      setAttachments((prev) => [...prev, { id: r.id, filename: f.name, kind: r.kind ?? "text", mime: r.mime }]);
      return r;
    },
    referenceAttachment: (a: RunAttachment) => {
      setAttachments((prev) => (prev.some((p) => p.id === a.id) ? prev : [...prev, { ...a, ref: true }]));
    },
    removeAttachment: (id: number) => {
      const target = attachments.find((a) => a.id === id);
      setAttachments((prev) => prev.filter((a) => a.id !== id));
      // 工作台已有文件只是「引用」，从输入区移除不能把用户的文件删掉。
      if (!target?.ref) void deleteAttachment(id);
    },
    refreshBootstrap: () => store.refreshBootstrap(),
  };
}

import { useCallback, useEffect, useRef, useState } from "react";
import { api, confirmAction } from "@/lib/api";
import { BRAND } from "@/lib/brand";
import { store } from "@/lib/store";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import type { RunRecord, BootstrapData, DashboardData, AgentToolStep, AgentPlanStep, AnswerMeta } from "@/lib/types";
import type { ChatMessage, StepInfo } from "@/components/ChatMessageBubble";
import { errMsg } from "@/lib/utils";

let msgSeq = 1;
const nextMsgId = () => msgSeq++;
export { nextMsgId };

/** 把历史 RunRecord 映射为 ChatMessage 对（user + assistant）；ID 走共享 msgSeq */
export function mapRunsToMessages(runs: RunRecord[]): ChatMessage[] {
  return runs.slice().reverse().flatMap((r) => [
    {
      id: nextMsgId(),
      role: "user" as const,
      text: r.question,
      steps: [],
      tools: [],
      attachments: r.attachments ?? [],
    },
    {
      id: nextMsgId(),
      role: "assistant" as const,
      text: r.answer,
      q: r.question,
      steps: [],
      tools: [],
      runId: r.id,
      // 来源随回答落库（route/llm/route_reason）：有就显示真实来源，
      // 来源随回答落库（route/llm/route_reason）：有就显示真实来源，
      // 旧记录或空值一律留空 —— 拿不到就不说，不猜。
      meta: {
        answer: r.answer,
        level: r.level,
        route: r.route ?? "",
        route_reason: r.route_reason ?? "",
        metrics: {},
        flags: r.flags,
        llm: (r.llm || undefined) as "llm" | "template" | undefined,
        tools: r.tools ?? [],
      },
      actions: r.actions ?? [],
      sources: r.sources ?? [],
      feedbackRating: r.feedback_rating ?? 0,
      feedbackReason: r.feedback_reason ?? "",
      created_at: r.created_at,
    },
  ]);
}

interface UseChatHistoryArgs {
  threadId: string;
  bootstrap: BootstrapData | null | undefined;
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  setShowSteps: React.Dispatch<React.SetStateAction<boolean>>;
  listRef: React.RefObject<HTMLDivElement | null>;
  abort: () => void;
}

/** 切换会话：加载该 thread 的历史问答；组件卸载/切会话时 abort 流式请求 */
export function useChatHistory({
  threadId,
  bootstrap,
  setMessages,
  setShowSteps,
  listRef,
  abort,
}: UseChatHistoryArgs) {
  // "展开过程"偏好：bootstrap 异步加载，独立 effect 监听其变化，避免首个会话不生效
  useEffect(() => {
    if (bootstrap) setShowSteps(bootstrap.settings.expand_process === "on");
  }, [bootstrap, setShowSteps]);

  useEffect(() => {
    let alive = true;
    const thisThread = threadId;
    setMessages([]);
    // 乐观 tmp 线程（会话尚未创建完成）不发历史请求：没有可加载的历史
    if (!threadId.startsWith("__tmp_")) {
      api<{ runs: RunRecord[] }>(`/api/history?thread_id=${encodeURIComponent(threadId)}&limit=50`)
        .then((d) => {
          // 竞态守卫：切会话时 alive=false 或 thisThread 已不匹配 → 丢弃旧响应
          if (!alive || thisThread !== threadId) return;
          const loaded = mapRunsToMessages(d.runs ?? []);
          // 合并而非整体替换：若历史请求返回前用户已发送提问（乐观消息），
          // 保留这些比历史更新的本地消息，避免被历史覆盖导致刚发的消息"消失"。
          setMessages((prev) => {
            if (prev.length === 0) return loaded;
            // 本地乐观消息：用户提问后、历史返回前 push 的用户+助手消息（无 runId）。
            const optimistic = prev.filter((m) => m.runId == null);
            if (optimistic.length === 0) return loaded;
            // 去重：若乐观消息的问题已在历史 DB 中（有 runId），保留历史版本
            const loadedQuestions = new Set(loaded.filter((m) => m.q).map((m) => m.q));
            const deduped = optimistic.filter((om) => !loadedQuestions.has(om.q));
            return [...loaded, ...deduped];
          });
          requestAnimationFrame(() =>
            listRef.current?.scrollTo({ top: listRef.current.scrollHeight }),
          );
        })
        .catch(() => {
          /* 历史加载失败不影响提问 */
        });
    }
    return () => {
      alive = false;
      abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId]);
}

/** 桌面端自动聚焦输入框：打开 / 切换会话后即可直接打字（移动端不弹键盘） */
export function useAutoFocus(inputRef: React.RefObject<HTMLTextAreaElement | null>, threadId: string) {
  useEffect(() => {
    if (window.matchMedia("(min-width: 768px)").matches) {
      inputRef.current?.focus();
    }
  }, [threadId, inputRef]);
}

interface ThrottledScroll {
  /** 立即滚到底（发送/切换会话时用） */
  scrollNow: () => void;
  /** 流式 token 期间攒着，100ms 只滚一次；滚到最底部才自动跟随 */
  scrollSoon: () => void;
}

/** 流式渲染节流：每个 token 都 smooth-scroll 会明显卡顿，攒到 100ms 批量滚一次 */
export function useThrottledScroll(listRef: React.RefObject<HTMLDivElement | null>): ThrottledScroll {
  const scrollTimer = useRef<number | null>(null);
  const pendingScroll = useRef(false);

  useEffect(() => () => {
    if (scrollTimer.current != null) window.clearTimeout(scrollTimer.current);
  }, []);

  return {
    scrollNow() {
      requestAnimationFrame(() => {
        listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
      });
    },
    scrollSoon() {
      pendingScroll.current = true;
      if (scrollTimer.current == null) {
        scrollTimer.current = window.setTimeout(() => {
          scrollTimer.current = null;
          if (!pendingScroll.current) return;
          pendingScroll.current = false;
          const el = listRef.current;
          if (!el) return;
          const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
          if (nearBottom) el.scrollTo({ top: el.scrollHeight });
        }, 100);
      }
    },
  };
}

export function useVoiceInput(setInput: React.Dispatch<React.SetStateAction<string>>) {
  const { toast } = useToast();
  // 识别语言跟随界面语言（此前硬编码 zh-CN：英文界面也会用中文识别）
  const { t: tr, lang } = useI18n();
  const [listening, setListening] = useState(false);
  const listeningRef = useRef(false);
  const recogRef = useRef<{ stop: () => void } | null>(null);

  const markListening = (v: boolean) => {
    listeningRef.current = v;
    setListening(v);
  };

  const doToggle = () => {
    const w = window as unknown as Record<string, unknown>;
    const SR = w.SpeechRecognition ?? w.webkitSpeechRecognition;
    if (!SR) {
      toast(tr("chat.voiceUnsupported"), "info");
      return;
    }
    if (listeningRef.current) {
      recogRef.current?.stop();
      markListening(false);
      return;
    }
    try {
      const rec = new (SR as new () => {
        lang: string;
        interimResults: boolean;
        onresult: ((e: unknown) => void) | null;
        onend: (() => void) | null;
        onerror: (() => void) | null;
        start: () => void;
        stop: () => void;
      })();
      rec.lang = lang === "en" ? "en-US" : "zh-CN";
      rec.interimResults = false;
      rec.onresult = (e: unknown) => {
        const ev = e as { results: ArrayLike<ArrayLike<{ transcript: string }>> };
        const t = ev.results[0]?.[0]?.transcript ?? "";
        if (t) setInput((v) => (v ? `${v}${t}` : t));
      };
      rec.onend = () => markListening(false);
      rec.onerror = () => markListening(false);
      recogRef.current = rec;
      rec.start();
      markListening(true);
      toast(tr("chat.voiceListening"), "info");
    } catch {
      markListening(false);
      toast(tr("chat.voiceFail"), "error");
    }
  };

  const doToggleRef = useRef(doToggle);
  doToggleRef.current = doToggle;
  const toggleVoice = useCallback(() => doToggleRef.current(), []);

  // 卸载清理：组件在语音识别进行中被卸载时停止监听，释放麦克风
  useEffect(() => {
    return () => {
      if (listeningRef.current) {
        recogRef.current?.stop();
        listeningRef.current = false;
      }
    };
  }, []);

  return { listening, toggleVoice };
}

/** 空态 / 有数据时的建议 chips（有数据才给，贴合当前仪表盘风险项） */
export function useSuggestions(
  dashboard: DashboardData | null,
  suggestionsOn: boolean,
): string[] {
  const hasData =
    (dashboard?.positions.length ?? 0) > 0 || (dashboard?.transactions.length ?? 0) > 0;
  if (!suggestionsOn || !hasData) return [];
  return [
    ...dynamicSuggestions(dashboard?.flags ?? []),
    ...BASE_SUGGESTION_KEYS,
  ].slice(0, 6);
}

const BASE_SUGGESTION_KEYS = [
  "chat.sHealth",
  "chat.sSpend",
  "chat.sRisk",
  "chat.sPnl",
];

function dynamicSuggestions(flags: RunRecord["flags"]): string[] {
  const map: Record<string, string> = {
    CONCENTRATION: "chat.qConcentration",
    HIGH_RATE_DEBT: "chat.qHighRateDebt",
    SAVINGS_RATE: "chat.qSavingsRate",
    EMERGENCY_FUND: "chat.qEmergencyFund",
    DTI: "chat.qDti",
  };
  return flags.slice(0, 2).filter((f) => map[f.code]).map((f) => map[f.code]);
}

/** SSE 流式事件 → 消息增量 patch 的分发逻辑（每个 token 触发一次） */
export function streamEventPatch(
  acc: {
    text: string;
    steps: StepInfo[];
    tools: AgentToolStep[];
    plan?: { steps: AgentPlanStep[]; mode: string; route: string };
    thinking: string[];
    agentStatus?: "running" | "done";
    cards?: { kind: string; data: Record<string, unknown> }[];
  },
  ev: Record<string, unknown>,
): Partial<ChatMessage> | null {
  // 兜底：老测试/老调用方可能不传 cards
  if (!acc.cards) acc.cards = [];
  switch (String(ev.type)) {
    case "card": {
      // 结构化数据卡：后端推 {kind, data}，前端渲染成对话内嵌小卡
      const block = (ev.block ?? ev.data ?? {}) as { kind: string; data: Record<string, unknown> };
      acc.cards.push({ kind: String(block.kind ?? "unknown"), data: block.data ?? {} });
      return { cards: [...acc.cards] };
    }
    case "token":
      // 流式 token（agent 模式最终回答逐字输出）：ev.data.content
      acc.text += String((ev.data as { content?: string })?.content ?? ev.delta ?? "");
      return { text: acc.text };
    case "text":
      // 兼容旧事件：确定性路径用的完整片段
      acc.text += String(ev.delta ?? "");
      return { text: acc.text };
    case "plan":
      acc.plan = {
        steps: (ev.data as { steps?: AgentPlanStep[] })?.steps ?? [],
        mode: String((ev.data as { mode?: string })?.mode ?? "deterministic") as
          | "agent"
          | "deterministic",
        route: String((ev.data as { route?: string })?.route ?? ""),
      };
      return { plan: acc.plan };
    case "thinking":
      acc.thinking = [...acc.thinking, String((ev.data as { content?: string })?.content ?? "")];
      return { thinking: acc.thinking };
    case "tool": {
      const d = (ev.data ?? {}) as {
        id?: string;
        name?: string;
        status?: string;
        summary?: string;
        duration_ms?: number;
        args?: Record<string, unknown>;
      };
      const name = String(d.name ?? "");
      const status = String(d.status ?? "done") as AgentToolStep["status"];
      const key = d.id || name;
      const next = [...acc.tools];
      const idx = next.findIndex((t) => (t.id || t.name) === key);
      if (idx >= 0) {
        next[idx] = {
          ...next[idx],
          status,
          summary: d.summary ?? next[idx].summary,
          duration_ms: d.duration_ms ?? next[idx].duration_ms,
        };
      } else {
        next.push({
          name,
          args: d.args ?? {},
          summary: d.summary ?? "",
          status,
          duration_ms: d.duration_ms,
          id: d.id,
        });
      }
      acc.tools = next;
      return { tools: next };
    }
    case "agent":
      acc.agentStatus = String((ev.data as { status?: string })?.status ?? "done") as
        | "running"
        | "done";
      return { agentStatus: acc.agentStatus };
    case "agent_step":
      acc.tools.push({
        name: String(ev.name),
        args: (ev.args as Record<string, unknown>) ?? {},
        summary: String(ev.summary ?? ""),
        status: "done",
      });
      return { tools: [...acc.tools] };
    case "step":
      if (ev.phase === "done") {
        acc.steps.push({ id: String(ev.id), label: String(ev.label), detail: String(ev.detail) });
        return { steps: [...acc.steps] };
      }
      return null;
    case "final":
      acc.text = String(ev.answer ?? acc.text);
      return {
        text: acc.text,
        meta: {
          answer: acc.text,
          level: String(ev.level ?? "L1 洞察"),
          route: String(ev.route ?? ""),
          route_reason: String(ev.route_reason ?? ""),
          metrics: (ev.metrics as Record<string, number>) ?? {},
          flags: (ev.flags as AnswerMeta["flags"]) ?? [],
          llm: (ev.llm as "llm" | "template") ?? "template",
          tools: (ev.tools as string[] | undefined) ?? [],
        },
        actions: (ev.actions as { tab: string }[] | undefined) ?? [],
        sources: (ev.sources as import("@/lib/types").AnswerSource[] | undefined) ?? [],
        runId: Number(ev.run_id) > 0 ? Number(ev.run_id) : undefined,
        pending:
          ev.pending_token
            ? { token: String(ev.pending_token), summary: String(ev.pending_summary ?? "") }
            : undefined,
      };
    case "error":
      return { error: String(ev.message) };
    default:
      return null;
  }
}

/** 把「问题 + 回答」导出为 Markdown（复制 / 下载） */
export function buildExportMd(
  m: ChatMessage,
  tr: (k: string, vars?: Record<string, string | number>) => string,
): string {
  return [
    `# ${BRAND.name} · Q&A Log`,
    ``,
    `**Q**: ${m.q ?? ""}`,
    ``,
    `**Time**: ${new Date().toLocaleString(tr("chat.locale") === "zh" ? "zh-CN" : "en-US")}`,
    ``,
    `---`,
    ``,
    m.text,
    ``,
    `---`,
    ``,
    `*${tr("chat.mdFooter", { name: BRAND.name })}*`,
  ].join("\n");
}

/** 写类动作 HITL 确认：token 一次性消费；409 = 已失效（过期/已执行/已取消）。
 *  返回值：true = 产生新回答（需追加 assistant 消息），false = 未产生 */
export async function runDecidePending(
  m: ChatMessage,
  decision: "confirm" | "cancel",
  patchMsg: (id: number, patch: Partial<ChatMessage>) => void,
  scrollNow: () => void,
): Promise<{ reply?: ChatMessage }> {
  if (!m.pending || m.pendingResult) return {};
  if (decision === "cancel") {
    patchMsg(m.id, { pendingResult: "cancelled" });
    return {};
  }
  try {
    const r = await confirmAction(m.pending.token, "confirm");
    patchMsg(m.id, { pendingResult: "executed" });
    if (r.answer) {
      const reply: ChatMessage = {
        id: nextMsgId(),
        role: "assistant",
        text: String(r.answer),
        q: m.q,
        steps: [],
        tools: [],
        created_at: new Date().toISOString(),
      };
      scrollNow();
      store.bump();
      return { reply };
    }
    scrollNow();
    store.bump();
    return {};
  } catch (err) {
    const msg = errMsg(err);
    if (/409|失效|过期|已执行|已取消/.test(msg)) {
      patchMsg(m.id, { pendingResult: "expired" });
    } else {
      patchMsg(m.id, { error: msg });
    }
    return {};
  }
}



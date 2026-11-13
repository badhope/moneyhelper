import { memo, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { PrismLight as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import javascript from "react-syntax-highlighter/dist/esm/languages/prism/javascript";
import typescript from "react-syntax-highlighter/dist/esm/languages/prism/typescript";
import jsx from "react-syntax-highlighter/dist/esm/languages/prism/jsx";
import tsx from "react-syntax-highlighter/dist/esm/languages/prism/tsx";
import python from "react-syntax-highlighter/dist/esm/languages/prism/python";
import bash from "react-syntax-highlighter/dist/esm/languages/prism/bash";
import json from "react-syntax-highlighter/dist/esm/languages/prism/json";
import sql from "react-syntax-highlighter/dist/esm/languages/prism/sql";
import yaml from "react-syntax-highlighter/dist/esm/languages/prism/yaml";
import {
  ChevronDown, ChevronUp, Copy, Download, Loader2, RotateCcw, Sparkles, Volume2, VolumeX, Wrench } from "lucide-react";
import { Button } from "@/components/ui/button";
import { copyText } from "@/lib/clipboard";
import { Badge } from "@/components/ui/badge";
import { SummaryBlock } from "@/components/SummaryBlock";
import { FinanceBlocks, type FinanceCardData } from "@/components/chat/FinanceBlocks";
import { BRAND, BrandLogo } from "@/lib/brand";
import { useI18n } from "@/lib/i18n";
import { useSpeech } from "@/lib/use-speech";
import { useTheme } from "@/lib/theme";
import type { AgentToolStep, AgentPlanStep, AnswerMeta } from "@/lib/types";

// 注册常用语言（PrismLight 按需，控制包体积）
SyntaxHighlighter.registerLanguage("javascript", javascript);
SyntaxHighlighter.registerLanguage("js", javascript);
SyntaxHighlighter.registerLanguage("typescript", typescript);
SyntaxHighlighter.registerLanguage("ts", typescript);
SyntaxHighlighter.registerLanguage("jsx", jsx);
SyntaxHighlighter.registerLanguage("tsx", tsx);
SyntaxHighlighter.registerLanguage("python", python);
SyntaxHighlighter.registerLanguage("bash", bash);
SyntaxHighlighter.registerLanguage("shell", bash);
SyntaxHighlighter.registerLanguage("json", json);
SyntaxHighlighter.registerLanguage("sql", sql);
SyntaxHighlighter.registerLanguage("yaml", yaml);
SyntaxHighlighter.registerLanguage("yml", yaml);

export interface StepInfo {
  id: string;
  label: string;
  detail: string;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  text: string;
  /** assistant 消息对应的提问（导出时用） */
  q?: string;
  meta?: AnswerMeta;
  steps: StepInfo[];
  /** agent 模式：模型调用过的工具（实时展示，含生命周期状态） */
  tools?: AgentToolStep[];
  /** 本轮 Agent 的规划步骤（计划卡 / 面板展示） */
  plan?: { steps: AgentPlanStep[]; mode: string; route: string };
  /** agent 模式：模型的中间思考片段 */
  thinking?: string[];
  /** agent 生命周期：running / done */
  agentStatus?: "running" | "done";
  /** 对话结果附带的跳转意图（对话中枢：结果一键去对应页面） */
  actions?: { tab: string }[];
  /** 写类动作待确认（HITL）：确认后调 /api/confirm 执行 */
  pending?: { token: string; summary: string };
  /** 确认结果：executed / cancelled / expired */
  pendingResult?: "executed" | "cancelled" | "expired";
  error?: string;
  created_at?: string;
  /** 对应后端 runs.id：历史跳转定位到本条时用 */
  runId?: number;
  /** 结构化数据卡：对话内嵌的可视化小卡（4宫格/mini环形/持仓预览） */
  cards?: { kind: string; data: Record<string, unknown> }[];
}

/** 工具名 → 用户能看懂的动作（工具名是内部契约，不出口） */
const TOOL_LABEL_KEYS: Record<string, string> = {
  get_market_view: "chat.toolMarket",
  get_ledger_view: "chat.toolLedger",
  get_risk_flags: "chat.toolRisk",
  get_budget: "chat.toolBudget",
  get_trend: "chat.toolTrend",
  record_transaction: "chat.toolRecord",
  get_kline: "chat.toolKline",
};

function toolLabel(tr: (k: string) => string, name: string): string {
  const k = TOOL_LABEL_KEYS[name];
  return k ? tr(k) : name;
}

/** agent 工具调用链：默认一行聚合，点击展开每步（含状态与耗时） */
function ToolSteps({ tools }: { tools: AgentToolStep[] }) {
  const { t: tr } = useI18n();
  const [open, setOpen] = useState(false);
  const running = tools.some((t) => t.status === "running");
  if (tools.length === 0) return null;
  return (
    <div className="mt-2.5">
      <button
        type="button"
        className="text-xs text-muted-foreground inline-flex items-center gap-1 hover:text-foreground"
        onClick={() => setOpen((v) => !v)}
      >
        {running ? (
          <Loader2 className="w-3 h-3 animate-spin" />
        ) : (
          <Wrench className="w-3 h-3" />
        )}
        {tr("summary.tools", { n: tools.length })}
        {open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
      </button>
      {open && (
        <div className="mt-1.5 space-y-1 border-l-2 border-primary/30 pl-2.5">
          {tools.map((t, i) => (
            <div key={i} className="flex items-start gap-1.5 text-xs text-muted-foreground">
              {t.status === "running" ? (
                <Loader2 className="w-3.5 h-3.5 shrink-0 text-primary mt-0.5 animate-spin" />
              ) : t.status === "error" ? (
                <span className="shrink-0 text-red-500 mt-0.5">✗</span>
              ) : (
                <span className="shrink-0 text-primary mt-0.5">✓</span>
              )}
              <span className="min-w-0">
                <b className="text-foreground/80">{toolLabel(tr, t.name)}</b>
                {t.summary ? <span className="ml-1">{t.summary}</span> : null}
                {t.duration_ms != null && (
                  <span className="ml-1 text-[11px] text-muted-foreground/70">{t.duration_ms}ms</span>
                )}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** 计划卡：Agent 本轮规划要做的步骤（chips），展示"它打算怎么干" */
function PlanCard({ plan }: { plan: NonNullable<ChatMessage["plan"]> }) {
  const { t: tr } = useI18n();
  if (!plan.steps.length) return null;
  return (
    <div className="mt-2.5 rounded-lg border border-border bg-card/40 px-3 py-2">
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Sparkles className="w-3 h-3 text-primary" />
        {tr("chat.planLabel")}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        {plan.steps.map((s, i) => (
          <span key={s.id} className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-2 py-0.5 text-[11px] text-foreground/80">
            <span className="text-primary">{i + 1}</span>
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}

/** 思考折叠：agent 模式模型的中间思路（collapsible）。
 *  running 时自动展开（实时看思路），结束后自动收起（对标 Claude 的思考节奏）；用户可手动展开/收起覆盖。 */
function Thinking({ items, running }: { items: string[]; running?: boolean }) {
  const { t: tr } = useI18n();
  const [open, setOpen] = useState(false);
  useEffect(() => {
    setOpen(Boolean(running));
  }, [running]);
  if (!items.length) return null;
  return (
    <div className="mt-2">
      <button
        type="button"
        className="text-xs text-muted-foreground inline-flex items-center gap-1 hover:text-foreground"
        onClick={() => setOpen((v) => !v)}
      >
        {tr("agent.thinking")}
        {open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
      </button>
      {open && (
        <div className="mt-1 space-y-1 border-l-2 border-border/70 pl-2.5 text-xs text-muted-foreground italic">
          {items.map((t, i) => (
            <div key={i}>{t}</div>
          ))}
        </div>
      )}
    </div>
  );
}

/** 对话结果的页面跳转意图 → 按钮文案 key。
 *  overview/holdings/market/ledger 是「功能」页内的子 tab（由 App 落 features 页对应子 tab）；
 *  settings 独立页；chat 留在对话。 */

/** 代码块高亮：PrismLight 按需语言 + 明暗主题自适应，带语言标签条与复制按钮。 */
function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const { resolved } = useTheme();
  const style = resolved === "dark" ? oneDark : oneLight;
  return (
    <div className="code-block relative my-3 overflow-hidden rounded-lg border border-border">
      {lang && (
        <div className="flex items-center justify-between border-b border-border bg-muted/40 px-3 py-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">
          <span>{lang}</span>
          <button
            type="button"
            aria-label="copy code"
            title="copy"
            onClick={() => copyText(code)}
            className="p-0.5 text-muted-foreground hover:text-foreground"
          >
            <Copy className="w-3 h-3" />
          </button>
        </div>
      )}
      <SyntaxHighlighter
        language={lang || "text"}
        style={style}
        customStyle={{ margin: 0, background: "transparent", padding: "0.75rem 1rem" }}
        codeTagProps={{ style: { fontFamily: "var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)", fontSize: "0.82rem" } }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}

/** 复用给 ReactMarkdown 的 components：代码块走 CodeBlock，行内代码保持原样。 */
const MD_COMPONENTS: Components = {
  // react-markdown 运行时传给 code 的 props 含非标准 inline 字段，类型缺省故用 any 收窄
  code({ className, children, ...props }: any) {
    const inline = Boolean((props as { inline?: boolean }).inline);
    const match = /language-(\w+)/.exec(className ?? "");
    const text = String(children ?? "").replace(/\n$/, "");
    if (inline || !match) {
      return (
        <code className={className} {...props}>
          {children}
        </code>
      );
    }
    return <CodeBlock lang={match[1]} code={text} />;
  },
};

const TAB_ACTION_KEYS: Record<string, string> = {
  overview: "chat.goOverview",
  holdings: "chat.goHoldings",
  market: "chat.goMarket",
  ledger: "chat.goLedger",
  settings: "chat.goSettings",
};

interface BubbleProps {
  message: ChatMessage;
  busy: boolean;
  /** 是否正在流式生成：末尾显示闪烁光标（对标 ChatGPT/Claude 的流式提示） */
  streaming?: boolean;
  showSteps: boolean;
  exportOn: boolean;
  voiceOn?: boolean;
  onToggleSteps: () => void;
  onNavigate: (tab: string) => void;
  onRegenerate: (msg: ChatMessage) => void;
  onExport: (msg: ChatMessage, action: "copy" | "download") => void;
  onDecidePending: (msg: ChatMessage, decision: "confirm" | "cancel") => void;
}

function BubbleInner({
  message: m,
  busy,
  streaming = false,
  showSteps,
  exportOn,
  voiceOn = false,
  onToggleSteps,
  onNavigate,
  onRegenerate,
  onExport,
  onDecidePending,
}: BubbleProps) {
  const { t: tr, lang } = useI18n();
  const speech = useSpeech();
  const spokenRef = useState<{ text: string }>({ text: "" })[0];
  useEffect(() => {
    if (!voiceOn || m.role !== "assistant" || streaming || !m.text) return;
    if (spokenRef.text === m.text) return;
    spokenRef.text = m.text;
    speech.speak(m.text, lang);
  }, [voiceOn, m.role, m.text, streaming, lang, spokenRef, speech]);
  const assistantName = lang === "en" ? BRAND.en : BRAND.name;

  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-3xl rounded-br-lg bg-muted px-4 py-2.5 text-[15.5px] leading-relaxed text-foreground whitespace-pre-wrap break-words">
          {m.text}
        </div>
      </div>
    );
  }

  return (
    <div className="group/msg flex gap-3">
      {/* 助手头像：品牌标记，尺寸克制，不抢正文 */}
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-border bg-card">
        <BrandLogo size={18} />
      </div>

      <div className="min-w-0 flex-1">
        {m.error && !m.text ? (
          <div className="text-sm text-red-600 dark:text-red-400">
            {tr("chat.error")}: {m.error}
          </div>
        ) : (
          <>
            <div className="mb-1 flex items-center gap-2 text-[12px] text-muted-foreground">
              <span className="font-medium text-foreground/80">{assistantName}</span>
              {m.meta?.llm === "template" && <Badge variant="muted">{tr("chat.badgeRule")}</Badge>}
              {m.agentStatus === "running" && (
                <span className="inline-flex items-center gap-1 text-primary">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  {tr("chat.badgeThinking")}
                </span>
              )}
            </div>

            {m.plan && <PlanCard plan={m.plan} />}
            {m.thinking && m.thinking.length > 0 && (
              <Thinking items={m.thinking} running={m.agentStatus === "running"} />
            )}

            {m.text === "" ? (
              <div className="flex items-center gap-2 py-1 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> {tr("chat.analyzing")}
              </div>
            ) : (
              <div className="md-body text-foreground">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  rehypePlugins={[
                    [
                      rehypeSanitize,
                      {
                        ...defaultSchema,
                        attributes: {
                          ...defaultSchema.attributes,
                          "*": [...(defaultSchema.attributes?.["*"] ?? []), "className"],
                        },
                      },
                    ],
                  ]}
                  components={MD_COMPONENTS}
                >
                  {m.text}
                </ReactMarkdown>
                {streaming && <span className="stream-caret" aria-hidden="true" />}
                {streaming && !m.text && (
                  <span className="thinking-dots" aria-label="思考中">
                    <span /><span /><span />
                  </span>
                )}
              </div>
            )}

            {m.error && m.text ? (
              <div className="mt-1.5 text-xs text-red-600 dark:text-red-400">
                {tr("chat.streamInterrupted")}: {m.error}
              </div>
            ) : null}

            {m.cards && m.cards.length > 0 && (
              <div className="mt-3 space-y-2">
                {m.cards.map((c, i) => (
                  <FinanceBlocks
                    key={i}
                    data={(c.data || {}) as FinanceCardData}
                    onNavigate={onNavigate}
                  />
                ))}
              </div>
            )}

            {m.meta && m.meta.route !== "general" && m.meta.route !== "nl_add" && (
              // 有富回答块时只用 compact：指标/风险已在块里，摘要不再重复同一组数字
              <SummaryBlock meta={m.meta} compact={Boolean(m.cards && m.cards.length > 0)} />
            )}

            {m.actions && m.actions.length > 0 && !(m.cards && m.cards.length > 0) && (
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                {m.actions.filter(Boolean).map((a, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => onNavigate(a.tab)}
                    className="rounded-full border border-border bg-background px-3 py-1.5 text-[12px] text-foreground/80 transition-colors hover:bg-accent hover:text-foreground"
                  >
                    {tr(TAB_ACTION_KEYS[a.tab] ?? "chat.goOverview")}
                  </button>
                ))}
              </div>
            )}

            {m.tools && m.tools.length > 0 && <ToolSteps tools={m.tools} />}

            {m.pending && (
              <div className="mt-3 rounded-2xl border border-amber-500/30 bg-amber-500/[0.06] p-3">
                <div className="flex items-center justify-between gap-2 text-xs">
                  <span className="font-medium text-amber-700 dark:text-amber-400">
                    {tr("chat.confirmTitle")}
                  </span>
                  <span className="text-amber-700/70 dark:text-amber-400/70">
                    {m.pendingResult
                      ? m.pendingResult === "executed"
                        ? tr("chat.confirmDone")
                        : m.pendingResult === "cancelled"
                          ? tr("chat.confirmCancelled")
                          : tr("chat.confirmExpired")
                      : tr("chat.confirmPending")}
                  </span>
                </div>
                <div className="mt-1 text-xs text-foreground/80">{m.pending.summary}</div>
                {!m.pendingResult && (
                  <div className="mt-2.5 flex gap-2">
                    <Button
                      size="sm"
                      variant="destructive"
                      className="h-8 rounded-full px-3.5 text-xs"
                      onClick={() => onDecidePending(m, "confirm")}
                    >
                      {tr("chat.confirmBtn")}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-8 rounded-full px-3.5 text-xs"
                      onClick={() => onDecidePending(m, "cancel")}
                    >
                      {tr("chat.cancelBtn")}
                    </Button>
                  </div>
                )}
                {m.pendingResult === "expired" && (
                  <div className="mt-1.5 text-[11px] text-amber-700 dark:text-amber-400">
                    {tr("chat.confirmExpired")}
                  </div>
                )}
              </div>
            )}

            {m.steps.length > 0 && (
              <div className="mt-2">
                <button
                  type="button"
                  className="inline-flex items-center gap-1 py-2 -my-1 text-xs text-muted-foreground hover:text-foreground"
                  onClick={onToggleSteps}
                >
                  {tr("chat.viewSteps")}
                  {showSteps ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                </button>
                {showSteps && (
                  <ul className="mt-2 space-y-1.5">
                    {m.steps.map((s, i) => (
                      <li key={i} className="flex gap-1.5 text-xs text-muted-foreground">
                        <span className="shrink-0 text-primary">✓</span>
                        <span>
                          <b className="text-foreground/80">{s.label}</b>
                          <span className="ml-1">{s.detail}</span>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {/* 操作条：对齐 ChatGPT——放在回答下方，默认半透明，悬停/聚焦变清晰 */}
            <div className="mt-1.5 flex items-center gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover/msg:opacity-100 max-sm:opacity-100">
              <button
                type="button"
                className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-40"
                aria-label={tr("chat.copyMd")}
                title={tr("chat.copyMd")}
                onClick={() => onExport(m, "copy")}
              >
                <Copy className="h-3.5 w-3.5" />
              </button>
              {speech.supported && (
                <button
                  type="button"
                  className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-40"
                  aria-label={tr("chat.speak")}
                  title={tr("chat.speak")}
                  disabled={busy}
                  onClick={() => speech.toggle(m.text, lang)}
                >
                  {speech.speaking ? <VolumeX className="h-3.5 w-3.5" /> : <Volume2 className="h-3.5 w-3.5" />}
                </button>
              )}
              <button
                type="button"
                className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-40"
                aria-label={tr("chat.regenerate")}
                title={tr("chat.regenerate")}
                disabled={busy}
                onClick={() => onRegenerate(m)}
              >
                <RotateCcw className="h-3.5 w-3.5" />
              </button>
              {exportOn && (
                <button
                  type="button"
                  className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                  aria-label={tr("chat.downloadMd")}
                  title={tr("chat.downloadMd")}
                  onClick={() => onExport(m, "download")}
                >
                  <Download className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/**
 * memo 比较策略：以 message 对象引用为主依赖（patchMsg 仅替换被 patch 那条的引用，
 * 其余消息引用不变），加上低频共享状态 busy / showSteps / exportOn；
 * 回调经 useRef 稳定化后引用恒定，无需比较。
 */
const BUBBLE_ARE_EQUAL = (prev: BubbleProps, next: BubbleProps): boolean =>
  prev.message === next.message &&
  prev.busy === next.busy &&
  prev.streaming === next.streaming &&
  prev.showSteps === next.showSteps &&
  prev.exportOn === next.exportOn &&
  prev.onNavigate === next.onNavigate;

export const ChatMessageBubble = memo(BubbleInner, BUBBLE_ARE_EQUAL);
ChatMessageBubble.displayName = "ChatMessageBubble";

/** 与后端 REST/SSE 契约对应的类型。 */

export interface Position {
  symbol: string;
  name: string;
  kind: string;
  industry: string;
  shares: number;
  last: number;
  market_value: number;
  /** 总成本 = 每股成本 × 股数（后端 market_view 口径）。编辑单价请用 cost_per_share。 */
  cost: number;
  /** 每股成本。老后端可能没有该字段，前端需回退到 cost / shares。 */
  cost_per_share?: number;
  pnl: number;
  pnl_pct: number;
}

export interface Transaction {
  id: number;
  date: string;
  item: string;
  category: string;
  amount: number;
}

export interface DebtItem {
  name: string;
  monthly: number;
  balance: number;
  rate: number;
  due_day?: string;
}

export interface RiskFlag {
  level: string;
  code: string;
  text: string;
}

export interface EmergencyInfo {
  cash: number;
  essential_monthly: number;
  essential_categories: string[];
  months_covered: number;
  target_months: number;
  has_data: boolean;
  ok: boolean;
}

export interface Goal {
  name: string;
  target: number;
  saved: number;
  pct: number;
  gap: number;
  deadline: string;
  months_left: number | null;
  monthly_suggest: number | null;
  done: boolean;
}

export interface MemoryItem {
  id: number;
  content: string;
  kind: string;
  created_at: string;
  updated_at: string;
}

export interface HealthReport {
  score: number;
  summary: string;
  dimensions: {
    key: string;
    title: string;
    status: "good" | "warn" | "bad";
    detail: string;
    suggestion: string;
  }[];
  flags: string[];
}

export interface IndexQuote {
  symbol: string;
  name: string;
  price: number;
  change: number | null;
  change_pct: number | null;
}

export interface DashboardData {
  positions: Position[];
  goals: Goal[];
  totals: {
    total_market_value: number;
    total_cost: number;
    total_pnl: number;
    total_pnl_pct: number;
  };
  today_pnl: { total: number; items: Record<string, number> };
  indices: IndexQuote[];
  concentration: {
    threshold_pct: number;
    /** pct 相对总市值（饼图/占比列）；investable_pct 相对非现金市值（集中度判定） */
    by_asset: { name: string; kind: string; pct: number; investable_pct?: number }[];
    by_industry: { industry: string; pct: number; investable_pct?: number }[];
    /** 超过单一持仓阈值的标的（后端已算好） */
    asset_breaches: { name: string; pct: number; investable_pct?: number }[];
    /** 超过行业集中度阈值的行业 */
    industry_breaches: { industry: string; pct: number; investable_pct?: number }[];
  };
  cashflow: {
    month: string;
    income: number;
    expense: number;
    net: number;
    savings_rate: number;
    by_category: { category: string; amount: number }[];
  };
  subscriptions: {
    items: { name: string; monthly: number; note: string; due_day?: string }[];
    monthly_total: number;
    annual_total: number;
  };
  debts: { items: DebtItem[]; monthly_total: number; dti_pct: number };
  emergency: EmergencyInfo;
  flags: RiskFlag[];
  transactions: Transaction[];
  /** 决策中心：把风险与目标收敛成的可执行待办（后端纯函数产出） */
  actions?: ActionCenter;
  source: { portfolio: string; ledger: string; quotes: string; seeded: boolean; demo?: boolean };
}

/** 单条待办：priority 越小越紧急；action_tab 指向应跳转的财务页 */
export interface ActionItem {
  domain: string;
  domain_label: string;
  priority: number;
  title: string;
  detail: string;
  impact: string;
  action: string;
  action_tab: string;
}

export interface ActionCenter {
  items: ActionItem[];
  count: number;
  top: ActionItem | null;
}

/** 已发送消息上挂过的附件：只存引用，正文和字节仍在工作台附件表。 */
export interface RunAttachment {
  id: number;
  filename: string;
  kind: string;
  mime?: string;
  /** true = 从工作台已有文件「引用」，移除时只取消引用，不删原文件。 */
  ref?: boolean;
}

export interface RunRecord {
  id: number;
  thread_id: string;
  question: string;
  answer: string;
  level: string;
  flags: RiskFlag[];
  created_at: string;
  /** 问答来源（2026-09 起随回答落库；更早的历史记录为空字符串 = 未知，不猜） */
  route?: string;
  llm?: string;
  route_reason?: string;
  /** 本轮调用过的工具（agent 模式落库） */
  tools?: string[];
  /** 工具执行轨迹（名称/参数/结果摘要）：历史回看还原“它做了哪几步” */
  steps?: AgentToolStep[];
  /** 对话结果附带的页面跳转意图（对话中枢：结果一键去对应页面） */
  actions?: { tab: string }[];
  /** 这一轮用户消息挂过的附件：刷新/换端后仍能回看 */
  attachments?: RunAttachment[];
  /** 回答依据（知识库/网页），随 run 落库 */
  sources?: AnswerSource[];
  /** 用户对回答的评价：1 赞 / -1 踩 / 0 未评 */
  feedback_rating?: number;
  feedback_reason?: string;
  /** 全局历史搜索附带：所属会话标题（无会话的孤儿记录为空） */
  session_title?: string;
}

/** 本轮回答真正使用的依据：知识库片段或正文外链 */
export interface AnswerSource {
  kind: "knowledge" | "web";
  title: string;
  detail?: string;
  url?: string;
  attachment_id?: number;
  score?: number;
}

/** 定时产出收件箱条目：晨报（cron）或技能触发（skill:<id>） */
export interface ScheduledOutput extends RunRecord {
  kind: "report" | "skill";
  skill_id: string | null;
  skill_name: string | null;
}

export interface SessionItem {
  id: number;
  thread_id: string;
  title: string;
  /** 1=置顶；老接口/老库可能没有这两个字段，按 0 兼容 */
  pinned?: number;
  archived?: number;
  created_at: string;
  updated_at: string;
}

export interface TrendMonth {
  month: string;
  income: number;
  expense: number;
  net: number;
}

export interface BudgetCatUsage {
  category: string;
  budget: number;
  spent: number;
  pct: number;
  over: boolean;
}

export interface BudgetUsage {
  month: string;
  budgets: { category: string; key: string; amount: number }[];
  usage: {
    total_budget: number;
    total_spent: number;
    total_pct: number;
    over: boolean;
    left: number;
    left_daily: number;
    days_left: number;
    categories: BudgetCatUsage[];
  };
}

export interface SchedulerStatus {
  enabled: boolean;
  report_time: string;
  last_run_at: string | null;
  next_run_at: string | null;
  last_error: string | null;
  generated: number;
}

export interface BootstrapData {
  settings: Record<string, string>;
  scheduler: SchedulerStatus;
  health: { llm_configured: boolean; model: string; auth_mode?: "token" | "accounts" | "local" };
  /** 模型目录（P0 模型点亮）：设置页勾选/输入区切换的候选清单 */
  model_catalog?: { id: string; name: string; provider: string; base: string; model: string }[];
  /** 已点亮模型（逗号分隔串解析后的列表） */
  enabled_models?: string[];
}

export interface AgentToolStep {
  /** 工具名（get_market_view 等） */
  name: string;
  args: Record<string, unknown>;
  /** 给用户看的结果摘要 */
  summary: string;
  /** 工具调用生命周期状态（pending→running→done/error） */
  status?: "pending" | "running" | "done" | "error";
  /** 本次工具调用耗时（ms） */
  duration_ms?: number;
  /** 工具调用 id（用于 running/done 配对） */
  id?: string;
}

/** 一轮 Agent 的规划步骤（supervisor 输出）：前端计划卡 / Agent 面板展示 */
export interface AgentPlanStep {
  id: string;
  label: string;
  detail: string;
}

export interface AnswerMeta {
  answer: string;
  level: string;
  route: string;
  route_reason: string;
  metrics: Record<string, number>;
  flags: RiskFlag[];
  /** 回答生成来源；历史记录未存来源时为 undefined（不渲染徽标） */
  llm?: "llm" | "template";
  /** 本轮调用过的工具（agent 模式） */
  tools?: string[];
}

/** 会话 token 计量（GET /api/sessions/{id}/usage） */
export type SessionUsage = {
  thread_id: string;
  turns: number;
  tokens_in: number;
  tokens_out: number;
  tokens_total: number;
  context_est: number;
  summary_chars: number;
  compacted: boolean;
};

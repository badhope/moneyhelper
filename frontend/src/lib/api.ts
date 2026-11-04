/** API 访问层：统一带访问口令（Authorization: Bearer，不进 URL/日志）；
 * 401 时通过注册的回调打开应用内口令对话框，输入后自动重试一次；
 * 普通请求带超时，SSE 由 fetch-event-source 管理断线重试。
 */

import { fetchEventSource } from "@microsoft/fetch-event-source";

const TOKEN_KEY = "wo.accessToken";
const REQUEST_TIMEOUT_MS = 20_000;

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

export function setToken(token: string): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

/** 口令对话框回调（由 App 注册，返回用户输入或 null=取消） */
let authPrompt: (() => Promise<string | null>) | null = null;

export function setAuthPromptHandler(fn: (() => Promise<string | null>) | null): void {
  authPrompt = fn;
}

/** 401 去重：并发请求同时 401 时只弹一次口令框，后续请求等结果后各自重试 */
let authPromptInFlight: Promise<string | null> | null = null;

async function askAuth(): Promise<string | null> {
  if (!authPrompt) return null;
  if (authPromptInFlight) return authPromptInFlight;
  authPromptInFlight = authPrompt().finally(() => {
    authPromptInFlight = null;
  });
  return authPromptInFlight;
}

/** 带超时的 fetch：外部 signal 与超时共存（任一触发即中止）。 */
async function fetchWithTimeout(path: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), timeoutMs);
  const external = init.signal;
  const onAbort = () => ctrl.abort();
  if (external) {
    if (external.aborted) ctrl.abort();
    else external.addEventListener("abort", onAbort);
  }
  try {
    return await fetch(path, { ...init, signal: ctrl.signal });
  } finally {
    window.clearTimeout(timer);
    external?.removeEventListener("abort", onAbort);
  }
}

function authHeaders(init: RequestInit): HeadersInit {
  const token = getToken();
  // FormData/Blob 由浏览器自己带 Content-Type（含 multipart boundary）；
  // 手动写死 application/json 会把 boundary 覆盖掉，后端解析不到文件。
  const isForm = typeof FormData !== "undefined" && init.body instanceof FormData;
  return {
    ...(isForm ? {} : { "Content-Type": "application/json" }),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(init.headers ?? {}),
  };
}

async function request(path: string, init: RequestInit = {}, retried = false): Promise<Response> {
  let resp: Response;
  try {
    resp = await fetchWithTimeout(path, { ...init, headers: authHeaders(init) }, REQUEST_TIMEOUT_MS);
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("请求超时，请检查服务是否可用");
    }
    throw err;
  }
  if (resp.status === 401 && !retried) {
    const input = await askAuth();
    if (input) {
      setToken(input.trim());
      return request(path, init, true);
    }
    throw new Error("需要访问口令");
  }
  return resp;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const resp = await request(path, init);
  if (!resp.ok) {
    // 兜底必须是「人能读懂的句子」，不能是裸状态码：代理层 502/504 常返回
    // HTML 而非 JSON，此前用户界面会只显示 "500" / "502" —— 完全无法判断
    // 是服务没启动、还是接口报错、还是网络断了。
    let detail = `请求失败（HTTP ${resp.status}）`;
    try {
      const body = await resp.json();
      detail = body?.error ?? body?.detail ?? body?.message ?? detail;
    } catch {
      if (resp.status >= 500) detail = `服务暂时不可用（HTTP ${resp.status}），请稍后重试或检查后端是否已启动`;
      else if (resp.status === 404) detail = "接口不存在（HTTP 404），请确认前后端版本一致";
    }
    throw new Error(detail);
  }
  // 部分接口（如 DELETE）可能返回空 body，避免对空串调 json() 报 SyntaxError
  const text = await resp.text();
  return (text ? (JSON.parse(text) as T) : ({} as T));
}

/** 内部信号：需要用户重新输口令（触发一次带新口令的重试） */
class ReauthError extends Error {}
/** 致命错误：不重试，直接抛给调用方 */
class FatalError extends Error {}

/**
 * SSE 流式问答：用微软官方 fetch-event-source。
 *
 * 生产级增强：
 * - 指数退避重连：首次断连等 1s，第二次 2s，第三次 4s，最多 5 次
 * - 网络恢复自动重试：监听 online 事件，断连后网络恢复时立即重试
 * - 页面隐藏不打断：openWhenHidden=true（提问后切标签页也不中断生成）
 * - 已收到内容不重试：got 后断连直接报错（重试会重跑一遍后端）
 *
 * fetch-event-source 的 onerror 语义：返回数字=延迟后重试，抛错=停止重试。
 */

const MAX_RETRIES = 5;
const BASE_RETRY_MS = 1000;

export interface StreamHandle {
  /** 当前重试次数（0=首次连接） */
  retryCount: number;
  /** 最后一次断连时间戳 */
  lastDisconnectMs: number;
  /** 总收到的字节数 */
  bytesReceived: number;
}

export async function apiStream(
  path: string,
  body: unknown,
  onLine: (obj: Record<string, unknown>) => void,
  signal?: AbortSignal,
  retried = false,
): Promise<void> {
  let got = false;
  // 是否收到服务端的终帧。只有收到 done 才算这条流成功走完；
  // 仅有"收到过内容"不足以判定成功——断连时也会 got=true，
  // 旧逻辑会直接 return，把半截回答当成完整结果展示给用户。
  let completed = false;
  let retryCount = 0;

  try {
    while (retryCount <= MAX_RETRIES) {
      if (signal?.aborted) break;

      // 离线时等网络恢复再试
      if (!navigator.onLine) {
        await _waitForOnline(signal);
        if (signal?.aborted) break;
      }

      try {
        await _fetchOnce(path, body, signal, retried, (obj) => {
          got = true;
          if (obj && obj.type === "done") completed = true;
          onLine(obj);
        });
        if (completed) return; // 收到终帧才算完整接收
        // 连接正常关闭但没收到 done：一律视为断流，交给重试逻辑。
        // 此前 got=false（一帧都没收到，例如反代超时/后端 204）时直接 return，
        // 调用方以为成功，气泡留空并永久显示「分析中」。
        if (got) throw new Error("流式连接提前结束（未收到完成标记）");
        throw new Error("流式连接未返回任何数据（服务端或代理中断）");
      } catch (err) {
        if (signal?.aborted) break;
        if (err instanceof ReauthError) {
          return apiStream(path, body, onLine, signal, true);
        }
        if (err instanceof FatalError) throw err;
        // 已经收到部分内容：不重放（会重复半段），但必须把"未完成"如实抛出，
        // 否则 UI 会把半截回答当成完整结果（旧逻辑在这里静默 return）。
        if (got) {
          throw err instanceof Error ? err : new Error("流式连接中断");
        }
        retryCount++;
        if (retryCount > MAX_RETRIES) {
          throw new Error(`流式连接中断，已重试 ${MAX_RETRIES} 次`);
        }
        const delay = BASE_RETRY_MS * 2 ** (retryCount - 1);
        // 每次重试创建新的 onlinePromise，防止"首次恢复后背底失效"
        await Promise.race([
          _sleep(delay, signal),
          new Promise<void>((resolve) => {
            if (navigator.onLine) { resolve(); return; }
            const onOnline = () => { window.removeEventListener("online", onOnline); resolve(); };
            window.addEventListener("online", onOnline);
            // signal abort 时也退出
            signal?.addEventListener("abort", () => {
              window.removeEventListener("online", onOnline);
              resolve();
            }, { once: true });
          }),
        ]);
      }
    }
  } finally {
    // cleanup 已内联到 Promise 构造中
  }

  if (signal?.aborted) {
    const e = new Error("aborted");
    e.name = "AbortError";
    throw e;
  }
}

/** 单次 SSE 连接（内部辅助，不含重试逻辑） */
async function _fetchOnce(
  path: string,
  body: unknown,
  signal: AbortSignal | undefined,
  retried: boolean,
  onLine: (obj: Record<string, unknown>) => void,
): Promise<void> {
  const token = getToken();
  await fetchEventSource(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
    openWhenHidden: true,
    async onopen(response) {
      if (response.status === 401) {
        if (!retried) {
          const input = await askAuth();
          if (input) {
            setToken(input.trim());
            throw new ReauthError();
          }
        }
        throw new FatalError("需要访问口令");
      }
      if (!response.ok) {
        let detail = `${response.status}`;
        try {
          const b = await response.clone().json();
          if (b?.error) detail = b.error;
        } catch {
          /* ignore */
        }
        throw new FatalError(detail);
      }
    },
    onmessage(ev) {
      if (!ev.data || ev.data === "[DONE]") return;
      try {
        onLine(JSON.parse(ev.data) as Record<string, unknown>);
      } catch {
        /* 忽略坏帧 */
      }
    },
    onclose() {
      // 对端正常关闭 → 不重试
    },
    onerror(err) {
      if (err instanceof ReauthError || err instanceof FatalError) throw err;
      if (signal?.aborted) throw err;
      throw err; // 交给外层 while 循环做重试
    },
  });
}

/** 等待网络恢复（或 signal 中止） */
function _waitForOnline(signal?: AbortSignal): Promise<void> {
  if (navigator.onLine) return Promise.resolve();
  return new Promise((resolve) => {
    const onOnline = () => {
      cleanup();
      resolve();
    };
    const onAbort = () => {
      cleanup();
      resolve();
    };
    const cleanup = () => {
      window.removeEventListener("online", onOnline);
      signal?.removeEventListener("abort", onAbort);
    };
    window.addEventListener("online", onOnline);
    signal?.addEventListener("abort", onAbort);
  });
}

function _sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(t);
      resolve();
    });
  });
}

// ---------------------------------------------------------------------------
// 财务目标
// ---------------------------------------------------------------------------

export const listGoals = () =>
  api<{ goals: import("@/lib/types").Goal[] }>("/api/goals").then((r) => r.goals);

export const createGoal = (g: { name: string; target: number; saved?: number; deadline?: string }) =>
  api<{ ok: boolean; name: string }>("/api/goals", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(g),
  });

export const updateGoal = (name: string, patch: { saved?: number; target?: number; deadline?: string }) =>
  api<{ ok: boolean }>(`/api/goals/${encodeURIComponent(name)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });

export const deleteGoal = (name: string) =>
  api<{ ok: boolean; deleted: number }>(`/api/goals/${encodeURIComponent(name)}`, { method: "DELETE" });

// ---------------------------------------------------------------------------
// 长期记忆
// ---------------------------------------------------------------------------

export const listMemory = () =>
  api<{ memory: import("@/lib/types").MemoryItem[] }>("/api/memory").then((r) => r.memory);

/** 写类动作 HITL 确认：token 一次性消费；409 = 已失效（过期/已执行/已取消）。 */
export const confirmAction = (token: string, decision: "confirm" | "cancel") =>
  api<{ ok: boolean; cancelled?: boolean; answer?: string; summary?: string }>("/api/confirm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, decision }),
  });

export const addMemory = (content: string) =>
  api<{ ok: boolean; id: number; deduped?: boolean }>("/api/memory", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });

export const deleteMemory = (id: number) =>
  api<{ ok: boolean; deleted: number }>(`/api/memory/${id}`, { method: "DELETE" });

export const clearMemory = () =>
  api<{ ok: boolean; deleted: number }>("/api/memory/clear", { method: "POST" });

/** 主动遗忘：清理超过 N 天未使用的记忆。 */
export const forgetMemory = (olderThanDays: number) =>
  api<{ ok: boolean; deleted: number; still_stale: number }>("/api/memory/forget", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ older_than_days: olderThanDays }),
  });

/** AI 归纳用户偏好：基于最近提问 + 现有记忆，建议若干条长期记忆（只出建议）。 */
export const suggestMemories = () =>
  api<{ ok: boolean; suggestions?: string[]; based_on?: { questions: number }; error?: string }>(
    "/api/memory/suggest",
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) },
  );

// ---------------------------------------------------------------------------
// 技能定时动作
// ---------------------------------------------------------------------------

/** 技能触发历史（归档在独立线程 skill:<id>，不进会话列表）。 */
export const listSkillRuns = (skillId: string, limit = 10) =>
  api<{ runs: import("@/lib/types").RunRecord[] }>(
    `/api/history?thread_id=${encodeURIComponent(`skill:${skillId}`)}&limit=${limit}`,
  ).then((r) => r.runs ?? []);

// —— 经验库（P1 反思 / 踩坑复盘）——
export interface ReflectionItem {
  id: number;
  tool: string;
  args: Record<string, unknown>;
  error: string;
  lesson: string;
  created_at: string;
}
export const listReflections = () =>
  api<{ reflections: ReflectionItem[] }>("/api/reflections").then((r) => r.reflections);
export const resolveReflection = (id: number) =>
  api<{ ok: boolean }>(`/api/reflections/${id}/resolve`, { method: "POST" });
export const clearReflections = () =>
  api<{ ok: boolean; deleted: number }>("/api/reflections/clear", { method: "POST" });

// ---------------------------------------------------------------------------
// 财务体检
// ---------------------------------------------------------------------------

export const fetchHealthCheck = (lang = "zh") =>
  api<import("@/lib/types").HealthReport>(`/api/health-check?lang=${encodeURIComponent(lang)}`);

// ---------------------------------------------------------------------------
// 日志
// ---------------------------------------------------------------------------

export const fetchLogs = (limit = 200) =>
  api<{ lines: string[]; total: number }>(`/api/logs?limit=${limit}`)

export const clearLogs = () =>
  api<{ ok: boolean; cleared_lines: number }>("/api/logs/clear", { method: "POST" })

// ---------------------------------------------------------------------------
// 审计日志（P2 金融级治理）
// ---------------------------------------------------------------------------

export interface AuditItem {
  id: number;
  ts: string;
  action: string;
  method: string;
  path: string;
  status: number;
  actor: string;
  detail: string;
  duration_ms: number;
}
export const listAudit = (limit = 200, action?: string) =>
  api<{ audit: AuditItem[] }>(
    `/api/audit?limit=${limit}${action ? `&action=${encodeURIComponent(action)}` : ""}`,
  ).then((r) => r.audit);
export const clearAudit = () =>
  api<{ ok: boolean; deleted: number }>("/api/audit/clear", { method: "POST" })

// ---------------------------------------------------------------------------
// 溯源链（provenance）：每个数字的来龙去脉
// ---------------------------------------------------------------------------

export interface ProvenanceItem {
  id: string;
  timestamp: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  before_json: string | null;
  after_json: string | null;
  source: string;
  username: string;
  metadata_json: string | null;
}

export const listProvenance = (params: {
  entityType?: string;
  entityId?: string;
  limit?: number;
} = {}) => {
  const q = new URLSearchParams();
  if (params.entityType) q.set("entity_type", params.entityType);
  if (params.entityId) q.set("entity_id", params.entityId);
  q.set("limit", String(params.limit ?? 50));
  return api<{ count: number; provenances: ProvenanceItem[] }>(
    `/api/provenance?${q.toString()}`,
  ).then((r) => r.provenances);
};

// ---------------------------------------------------------------------------
// 附件（P2 能力扩展）：@提及引用文件
// ---------------------------------------------------------------------------

export interface AttachmentItem {
  id: number;
  filename: string;
  kind: string;
  size: number;
  created_at: string;
}
export const listAttachments = () =>
  api<{ attachments: AttachmentItem[] }>("/api/attachments").then((r) => r.attachments);
export const uploadAttachment = (file: File) => {
  const fd = new FormData();
  fd.append("file", file);
  return api<{ ok: boolean; id: number }>("/api/attachments", { method: "POST", body: fd });
};
export const deleteAttachment = (id: number) =>
  api<{ ok: boolean; deleted: number }>(`/api/attachments/${id}`, { method: "DELETE" });

// ---------------------------------------------------------------------------
// 撤销面板（CommandPalette 最近操作 → 撤回）
// ---------------------------------------------------------------------------

export interface UndoableItem {
  id: number;
  entity: string;
  entity_id: string;
  label: string;
  created_at: string;
}
export const listUndoables = (limit = 8) =>
  api<{ items: UndoableItem[] }>(`/api/undoables?limit=${limit}`).then((r) => r.items);
export const undoById = (recordId: number) =>
  api<{ ok: boolean; consumed_at?: string }>(`/api/undo/${recordId}`, { method: "POST" });

// ---------------------------------------------------------------------------
// 家庭 / 成员 / 借贷（后端早已完整，此前前端零入口）
// ---------------------------------------------------------------------------

export interface FamilyMember {
  id: number;
  username: string;
  display_name: string;
  role: "owner" | "admin" | "member" | "viewer";
  avatar_color: string;
  created_at: string;
}

export interface MemberLoan {
  id: number;
  from_member_id: number;
  to_member_id: number;
  amount: number;
  currency: string;
  note: string;
  settled: number;
  created_at: string;
  settled_at?: string | null;
  from_name?: string;
  to_name?: string;
}

export interface MemberSummary {
  member_id: number;
  income: number;
  expense: number;
  transaction_count: number;
  display_name: string;
  role: string;
  avatar_color: string;
}

export interface FamilySummary {
  household_income: number;
  household_expense: number;
  household_net: number;
  members: {
    id: number;
    display_name: string;
    role: string;
    avatar_color: string;
    income: number;
    expense: number;
    balance: number;
    pct: number;
    transaction_count: number;
  }[];
  outstanding_loans?: MemberLoan[];
  top_categories?: { category: string; amount: number }[];
}

export const listMembers = () =>
  api<{ members: FamilyMember[] }>("/api/members").then((r) => r.members);
export const addMember = (body: { display_name: string; role?: string; username?: string }) =>
  api<{ ok: boolean; member: FamilyMember }>("/api/members", {
    method: "POST",
    body: JSON.stringify(body),
  });
export const updateMember = (id: number, body: Record<string, string>) =>
  api<{ ok: boolean }>(`/api/members/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const deleteMember = (id: number) =>
  api<{ ok: boolean; deleted: number }>(`/api/members/${id}`, { method: "DELETE" });
export const listMemberLoans = () =>
  api<{ loans: MemberLoan[] }>("/api/members/loans").then((r) => r.loans);
export const createMemberLoan = (body: {
  from_member_id: number;
  to_member_id: number;
  amount: number;
  note?: string;
}) =>
  api<{ ok: boolean; id: number }>("/api/members/loans", {
    method: "POST",
    body: JSON.stringify(body),
  });
export const settleMemberLoan = (id: number) =>
  api<{ ok: boolean }>(`/api/members/loans/${id}/settle`, { method: "POST" });
export const deleteMemberLoan = (id: number) =>
  api<{ ok: boolean }>(`/api/members/loans/${id}`, { method: "DELETE" });
export const memberSummaries = () =>
  api<{ members: MemberSummary[] }>("/api/members/summary").then((r) => r.members);
export const familySummary = () => api<FamilySummary>("/api/family/summary");

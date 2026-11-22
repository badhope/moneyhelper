/** API 域：目标 / 长期记忆 / 技能 / 体检 / 日志 / 审计 / 溯源 / 附件 / 撤销。
 *
 * 从 api.ts 拆出（原 342-548 行），api.ts 以 `export *` 汇总，调用方路径不变。
 */

import {
  api,
  SLOW_REQUEST_TIMEOUT_MS,
} from "./client";

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
  api<{ runs: { id: number; question: string; created_at: string }[] }>(
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
  /** text / csv / image / pdf */
  kind: string;
  /** 二进制附件的 MIME；文本为空 */
  mime?: string;
  size: number;
  /** 0/1：是否已加入知识库（参与检索） */
  indexed: number;
  /** 是否保留了原始字节；文本附件下载完整文件靠它 */
  has_data?: boolean;
  created_at: string;
}
export interface AttachmentHit extends AttachmentItem {
  /** 正文命中时返回关键词附近片段；文件名命中为空 */
  snippet: string;
  match: "filename" | "content";
}

export interface AttachmentDetail extends AttachmentItem {
  /** 正文（后端只存前 6000 字；图片/PDF 为空） */
  content: string;
  /** 是否有原始字节（图片/PDF 预览与下载用） */
  has_data?: boolean;
}
export const getAttachment = (id: number) =>
  api<AttachmentDetail>(`/api/attachments/${id}`);
export const listAttachments = () =>
  api<{ attachments: AttachmentItem[] }>("/api/attachments").then((r) => r.attachments);
export const searchAttachments = (q: string, limit = 30) => {
  const query = q.trim();
  if (!query) return Promise.resolve([] as AttachmentHit[]);
  return api<{ results: AttachmentHit[] }>(
    `/api/attachments/search?q=${encodeURIComponent(query)}&limit=${Math.max(1, Math.min(limit, 50))}`,
  ).then((r) => (Array.isArray(r.results) ? r.results : []));
};
export const uploadAttachment = (file: File) => {
  const fd = new FormData();
  fd.append("file", file);
  return api<{ ok: boolean; id: number }>(
    "/api/attachments",
    { method: "POST", body: fd },
    { timeoutMs: SLOW_REQUEST_TIMEOUT_MS },
  );
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

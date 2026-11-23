import { api } from "./client";

export interface ThreadContextAttachment {
  id: number;
  filename: string;
  kind: string;
}
export interface ThreadMemory {
  id: number;
  text: string;
}
export interface ThreadContext {
  thread_id: string;
  project_id?: number | null;
  project_name?: string;
  instructions: string;
  attachments: ThreadContextAttachment[];
  memories: ThreadMemory[];
  updated_at?: string;
}

export interface ChatProjectSummary {
  id: number;
  name: string;
  instructions: string;
  attachment_count: number;
  memory_count: number;
  updated_at: string;
}
export interface ChatProject extends ChatProjectSummary {
  attachments: ThreadContextAttachment[];
  memories: ThreadMemory[];
}

export const getThreadContext = (threadId: string) =>
  api<ThreadContext>(`/api/threads/${encodeURIComponent(threadId)}/context`);

export const saveThreadContext = (
  threadId: string,
  body: {
    instructions: string;
    attachment_ids: number[];
    memories: string[];
    /** null = 退回仅本会话；不传 = 保留已有绑定 */
    project_id?: number | null;
  },
) =>
  api<ThreadContext>(`/api/threads/${encodeURIComponent(threadId)}/context`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const clearThreadContext = (threadId: string) =>
  api<ThreadContext>(`/api/threads/${encodeURIComponent(threadId)}/context`, {
    method: "DELETE",
  });

export const listChatProjects = () =>
  api<{ projects: ChatProjectSummary[] }>("/api/chat-projects").then((r) => r.projects);

export const getChatProject = (id: number) =>
  api<ChatProject>(`/api/chat-projects/${id}`);

export const createChatProject = (body: {
  name: string;
  instructions: string;
  attachment_ids: number[];
  memories: string[];
}) =>
  api<ChatProject>("/api/chat-projects", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const updateChatProject = (
  id: number,
  body: { name: string; instructions: string; attachment_ids: number[]; memories: string[] },
) =>
  api<ChatProject>(`/api/chat-projects/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const deleteChatProject = (id: number) =>
  api<{ ok: boolean; deleted: boolean }>(`/api/chat-projects/${id}`, { method: "DELETE" });

export interface ShareResult {
  token: string;
  path: string;
  expires_at: string;
}
export const createShare = (threadId: string, expireDays = 7) =>
  api<ShareResult>("/api/shares", {
    method: "POST",
    body: JSON.stringify({ thread_id: threadId, expire_days: expireDays }),
  });
export const revokeShare = (token: string) =>
  api<{ ok: boolean }>(`/api/shares/${encodeURIComponent(token)}`, { method: "DELETE" });

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
  instructions: string;
  attachments: ThreadContextAttachment[];
  memories: ThreadMemory[];
  updated_at?: string;
}

export const getThreadContext = (threadId: string) =>
  api<ThreadContext>(`/api/threads/${encodeURIComponent(threadId)}/context`);

export const saveThreadContext = (
  threadId: string,
  body: { instructions: string; attachment_ids: number[]; memories: string[] },
) =>
  api<ThreadContext>(`/api/threads/${encodeURIComponent(threadId)}/context`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const clearThreadContext = (threadId: string) =>
  api<ThreadContext>(`/api/threads/${encodeURIComponent(threadId)}/context`, {
    method: "DELETE",
  });

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

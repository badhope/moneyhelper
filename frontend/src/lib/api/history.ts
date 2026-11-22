/** 历史问答搜索：跨会话搜正文，返回侧栏可直接渲染的命中片段。 */

import { api } from "./client";

export interface HistoryHit {
  id: number;
  thread_id: string;
  session_title: string;
  role: "question" | "answer";
  snippet: string;
  created_at: string;
  archived: boolean;
}

export async function searchHistory(q: string, limit = 20): Promise<HistoryHit[]> {
  const query = q.trim();
  if (!query) return [];
  const res = await api<{ results: HistoryHit[] }>(
    `/api/history?q=${encodeURIComponent(query)}&compact=1&limit=${Math.max(1, Math.min(limit, 50))}`,
  );
  return Array.isArray(res.results) ? res.results : [];
}

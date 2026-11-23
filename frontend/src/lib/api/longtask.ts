/** API 域：长任务（分段执行 + 产物落盘）。
 *
 * 从 api.ts 拆出（原 1387-1462 行），api.ts 以 `export *` 汇总，调用方路径不变。
 */

import {
  api,
} from "./client";
import type { FamilySummary } from "./family";

// ---------------------------------------------------------------------------

export interface LongTaskStage {
  index: number;
  name: string;
  instruction: string;
  status: string; // pending/running/done/failed/skipped
  chars: number;
  file: string;
  error: string;
  started_at: string;
  finished_at: string;
  /** 本阶段实际尝试次数；旧任务可能没有该字段 */
  attempts?: number;
  /** 本阶段总耗时（毫秒）；取消或旧任务可能没有 */
  duration_ms?: number;
}

export interface LongTask {
  id: string;
  kind: string;
  title: string;
  brief: string;
  success_criteria?: string;
  error?: string;
  status: string; // pending/running/done/failed/cancelled
  created_at: string;
  updated_at: string;
  stages: LongTaskStage[];
}

export interface LongTaskSummary {
  id: string;
  kind: string;
  title: string;
  status: string;
  done: number;
  total: number;
  created_at: string;
  updated_at: string;
}

export const listLongTaskTemplates = () =>
  api<{ templates: { id: string; label: string; stages: string[] }[] }>(
    "/api/longtasks/templates",
  ).then((r) => r.templates);

export const listLongTasks = () =>
  api<{ tasks: LongTaskSummary[] }>("/api/longtasks").then((r) => r.tasks);

export const createLongTask = (body: {
  kind: string;
  title: string;
  brief: string;
  success_criteria?: string;
  stages?: string[];
}) =>
  api<{ ok: boolean; task: LongTask }>("/api/longtasks", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const runLongTask = (id: string, maxStages?: number, background = true) =>
  api<{ ok: boolean; task: LongTask }>(`/api/longtasks/${id}/run`, {
    method: "POST",
    body: JSON.stringify({
      ...(maxStages ? { max_stages: maxStages } : {}),
      ...(background ? { background: true } : {}),
    }),
  });

export const cancelLongTask = (id: string) =>
  api<{ ok: boolean; task: LongTask }>(`/api/longtasks/${id}/cancel`, {
    method: "POST",
  });

export const getLongTask = (id: string) =>
  api<LongTask>(`/api/longtasks/${id}`);

export const readLongTaskStage = (id: string, index: number) =>
  api<{ task_id: string; index: number; content: string }>(
    `/api/longtasks/${id}/stages/${index}`,
  ).then((r) => r.content);

export const familySummary = () => api<FamilySummary>("/api/family/summary");

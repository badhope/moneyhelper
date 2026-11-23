/** API 域：长任务（分段执行 + 产物落盘）。
 *
 * 从 api.ts 拆出（原 1387-1462 行），api.ts 以 `export *` 汇总，调用方路径不变。
 */

import {
  api,
} from "./client";
import type { FamilySummary } from "./family";

// ---------------------------------------------------------------------------

export interface LongTaskContract {
  min_chars: number;
  max_chars: number;
  required_sections: string[];
  forbid_placeholders: boolean;
  use_tools: boolean;
  route: string;
}

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
  contract?: LongTaskContract;
  /** 上游重算后，本阶段产物基于旧上下文：已过期，需重算确认 */
  stale?: boolean;
  stale_reason?: string;
  stale_at?: string;
  checkpoint_id?: string;
  tools_used?: string[];
  tool_steps?: { name: string; summary: string; status: string; duration_ms: number }[];
  validation?: { ok?: boolean; errors?: string[]; checked_at?: string; restored_from?: string };
}

export interface LongTask {
  id: string;
  kind: string;
  title: string;
  brief: string;
  success_criteria?: string;
  error?: string;
  status: string; // pending/running/done/failed/cancelled
  /** 是否真有后台协程在跑：区分“状态机 running”与“实际执行中” */
  active?: boolean;
  stale_count?: number;
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
  stale?: number;
  total: number;
  created_at: string;
  updated_at: string;
}

export interface LongTaskCheckpoint {
  id: string;
  stage_index: number;
  stage_name: string;
  created_at: string;
  chars: number;
  attempt: number;
  duration_ms: number;
  source: string;
  contract_ok: boolean;
  tools_used: string[];
  file: string;
}

export const listLongTaskTemplates = () =>
  api<{
    templates: {
      id: string;
      label: string;
      stages: string[];
      contracts?: LongTaskContract[];
    }[];
  }>("/api/longtasks/templates").then((r) => r.templates);

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

export const runLongTask = (
  id: string,
  maxStages?: number,
  background = true,
  stageIndex?: number,
  cascade = false,
  staleOnly = false,
) =>
  api<{ ok: boolean; task: LongTask }>(`/api/longtasks/${id}/run`, {
    method: "POST",
    body: JSON.stringify({
      ...(maxStages ? { max_stages: maxStages } : {}),
      ...(stageIndex != null ? { stage_index: stageIndex } : {}),
      ...(background ? { background: true } : {}),
      ...(cascade ? { cascade: true } : {}),
      ...(staleOnly ? { stale_only: true } : {}),
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

export const listLongTaskCheckpoints = (id: string, stageIndex: number) =>
  api<{ checkpoints: LongTaskCheckpoint[] }>(
    `/api/longtasks/${id}/stages/${stageIndex}/checkpoints`,
  ).then((r) => r.checkpoints);

export const rollbackLongTask = (
  id: string,
  stageIndex: number,
  checkpointId: string,
) =>
  api<{ ok: boolean; task: LongTask }>(`/api/longtasks/${id}/rollback`, {
    method: "POST",
    body: JSON.stringify({
      stage_index: stageIndex,
      checkpoint_id: checkpointId,
    }),
  });

export const familySummary = () => api<FamilySummary>("/api/family/summary");

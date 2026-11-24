/** 自动化运行台账：真实后台工作流的读取与手动补跑（/api/automation/*）。 */

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

export type AutomationStep = {
  name: string;
  ok: boolean;
  duration_ms: number;
  result: Record<string, unknown> | null;
  error?: string;
};

export type AutomationRun = {
  id: string;
  workflow: string;
  workflow_name: string;
  trigger: "manual" | "schedule" | string;
  status: "running" | "done" | "partial" | "failed" | string;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  steps: AutomationStep[];
  error?: string;
};

export type AutomationWorkflow = {
  key: string;
  name: string;
  scope: "personal" | "enterprise" | string;
  description: string;
  steps: string[];
};

const POLL_MS = 60_000;

export function useAutomation(active: boolean) {
  const [workflows, setWorkflows] = useState<AutomationWorkflow[]>([]);
  const [runs, setRuns] = useState<AutomationRun[] | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [w, r] = await Promise.all([
        api<{ workflows: AutomationWorkflow[] }>("/api/automation/workflows"),
        api<{ runs: AutomationRun[] }>("/api/automation/runs?limit=8"),
      ]);
      setWorkflows(w.workflows ?? []);
      setRuns(r.runs ?? []);
      setError("");
    } catch {
      setRuns((prev) => prev ?? []);
      setError("load");
    }
  }, []);

  useEffect(() => {
    if (!active) return;
    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [active, refresh]);

  const run = useCallback(
    async (key: string) => {
      setRunning(key);
      setError("");
      try {
        await api<AutomationRun>(`/api/automation/workflows/${key}/run`, {
          method: "POST",
          body: JSON.stringify({}),
        });
        await refresh();
      } catch {
        setError("run");
      } finally {
        setRunning(null);
      }
    },
    [refresh],
  );

  return { workflows, runs, running, error, refresh, run };
}

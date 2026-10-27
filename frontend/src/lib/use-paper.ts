/** 团队模拟盘 API hooks（v4.2）：开户 / 下单 / 列表 / 详情 / 删除。
 *
 * 与 use-research 同风格：请求内联在组件外，页面只关心状态与回填。
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

export interface PaperAccount {
  account_id: string;
  name: string;
  initial_cash: number;
  created_at: string;
  trade_count: number;
  cash: number;
  equity: number;
  market_value: number;
  return_pct: number;
  total_pnl: number;
  position_count: number;
  stale: boolean;
  holdings: PaperPosition[];
}

export interface PaperPosition {
  symbol: string;
  shares: number;
  cost: number;
  last: number;
  market_value: number;
  pnl: number;
  pnl_pct: number | null;
}

export interface PaperSummary {
  account_count: number;
  total_initial_cash: number;
  total_equity: number;
  total_pnl: number;
  return_pct: number;
  active_positions: number;
}

export interface PaperListResp {
  items: PaperAccount[];
  summary: PaperSummary;
  valuation_source: string;
}

export interface PaperCurve {
  dates: string[];
  equity: number[];
  bench: number[];
}

export interface PaperTrade {
  id: number;
  date: string;
  symbol: string;
  name: string;
  side: "buy" | "sell";
  price: number;
  shares: number;
  fee: number;
  amount: number;
}

export interface PaperDetailResp {
  account: PaperAccount;
  curve: PaperCurve;
  trades: PaperTrade[];
}

export function usePaperList() {
  const [data, setData] = useState<PaperListResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await api<PaperListResp>("/api/paper/accounts");
      setData(resp);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload };
}

export function usePaperDetail(accountId: string | null) {
  const [data, setData] = useState<PaperDetailResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const reload = useCallback(async () => {
    if (!accountId) {
      setData(null);
      return;
    }
    setLoading(true);
    try {
      const resp = await api<PaperDetailResp>(`/api/paper/accounts/${accountId}`);
      setData(resp);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [accountId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload };
}

export async function paperOpen(name: string, initialCash: number): Promise<void> {
  await api(`/api/paper/accounts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, initial_cash: initialCash }),
  });
}

export async function paperDelete(accountId: string): Promise<void> {
  await api(`/api/paper/accounts/${accountId}`, { method: "DELETE" });
}

export async function paperTrade(
  accountId: string,
  trade: { symbol: string; side: "buy" | "sell"; price: number; shares: number; name?: string },
): Promise<void> {
  await api(`/api/paper/accounts/${accountId}/trades`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(trade),
  });
}

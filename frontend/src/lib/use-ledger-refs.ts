import { useQuery, useQueryClient } from "@tanstack/react-query";
import { listGlAccounts, listGlPeriods, type GlAccount, type GlPeriod } from "@/lib/api";

/**
 * 账务引用数据（科目表 + 会计期间）：全站唯一来源。
 *
 * 原先 4 个页面（总账、银行对账、报销、采购应付）各自
 * `Promise.all([listGlAccounts(), listGlPeriods()])`，同一次页面切换里
 * 同一份科目表被请求 3–4 次；而且每页再各写一份 loading / 错误处理。
 *
 * 用 TanStack Query 缓存的原因：这两份数据"很少变、到处用"，正好是查询缓存的对象；
 * 不该为了"少装一个库"去手写一个模块级 Map 缓存（那是把库的活重做一遍，还得自己处理
 * 失效、并发、登出清理）。
 *
 * invalidate 时机：任何会改科目/期间的操作（建账、新增科目、新增期间、关账）之后调用
 * `useLedgerRefsInvalidate()` 即可，各页无需知道彼此存在。
 */
const STALE_MS = 60 * 1000;

export function useLedgerAccounts() {
  return useQuery({
    queryKey: ["gl", "accounts"],
    queryFn: () => listGlAccounts(),
    staleTime: STALE_MS,
  });
}

export function useLedgerPeriods() {
  return useQuery({
    queryKey: ["gl", "periods"],
    queryFn: () => listGlPeriods(),
    staleTime: STALE_MS,
  });
}

/** 一份 hook 同时拿两样，供"就想要这两张表"的页面用。 */
export function useLedgerRefs(): {
  accounts: GlAccount[];
  periods: GlPeriod[];
  loading: boolean;
  error: unknown;
  invalidate: () => void;
} {
  const qa = useLedgerAccounts();
  const qp = useLedgerPeriods();
  const qc = useQueryClient();
  return {
    accounts: qa.data ?? [],
    periods: qp.data ?? [],
    loading: qa.isLoading || qp.isLoading,
    error: qa.error ?? qp.error ?? null,
    invalidate: () => {
      void qc.invalidateQueries({ queryKey: ["gl", "accounts"] });
      void qc.invalidateQueries({ queryKey: ["gl", "periods"] });
    },
  };
}

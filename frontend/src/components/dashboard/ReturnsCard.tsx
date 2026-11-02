/** 投资收益卡片：XIRR / TWR / 简单收益率 */

import { LineChart } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/lib/i18n";
import { fmtPct, pnlClass } from "@/lib/format";
import { useReturns, type ReturnMetric } from "@/lib/use-calculations";

/** 指标可能整体缺失：空账本/无持仓时后端不返回 xirr 与 twr 键，
 *  旧实现直接 `"error" in m` 会对 undefined 做 in 运算并整页崩溃（总览白屏）。 */
function metricPct(m: ReturnMetric | { error: string } | undefined | null): number | null {
  if (!m || "error" in m) return null;
  return m.pct;
}

function metricValue(m: ReturnMetric | { error: string } | undefined | null): string {
  if (!m || "error" in m) return "—";
  return fmtPct(m.pct, true);
}

export function ReturnsCard({ months = 6 }: { months?: number }) {
  const { t: tr } = useI18n();
  const { data, isLoading, isError } = useReturns(months);

  if (isLoading) {
    return (
      <Card className="p-[var(--card-pad)]">
        <Skeleton className="h-4 w-20 mb-3" />
        <div className="grid grid-cols-3 gap-2">
          <Skeleton className="h-10 rounded" />
          <Skeleton className="h-10 rounded" />
          <Skeleton className="h-10 rounded" />
        </div>
      </Card>
    );
  }
  if (isError || !data) {
    return (
      <Card className="p-[var(--card-pad)]">
        <div className="text-sm text-muted-foreground">{tr("returns.loadFail")}</div>
      </Card>
    );
  }

  return (
    <Card className="p-[var(--card-pad)]">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 text-sm font-medium">
          <LineChart className="w-4 h-4 text-primary" />
          {tr("returns.title")}
        </div>
        <span className="text-xs text-muted-foreground">{data.period_months}{tr("returns.monthsUnit")}</span>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <ReturnStat
          label={tr("returns.xirr")}
          value={metricValue(data.xirr ?? undefined)}
          pct={metricPct(data.xirr ?? undefined)}
        />
        <ReturnStat
          label={tr("returns.twr")}
          value={metricValue(data.twr ?? undefined)}
          pct={metricPct(data.twr ?? undefined)}
        />
        <ReturnStat
          label={tr("returns.simple")}
          value={data.simple_return ? metricValue(data.simple_return) : "—"}
          pct={data.simple_return ? metricPct(data.simple_return) : null}
        />
      </div>

      <div className="mt-2 text-[11px] text-muted-foreground tabular-nums">
        {tr("returns.txCount")}: {data.transaction_count}
      </div>
    </Card>
  );
}

function ReturnStat({ label, value, pct }: { label: string; value: string; pct: number | null }) {
  // tone: 中国市场涨红跌绿
  const tone = pct === null ? "neutral" : pct >= 0 ? "up" : "down";
  return (
    <div className="rounded-lg bg-muted/30 px-2 py-1.5 text-center">
      <div className="text-[11px] text-muted-foreground mb-0.5">{label}</div>
      <div className={`text-sm font-bold tabular-nums ${pnlClass(tone === "up" ? 1 : tone === "down" ? -1 : 0)}`}>
        {value}
      </div>
    </div>
  );
}

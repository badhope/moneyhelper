/** 净资产大图卡：总资产 + 资产组成饼图 + 负债列表 */

import { useMemo, useRef } from "react";
import { Landmark, TrendingUp } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useEChart, usePalette } from "@/lib/charts";
import { useI18n } from "@/lib/i18n";
import { fmtMoney } from "@/lib/format";
import { useNetWorth, type NetWorthBreakdown } from "@/lib/use-calculations";
import type { EChartsCoreOption } from "echarts/core";

function NetWorthPie({ breakdown }: { breakdown: NetWorthBreakdown["asset_breakdown"] }) {
  const ref = useRef<HTMLDivElement>(null);
  const palette = usePalette();
  const option = useMemo<EChartsCoreOption | null>(() => {
    const items = Object.entries(breakdown)
      .filter(([, value]) => value > 0)
      .map(([label, value]) => ({ label, value }));
    if (items.length === 0) return null;
    return {
      tooltip: { trigger: "item", triggerOn: "click", renderMode: "richText", confine: true, formatter: `{b}\n¥{c}` },
      series: [{
        // 必须留中心孔：卡上在圆心叠了「总资产 / 金额」两行文字，
        // 实心饼会把它们压在扇区上（截图里"总资产"几乎看不清）。
        type: "pie", radius: ["48%", "64%"], center: ["50%", "50%"],
        avoidLabelOverlap: true, itemStyle: { borderRadius: 4, borderColor: "transparent", borderWidth: 2 },
        label: { show: false }, emphasis: { label: { show: true, fontSize: 11, fontWeight: 600 } },
        data: items.map((d, i) => ({ name: d.label, value: d.value, itemStyle: { color: palette[i % 3] } })),
      }],
    };
  }, [breakdown, palette]);
  useEChart(ref, option, [option]);
  return <div ref={ref} className="h-44 w-full" />;
}

function StatRow({ label, value, tone }: { label: string; value: number; tone?: "up" | "down" }) {
  return (
    <div className="flex items-baseline gap-3 text-xs">
      <span className="flex-1 text-muted-foreground">{label}</span>
      <span
        className={`w-24 shrink-0 text-right tabular-nums ${
          tone === "up" ? "text-up" : tone === "down" ? "text-down" : "text-foreground"
        }`}
      >
        {fmtMoney(value)}
      </span>
    </div>
  );
}

export function NetWorthCard() {
  const { t: tr } = useI18n();
  const palette = usePalette();
  const { data, isLoading, isError } = useNetWorth();

  if (isLoading) {
    return (
      <Card className="p-[var(--card-pad)]">
        <Skeleton className="h-4 w-20 mb-3" />
        <Skeleton className="h-8 w-36 mb-3" />
        <Skeleton className="h-36 w-full" />
      </Card>
    );
  }
  if (isError || !data) {
    return (
      <Card className="p-[var(--card-pad)]">
        <div className="text-sm text-muted-foreground">{tr("netWorth.loadFail")}</div>
      </Card>
    );
  }

  const hasPieData = Object.values(data.asset_breakdown ?? {}).some((v) => v > 0);
  // 防御旧服务端/中间版本缺字段：null 保护，避免整卡被 ErrorBoundary 兜成"页面出错"
  const assets = data.asset_breakdown ?? {};
  const liabilities = data.liability_breakdown ?? {};

  return (
    <Card className="p-[var(--card-pad)]">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2 text-sm font-medium">
          <TrendingUp className="w-4 h-4 text-primary" />
          {tr("netWorth.title")}
        </div>
        <Badge variant={data.net_worth >= 0 ? "ok" : "warn"}>
          {data.net_worth >= 0 ? tr("netWorth.positive") : tr("netWorth.negative")}
        </Badge>
      </div>

      <div className="flex items-baseline gap-1.5 mb-3">
        <span className="text-2xl font-bold tabular-nums">{fmtMoney(data.net_worth)}</span>
        <span className="text-xs text-muted-foreground">{tr("netWorth.total")}</span>
      </div>

      <div className="grid max-w-3xl items-start gap-6 sm:grid-cols-[13rem_20rem]">
        {hasPieData ? (
          <div className="relative">
            <NetWorthPie breakdown={assets} />
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-[10px] text-muted-foreground">{tr("netWorth.assets")}</span>
              <span className="text-[13px] font-semibold tabular-nums">{fmtMoney(data.total_assets, false, true)}</span>
            </div>
          </div>
        ) : null}
        <div className={hasPieData ? "w-full space-y-2" : "grid grid-cols-2 gap-x-6 gap-y-1.5"}>
          <StatRow label={tr("netWorth.assets")} value={data.total_assets} tone="up" />
          {Object.entries(assets).map(([label, value], i) => (
            <div key={label} className="flex items-baseline gap-3 text-xs">
              <span className="flex min-w-0 flex-1 items-center gap-1.5">
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ background: palette[i % 3] }}
                />
                <span className="truncate text-muted-foreground">{label}</span>
              </span>
              <span className="w-24 shrink-0 text-right tabular-nums text-foreground">{fmtMoney(value)}</span>
            </div>
          ))}
          <StatRow label={tr("netWorth.liability")} value={data.total_liabilities} tone="down" />
        </div>
      </div>

      {/* 负债明细 */}
      {Object.keys(liabilities).length > 0 && (
        <div className="mt-3 pt-3 border-t border-border/60">
          <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground mb-2">
            <Landmark className="w-3.5 h-3.5" />
            {tr("netWorth.liabilityDetail")}
          </div>
          <div className="space-y-1.5">
            {Object.entries(liabilities).map(([name, balance]) => {
              const rate = data.liability_rates?.[name] ?? 0;
              return (
                <div key={name} className="flex items-center justify-between text-xs">
                  <span>
                    {name}
                    {rate > 0 && <span className="text-muted-foreground ml-1.5">{(rate * 100).toFixed(2)}%</span>}
                  </span>
                  <span className="text-down tabular-nums">{fmtMoney(balance)}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </Card>
  );
}

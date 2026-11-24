/** 财税时序看板（4.17.1）：总账已过账凭证的月度时间轴。
 *
 * 口径只来自后端 `/api/finance/timeline`；前端不补零、不推算税局状态。
 * 没有期间的月份显示“缺账”，避免把空月看成 0 收入。
 */

import { useMemo, useRef } from "react";
import type { EChartsCoreOption } from "echarts/core";
import { AlertTriangle, CalendarRange } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useEChart, usePalette, axisLabelColor } from "@/lib/charts";
import { useTheme } from "@/lib/theme";
import { fmtMoney, pnlClass } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { useFinanceTimeline, type TimelineMonth } from "@/lib/use-finance-tax";

function statusBadge(m: TimelineMonth, t: (k: string) => string) {
  if (m.status === "closed") return <Badge variant="ok">{t("tax.timelineStatusClosed")}</Badge>;
  if (m.status === "open") return <Badge variant="warn">{t("tax.timelineStatusOpen")}</Badge>;
  return <Badge variant="muted">{t("tax.timelineStatusMissing")}</Badge>;
}

export function TaxTimelinePanel() {
  const { t } = useI18n();
  const { data, isLoading, error } = useFinanceTimeline(6);
  const ref = useRef<HTMLDivElement>(null);
  const palette = usePalette();
  const { resolved } = useTheme();

  const option = useMemo<EChartsCoreOption | null>(() => {
    if (!data || data.period_count === 0) return null;
    const months = data.months;
    return {
      tooltip: {
        trigger: "axis",
        renderMode: "richText",
        confine: true,
        formatter: (p: unknown) => {
          const raw = p as { seriesName: string; value: number | null; axisValue: string }[];
          const arr = raw.filter((x) => x.value !== null && x.value !== undefined);
          return [
            raw[0]?.axisValue ?? "",
            ...arr.map((x) => `${x.seriesName}: ${fmtMoney(Number(x.value))}`),
            arr.length === 0 ? t("tax.timelineStatusMissing") : "",
          ].filter(Boolean).join("\n");
        },
      },
      legend: { top: 0, textStyle: { fontSize: 10, color: axisLabelColor(resolved) } },
      grid: { left: 8, right: 8, top: 34, bottom: 8, containLabel: true },
      xAxis: {
        type: "category",
        data: months.map((m) => m.month.slice(5)),
        axisLabel: { fontSize: 10, color: axisLabelColor(resolved) },
        axisLine: { lineStyle: { color: axisLabelColor(resolved), opacity: 0.3 } },
      },
      yAxis: {
        type: "value",
        axisLabel: {
          fontSize: 10,
          color: axisLabelColor(resolved),
          formatter: (v: number) => (Math.abs(v) >= 10000 ? `${Math.round(v / 10000)}万` : String(v)),
        },
        splitLine: { lineStyle: { opacity: 0.15 } },
      },
      series: [
        {
          name: t("tax.timelineIncome"),
          type: "bar",
          data: months.map((m) => (m.status === "missing" ? null : m.income)),
          itemStyle: { color: palette[2], borderRadius: [3, 3, 0, 0] },
          barMaxWidth: 18,
        },
        {
          name: t("tax.timelineExpense"),
          type: "bar",
          data: months.map((m) => (m.status === "missing" ? null : m.expense)),
          itemStyle: { color: palette[5], borderRadius: [3, 3, 0, 0] },
          barMaxWidth: 18,
        },
        {
          name: t("tax.timelineProfit"),
          type: "line",
          data: months.map((m) => (m.status === "missing" ? null : m.profit)),
          lineStyle: { width: 2, color: palette[0] },
          itemStyle: { color: palette[0] },
          symbolSize: 5,
        },
        {
          name: t("tax.timelineCashNet"),
          type: "line",
          data: months.map((m) => (m.status === "missing" ? null : m.cash_net)),
          lineStyle: { width: 2, type: "dashed", color: palette[4] },
          itemStyle: { color: palette[4] },
          symbolSize: 4,
        },
      ],
    };
  }, [data, palette, resolved, t]);

  useEChart(ref, option, [option]);

  if (isLoading) {
    return (
      <Card className="p-[var(--card-pad)]">
        <Skeleton className="mb-3 h-4 w-40" />
        <Skeleton className="h-56 w-full" />
      </Card>
    );
  }
  if (error) {
    return (
      <Card className="p-[var(--card-pad)]">
        <div className="flex items-center gap-2 text-[12px] text-down">
          <AlertTriangle className="h-4 w-4" />
          {error instanceof Error ? error.message : String(error)}
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      <Card className="p-[var(--card-pad)]">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <div className="flex items-center gap-1.5 text-[13px] font-medium">
              <CalendarRange className="h-4 w-4 text-primary" />
              {t("tax.timelineTitle")}
            </div>
            <p className="mt-1 max-w-2xl text-[11.5px] leading-relaxed text-muted-foreground">
              {t("tax.timelineDesc")}
            </p>
          </div>
          {data ? (
            <div className="flex gap-1.5 text-[10.5px]">
              <Badge variant="muted">{t("tax.timelinePeriods", { n: String(data.period_count) })}</Badge>
              {data.missing_count > 0 ? (
                <Badge variant="warn">
                  {t("tax.timelineMissing", { n: String(data.missing_count) })}
                </Badge>
              ) : null}
            </div>
          ) : null}
        </div>

        {data && data.period_count > 0 ? (
          <div ref={ref} className="mt-3 h-60 w-full" />
        ) : (
          <EmptyState mode="compact" text={t("tax.timelineEmpty")} />
        )}
      </Card>

      {data && data.period_count > 0 ? (
        <Card className="p-[var(--card-pad)]">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-[11.5px]">
              <thead>
                <tr className="border-b border-border text-left text-[10.5px] text-muted-foreground">
                  <th className="py-1.5 pr-3 font-medium">{t("tax.timelineMonth")}</th>
                  <th className="py-1.5 pr-3 font-medium">{t("tax.timelineStatus")}</th>
                  <th className="py-1.5 pr-3 text-right font-medium">{t("tax.timelineIncome")}</th>
                  <th className="py-1.5 pr-3 text-right font-medium">{t("tax.timelineExpense")}</th>
                  <th className="py-1.5 pr-3 text-right font-medium">{t("tax.timelineProfit")}</th>
                  <th className="py-1.5 pr-3 text-right font-medium">{t("tax.timelineTaxNet")}</th>
                  <th className="py-1.5 text-right font-medium">{t("tax.timelineCashNet")}</th>
                </tr>
              </thead>
              <tbody>
                {data.months.map((m) => (
                  <tr key={m.month} className="border-b border-border/60 last:border-0">
                    <td className="py-1.5 pr-3 font-medium tabular-nums">{m.month}</td>
                    <td className="py-1.5 pr-3">{statusBadge(m, t)}</td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">
                      {m.status === "missing" ? "—" : fmtMoney(m.income)}
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">
                      {m.status === "missing" ? "—" : fmtMoney(m.expense)}
                    </td>
                    <td
                      className={`py-1.5 pr-3 text-right tabular-nums ${
                        m.status === "missing" ? "text-muted-foreground" : pnlClass(m.profit)
                      }`}
                    >
                      {m.status === "missing" ? "—" : fmtMoney(m.profit, true)}
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">
                      {m.status === "missing" ? "—" : fmtMoney(m.tax_net)}
                    </td>
                    <td
                      className={`py-1.5 text-right tabular-nums ${
                        m.status === "missing" ? "text-muted-foreground" : pnlClass(m.cash_net)
                      }`}
                    >
                      {m.status === "missing" ? "—" : fmtMoney(m.cash_net, true)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[10.5px] leading-relaxed text-muted-foreground">
            {t("tax.timelineBoundary")}
          </p>
        </Card>
      ) : null}
    </div>
  );
}

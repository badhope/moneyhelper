/** 支出树图：按分类的支出占比与绝对额，一块面积同时表达两件事。
 *
 * 为什么用树图而不是饼图：分类多时饼图的扇区会细到无法点击，
 * 树图用面积编码金额，大小对比更直观，且能再分一层子项（未来接预算分类）。
 */

import { useMemo, useRef } from "react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useEChart, usePalette, axisLabelColor } from "@/lib/charts";
import { useTheme } from "@/lib/theme";
import { useI18n } from "@/lib/i18n";
import { fmtMoney } from "@/lib/format";
import { useDashboard } from "@/lib/store";
import type { EChartsCoreOption } from "echarts/core";

export function ExpenseTreemapCard() {
  const { t } = useI18n();
  const { dashboard: data, loading } = useDashboard();
  const ref = useRef<HTMLDivElement>(null);
  const palette = usePalette();
  const { resolved } = useTheme();

  const option = useMemo<EChartsCoreOption | null>(() => {
    const cats = (data?.cashflow?.by_category ?? []) as { category: string; amount: number }[];
    const items = cats.filter((c) => Number(c.amount) > 0);
    if (items.length === 0) return null;
    const total = items.reduce((s, c) => s + Number(c.amount), 0);
    return {
      tooltip: {
        renderMode: "richText",
        confine: true,
        formatter: (p: { name: string; value: number }) =>
          `${p.name}: ${fmtMoney(p.value)}（${((p.value / total) * 100).toFixed(1)}%）`,
      },
      series: [
        {
          type: "treemap",
          roam: false,
          nodeClick: false,
          breadcrumb: { show: false },
          width: "100%",
          height: "100%",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          itemStyle: { borderColor: "transparent", borderWidth: 2, gapWidth: 2 },
          label: {
            show: true,
            fontSize: 11,
            color: "#fff",
            formatter: (p: { name: string; value: number }) =>
              `${p.name}\n${((p.value / total) * 100).toFixed(0)}%`,
          },
          data: items.map((c, i) => ({
            name: c.category,
            value: Number(c.amount),
            itemStyle: { color: palette[i % palette.length] },
          })),
        },
      ],
    };
  }, [data, palette]);

  useEChart(ref, option, [option], undefined, ["treemap"]);

  if (loading) {
    return (
      <Card className="p-[var(--card-pad)]">
        <Skeleton className="h-4 w-24 mb-3" />
        <Skeleton className="h-40 w-full" />
      </Card>
    );
  }
  if (!option) return null;

  const cats = (data?.cashflow?.by_category ?? []) as { category: string; amount: number }[];
  const top = cats[0];
  return (
    <Card className="p-[var(--card-pad)]">
      <h3 className="mb-1 text-sm font-medium">{t("chart.expenseTree")}</h3>
      <p className="mb-2 text-xs text-muted-foreground">
        {top
          ? t("chart.expenseTreeHint", { cat: top.category, amount: fmtMoney(Number(top.amount)) })
          : t("chart.noData")}
      </p>
      <div ref={ref} className="h-40 w-full" />
      <div className="mt-2 space-y-1">
        {cats.slice(0, 5).map((c, i) => (
          <div key={c.category} className="flex items-center justify-between text-[11px]">
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <span
                className="inline-block h-2 w-2 rounded-sm"
                style={{ background: palette[i % palette.length] }}
              />
              {c.category}
            </span>
            <span className="tabular-nums" style={{ color: axisLabelColor(resolved) }}>
              {fmtMoney(Number(c.amount))}
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}

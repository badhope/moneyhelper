/** 健康五维雷达：一次看清五个维度的强弱，短板一眼可见。
 *
 * 为什么用雷达：五个维度的分数放进柱状图会变成"五根柱子比高矮"，
 * 读者需要自己在脑子里拼出形状；雷达图直接把"形状是否饱满"摆出来，
 * 短板（凹陷的那一角）自然凸显。
 */

import { useMemo, useRef } from "react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useEChart, usePalette, axisLabelColor } from "@/lib/charts";
import { useTheme } from "@/lib/theme";
import { useI18n } from "@/lib/i18n";
import { useHealthScore } from "@/lib/use-calculations";
import type { EChartsCoreOption } from "echarts/core";

export function HealthRadarCard() {
  const { t } = useI18n();
  const { data, isLoading } = useHealthScore();
  const ref = useRef<HTMLDivElement>(null);
  const palette = usePalette();
  const { resolved } = useTheme();

  const option = useMemo<EChartsCoreOption | null>(() => {
    if (!data) return null;
    // breakdown 是 { dimKey: { score, max, label, detail } }
    const entries = Object.entries(data.breakdown ?? {});
    if (entries.length === 0) return null;
    const indicators = entries.map(([key, v]) => ({
      name: v.label || key,
      max: Number(v.max ?? 100),
    }));
    const values = entries.map(([, v]) => Number(v.score ?? 0));
    return {
      tooltip: { renderMode: "richText", confine: true },
      radar: {
        indicator: indicators,
        radius: "62%",
        center: ["50%", "54%"],
        splitNumber: 4,
        axisName: { fontSize: 10, color: axisLabelColor(resolved) },
        splitLine: { lineStyle: { opacity: 0.2 } },
        splitArea: { show: false },
        axisLine: { lineStyle: { opacity: 0.2 } },
      },
      series: [
        {
          type: "radar",
          data: [
            {
              value: values,
              name: t("chart.health"),
              areaStyle: { opacity: 0.25 },
              lineStyle: { width: 2, color: palette[0] },
              itemStyle: { color: palette[0] },
            },
          ],
        },
      ],
    };
  }, [data, palette, resolved, t]);

  useEChart(ref, option, [option], undefined, ["radar"]);

  if (isLoading) {
    return (
      <Card className="p-[var(--card-pad)]">
        <Skeleton className="h-4 w-24 mb-3" />
        <Skeleton className="h-48 w-full" />
      </Card>
    );
  }
  if (!option) return null;

  const entries = Object.entries(data?.breakdown ?? {});
  const weakest = entries.length
    ? entries.reduce((a, b) => (Number(b[1].score) < Number(a[1].score) ? b : a))
    : null;

  return (
    <Card className="p-[var(--card-pad)]">
      <div className="mb-1 flex items-baseline justify-between">
        <h3 className="text-sm font-medium">{t("chart.healthRadar")}</h3>
        <span className="text-xs tabular-nums text-muted-foreground">
          {data?.score ?? "—"} · {data?.grade ?? ""}
        </span>
      </div>
      <p className="mb-1 text-xs text-muted-foreground">
        {weakest
          ? t("chart.healthHint", {
              dim: weakest[1].label || weakest[0],
              score: Math.round(Number(weakest[1].score ?? 0)),
            })
          : t("chart.noData")}
      </p>
      <div ref={ref} className="h-48 w-full" />
    </Card>
  );
}

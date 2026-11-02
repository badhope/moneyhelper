import { useMemo, useRef } from "react";
import { useEChart, usePalette, axisLabelColor } from "@/lib/charts";
import { useTheme } from "@/lib/theme";
import { useI18n } from "@/lib/i18n";
import { fmtMoney } from "@/lib/format";
import type { Position } from "@/lib/types";

/**
 * 持仓盈亏贡献：横向条形图（股票软件"个股贡献度"的常见形态）。
 *
 * 为什么需要它：持仓页表格只列单只标的的盈亏，用户看不出"今天这些钱到底
 * 是哪几只赚/亏出来的"。这里按盈亏绝对值排序，一眼看清贡献结构。
 * 零值或空持仓时不渲染，避免出现一根空坐标轴。
 */
export function PositionContributionCard({ positions, compact }: { positions: Position[]; compact: boolean }) {
  const { t } = useI18n();
  const { resolved } = useTheme();
  const palette = usePalette();
  const ref = useRef<HTMLDivElement>(null);

  const rows = useMemo(
    () =>
      positions
        .filter((p) => p.kind !== "现金" && p.pnl !== 0)
        .sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl))
        .slice(0, 8),
    [positions],
  );

  const option = useMemo(() => {
    if (!rows.length) return null;
    // 图表自下而上绘制：反转后盈亏最大的排在最上面
    const data = [...rows].reverse();
    const label = axisLabelColor(resolved);
    const maxAbs = Math.max(...data.map((p) => Math.abs(p.pnl)), 1);
    const hasNegative = data.some((p) => p.pnl < 0);
    return {
      // 左右各留出标签位：负值标签在条左侧，正值标签在条右侧，都不压条
      grid: { left: 8, right: 8, top: 6, bottom: 6, containLabel: true },
      // 盈亏是「相对零轴的方向性」数据。零轴必须居中且可见：
      // 正值向右、负值向左，否则亏损条会看起来也朝右延伸，被读成盈利。
      xAxis: {
        type: "value",
        show: false,
        min: hasNegative ? -maxAbs : 0,
        max: maxAbs,
      },
      yAxis: {
        type: "category",
        data: data.map((p) => p.name),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: label, fontSize: 11, width: 104, overflow: "truncate" },
      },
      series: [
        {
          type: "bar",
          data: data.map((p, i) => ({
            value: p.pnl,
            itemStyle: {
              color: p.pnl >= 0 ? "#dc2626" : "#059669",
              // 圆角只给「远离零轴的那一端」，让方向一眼可辨
              borderRadius: p.pnl >= 0 ? [0, 3, 3, 0] : [3, 0, 0, 3],
            },
            // 用序号占位，避免依赖原始顺序
            _i: i,
          })),
          barWidth: 12,
          label: {
            show: true,
            // 正值标签在条右端、负值在条左端（都是远离零轴的方向）
            position: "right",
            distance: 6,
            fontSize: 11,
            color: label,
            formatter: (p: { value: number }) => fmtMoney(p.value, true, compact),
          },
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { color: label, width: 1, type: "solid", opacity: 0.35 },
            label: { show: false },
            data: [{ xAxis: 0 }],
          },
        },
      ],
      tooltip: {
        trigger: "item",
        confine: true,
        formatter: (p: { name: string; value: number }) =>
          `${p.name}<br/>${t("dash.totalPnl")} ${fmtMoney(p.value, true, compact)}`,
      },
      color: palette,
    };
  }, [rows, resolved, palette, compact, t]);

  useEChart(ref, option, [option]);

  if (!rows.length) return null;

  return (
    <div className="mt-3 border-t border-border/60 pt-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium">{t("dash.pnlContribution")}</span>
        <span className="text-[11px] text-muted-foreground">{t("dash.pnlContributionHint")}</span>
      </div>
      <div ref={ref} className="h-[15rem] w-full" />
    </div>
  );
}

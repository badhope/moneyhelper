import { useQuery } from "@tanstack/react-query";
import { TrendingUp } from "lucide-react";
import { useEChart, usePalette, axisLabelColor } from "@/lib/charts";
import { useTheme } from "@/lib/theme";
import { useI18n } from "@/lib/i18n";
import { api } from "@/lib/api";
import { fmtMoney, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useRef } from "react";

/**
 * 净值趋势与变动归因：回答「这个月净值涨了，是存下来的还是市场涨的」。
 *
 * 为什么值得单独一张卡：净资产一个数字看不出质量。同样涨 3 万，
 * 靠省吃俭用存下来的可持续，靠行情涨的不可复制——这两个来源的意义完全不同。
 * Empower / Kubera / Sharesight 都把「净储蓄 vs 投资收益」拆分当作核心指标。
 *
 * 数据不足时明确说明「明天再来看」，绝不拿当前值倒推历史（那是伪造）。
 */

type HistoryPoint = { date: string; net_worth: number; assets: number; liabilities: number };
type History = {
  points: HistoryPoint[];
  count: number;
  available: boolean;
  reason?: string;
  start?: string;
  end?: string;
  change?: number;
  change_pct?: number | null;
};
type Attribution = {
  available: boolean;
  reason?: string;
  change?: number;
  savings?: number;
  investment_pnl?: number;
  debt_effect?: number;
  other?: number;
  shares?: { savings_pct: number | null; investment_pct: number | null; debt_pct: number | null };
  note?: string;
  start_date?: string;
  end_date?: string;
};

export function NetWorthTrendCard() {
  const { t, lang } = useI18n();
  const l = lang?.startsWith("en") ? "en" : "zh";
  const { resolved } = useTheme();
  const palette = usePalette();
  const ref = useRef<HTMLDivElement>(null);

  const hist = useQuery({
    queryKey: ["calcs", "net-worth-history", l],
    queryFn: () => api<History>(`/api/calculations/net-worth/history?days=180`),
    staleTime: 60_000,
    retry: false,
  });
  const attr = useQuery({
    queryKey: ["calcs", "net-worth-attribution", l],
    queryFn: () => api<Attribution>(`/api/calculations/net-worth/attribution?days=31`),
    staleTime: 60_000,
    retry: false,
    enabled: Boolean(hist.data?.available),
  });

  const data = hist.data;
  const points = data?.points ?? [];

  const option = (() => {
    if (points.length < 2) return null;
    return {
      grid: { left: 6, right: 12, top: 12, bottom: 4, containLabel: true },
      xAxis: {
        type: "category",
        data: points.map((p) => p.date.slice(5)),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: axisLabelColor(resolved), fontSize: 10, interval: "auto" },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { opacity: 0.15 } },
        axisLabel: { color: axisLabelColor(resolved), fontSize: 10 },
      },
      tooltip: {
        trigger: "axis",
        confine: true,
        formatter: (ps: { dataIndex: number }[]) => {
          const i = ps?.[0]?.dataIndex ?? 0;
          const p = points[i];
          return `${p.date}<br/>${t("nw.netWorth")} ${fmtMoney(p.net_worth)}`;
        },
      },
      series: [
        {
          type: "line",
          data: points.map((p) => p.net_worth),
          smooth: 0.2,
          showSymbol: false,
          lineStyle: { width: 2, color: palette[0] },
          areaStyle: { opacity: 0.08, color: palette[0] },
        },
      ],
      color: palette,
    };
  })();

  useEChart(ref, option, [option]);

  // 没有历史（或只有一天）时：给一句明确的下一步，而不是空卡片
  if (!data || !data.available) {
    return (
      <section className="rounded-xl border border-border/70 bg-card px-4 py-3">
        <div className="flex items-center gap-1.5">
          <TrendingUp className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-medium">{t("nw.title")}</h2>
        </div>
        <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted-foreground">
          {data?.reason ?? t("nw.collecting")}
        </p>
      </section>
    );
  }

  const a = attr.data;
  const rows = a?.available
    ? [
        { key: "savings", label: t("nw.savings"), value: a.savings ?? 0, tone: "text-foreground" },
        { key: "investment", label: t("nw.investment"), value: a.investment_pnl ?? 0, tone: "text-foreground" },
        { key: "debt", label: t("nw.debt"), value: a.debt_effect ?? 0, tone: "text-foreground" },
      ]
    : [];

  return (
    <section className="rounded-xl border border-border/70 bg-card">
      <header className="flex items-baseline justify-between gap-2 border-b border-border/60 px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          <TrendingUp className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-medium">{t("nw.title")}</h2>
          <span className="text-[11px] text-muted-foreground">{data.start} → {data.end}</span>
        </div>
        <div className="text-right">
          <div className={cn("text-[15px] font-semibold tabular-nums", (data.change ?? 0) >= 0 ? "text-up" : "text-down")}>
            {fmtMoney(data.change, true)}
          </div>
          <div className="text-[11px] text-muted-foreground">{fmtPct(data.change_pct ?? null, true)}</div>
        </div>
      </header>

      <div ref={ref} className="h-36 w-full px-2 pt-1" />

      {a?.available && (
        <div className="border-t border-border/60 px-4 py-2.5">
          <div className="mb-1.5 text-[11px] text-muted-foreground">{t("nw.attribution")}</div>
          <ul className="space-y-1">
            {rows.map((r) => (
              <li key={r.key} className="flex items-center justify-between text-[12.5px]">
                <span className="text-muted-foreground">{r.label}</span>
                <span className={cn("tabular-nums", r.tone)}>{fmtMoney(r.value, true)}</span>
              </li>
            ))}
            {Math.abs(a.other ?? 0) > 0.01 && (
              <li className="flex items-center justify-between text-[12.5px] text-muted-foreground">
                <span>{t("nw.other")}</span>
                <span className="tabular-nums">{fmtMoney(a.other, true)}</span>
              </li>
            )}
          </ul>
          {a.note && <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground/80">{a.note}</p>}
        </div>
      )}
    </section>
  );
}

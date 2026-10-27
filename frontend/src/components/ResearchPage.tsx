/** 股票投研工作台（v4.1 深化版）。
 *
 * 对标「团队炒股」类项目的投研面板：一只股票 = 一张决策看板。
 * 1. 现价条：实时行情（东财/新浪）+ 多空倾向
 * 2. 技术面指标卡：MA 排列 / RSI / MACD / BOLL / KDJ
 * 3. K 线主图：蜡烛（A股红涨绿跌）+ MA5/20/60 + 布林带切换 + 日/周/月周期切换 + 缩放重置
 * 4. 信号流：规则引擎输出的金叉/死叉/超买超卖/突破
 * 5. 统计预测：线性趋势 + 蒙特卡洛 GBM 分位区间带（固定种子可复现）
 * 6. 策略回测：双均线 / 定投切换 + 可调参数 + 指标条 + 资金曲线 + 交易回合明细
 *
 * 全部数值由后端确定性引擎计算；行情/预测/回测不可用时逐块降级展示原因。
 */

import { useMemo, useRef, useState } from "react";
import type { EChartsType } from "echarts/core";
import {
  Activity,
  LineChart,
  RefreshCw,
  Search,
  TrendingDown,
  TrendingUp,
  Undo2,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { StatCell } from "@/components/ui/stat";
import { useEChart, usePalette, useCandleColors, axisLabelColor } from "@/lib/charts";
import { useTheme } from "@/lib/theme";
import { fmtMoney, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  useResearchAnalyze,
  useResearchBacktest,
  useResearchForecast,
  type BacktestResult,
  type ForecastResult,
  type TechnicalResult,
} from "@/lib/use-research";

const BIAS_META: Record<string, { label: string; cls: string }> = {
  bull: { label: "偏多", cls: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" },
  bear: { label: "偏空", cls: "bg-red-500/10 text-red-600 dark:text-red-400" },
  neutral: { label: "中性", cls: "bg-muted text-muted-foreground" },
};

const SIGNAL_STYLE: Record<string, string> = {
  bull: "text-up",
  bear: "text-down",
  neutral: "text-muted-foreground",
};

const PERIODS: { key: "daily" | "weekly" | "monthly"; label: string }[] = [
  { key: "daily", label: "日 K" },
  { key: "weekly", label: "周 K" },
  { key: "monthly", label: "月 K" },
];

function TechnicalCard({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "up" | "down" | "muted" }) {
  const cls = tone === "up" ? "text-up" : tone === "down" ? "text-down" : tone === "muted" ? "text-muted-foreground" : "text-foreground";
  return (
    <div className="min-w-0 rounded-lg bg-muted/25 px-3 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("mt-1 truncate text-[15px] font-semibold tabular-nums num-in", cls)}>{value}</div>
      {hint ? <div className="mt-0.5 truncate text-[11px] text-muted-foreground/80">{hint}</div> : null}
    </div>
  );
}

/** K 线主图：蜡烛（A股红涨绿跌）+ MA + 布林带（多序列 toggle）+ 周期切换 + 缩放重置 */
function KlineChart({ series, period, onPeriod }: { series: TechnicalResult["series"]; period: string; onPeriod: (p: "daily" | "weekly" | "monthly") => void }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<EChartsType | null>(null);
  const palette = usePalette();
  const { up, down } = useCandleColors();
  const { resolved } = useTheme();
  const [showBoll, setShowBoll] = useState(false);
  const axisColor = axisLabelColor(resolved);

  const option = useMemo(() => {
    const dates = series.dates;
    const kdata = series.ohlc;
    return {
      backgroundColor: "transparent",
      animation: false,
      grid: [
        { left: 52, right: 16, top: 24, height: "58%" },
        { left: 52, right: 16, top: "78%", height: "15%" },
      ],
      axisPointer: { link: [{ xAxisIndex: "all" }], label: { backgroundColor: "#64748b" } },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
        backgroundColor: resolved === "dark" ? "#1e293b" : "#fff",
        borderColor: "#64748b40",
        textStyle: { color: resolved === "dark" ? "#e2e8f0" : "#0f172a", fontSize: 12 },
      },
      xAxis: [
        { type: "category", data: dates, gridIndex: 0, axisLabel: { color: axisColor, fontSize: 10 }, axisLine: { lineStyle: { color: "#64748b60" } } },
        { type: "category", gridIndex: 1, axisLabel: { show: false }, axisLine: { lineStyle: { color: "#64748b60" } }, data: dates },
      ],
      yAxis: [
        { scale: true, gridIndex: 0, splitLine: { lineStyle: { color: "#64748b20" } }, axisLabel: { color: axisColor, fontSize: 10 } },
        { scale: true, gridIndex: 1, splitLine: { show: false }, axisLabel: { color: axisColor, fontSize: 10 } },
      ],
      dataZoom: [
        { type: "inside", xAxisIndex: [0, 1], start: 45, end: 100 },
        { type: "slider", xAxisIndex: [0, 1], bottom: 0, height: 14, start: 45, end: 100, borderColor: "#64748b40", textStyle: { color: axisColor } },
      ],
      series: [
        {
          name: "K线",
          type: "candlestick",
          data: kdata,
          itemStyle: {
            color: up,           // 阳线（收>开）= 涨 = 红（A股惯例）
            color0: down,        // 阴线（收<开）= 跌 = 绿
            borderColor: up,
            borderColor0: down,
          },
        },
        { name: "MA20", type: "line", data: series.ma20, symbol: "none", lineStyle: { width: 1.2, color: palette[4] }, smooth: true },
        { name: "MA60", type: "line", data: series.ma60, symbol: "none", lineStyle: { width: 1.2, color: palette[7] }, smooth: true },
        ...(showBoll
          ? [
              { name: "BOLL上轨", type: "line", data: series.boll_upper, symbol: "none", lineStyle: { width: 1, type: "dashed", color: palette[2] }, smooth: true },
              { name: "BOLL中轨", type: "line", data: series.boll_mid, symbol: "none", lineStyle: { width: 1, type: "dashed", color: palette[5] }, smooth: true },
              { name: "BOLL下轨", type: "line", data: series.boll_lower, symbol: "none", lineStyle: { width: 1, type: "dashed", color: palette[6] }, smooth: true },
            ]
          : []),
        {
          name: "成交量",
          type: "bar",
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: series.volume.map((v, i) => {
            const isUp = series.close[i] != null && series.ohlc[i] != null ? series.close[i]! >= series.ohlc[i]![1] : false;
            return { value: v ?? 0, itemStyle: { color: isUp ? up + "99" : down + "99" } };
          }),
          barWidth: "60%",
        },
      ],
      legend: {
        top: 0,
        left: 0,
        textStyle: { color: axisColor, fontSize: 10 },
        data: ["MA5", "MA20", "MA60", "BOLL上轨", "BOLL中轨", "BOLL下轨"],
        selected: { "BOLL上轨": showBoll, "BOLL中轨": showBoll, "BOLL下轨": showBoll },
      },
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series, palette, resolved, showBoll, up, down]);

  useEChart(ref, option, [option], (chart) => {
    chartRef.current = chart;
  });

  return (
    <div className="flex flex-col">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-medium">K 线走势</div>
        <div className="flex items-center gap-1.5">
          {/* 周期切换 */}
          <div className="flex gap-0.5 rounded-lg bg-muted/40 p-0.5 text-[11px]">
            {PERIODS.map((p) => (
              <button
                key={p.key}
                type="button"
                onClick={() => onPeriod(p.key)}
                className={cn(
                  "rounded-md px-2 py-0.5 transition-colors",
                  period === p.key ? "bg-background font-medium shadow-sm" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => setShowBoll((v) => !v)}
            className={cn(
              "rounded-md px-2 py-1 text-xs transition-colors",
              showBoll ? "bg-primary/10 text-primary" : "bg-muted/30 text-muted-foreground hover:text-foreground",
            )}
          >
            {showBoll ? "隐藏布林带" : "叠加布林带"}
          </button>
          <button
            type="button"
            onClick={() => chartRef.current?.dispatchAction({ type: "dataZoom", start: 45, end: 100 })}
            className="rounded-md bg-muted/30 px-2 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
            title="重置缩放"
          >
            <Undo2 className="h-3 w-3" />
          </button>
        </div>
      </div>
      <div ref={ref} className="h-[320px] w-full" />
    </div>
  );
}

/** 统计预测面板：实际收盘 + 线性趋势 + 蒙特卡洛中值/分位区间带 */
function ForecastPanel({ forecast: f, loading, unavailable }: { forecast: ForecastResult | undefined; loading: boolean; unavailable: string | undefined }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const palette = usePalette();
  const { up, down } = useCandleColors();
  const { resolved } = useTheme();
  const axisColor = axisLabelColor(resolved);

  const option = useMemo(() => {
    if (!f) return null;
    const dates = f.dates;
    // 区间带宽 = p95 - p5，与 p5 堆叠成带
    const band = f.p5.map((v, i) => (v != null && f.p95[i] != null ? f.p95[i]! - v : null));
    return {
      backgroundColor: "transparent",
      animation: false,
      color: [palette[0], palette[4], palette[2], up, up],
      tooltip: {
        trigger: "axis",
        backgroundColor: resolved === "dark" ? "#1e293b" : "#fff",
        textStyle: { color: resolved === "dark" ? "#e2e8f0" : "#0f172a" },
      },
      legend: { top: 0, left: 0, textStyle: { color: axisColor, fontSize: 11 }, data: ["收盘", "线性趋势", "蒙特卡洛中值", "5%-95% 区间"] },
      grid: { left: 56, right: 16, top: 32, bottom: 24 },
      xAxis: { type: "category", data: dates, axisLabel: { color: axisColor, fontSize: 10, interval: Math.floor(dates.length / 8) }, axisLine: { lineStyle: { color: "#64748b60" } } },
      yAxis: { scale: true, splitLine: { lineStyle: { color: "#64748b20" } }, axisLabel: { color: axisColor, fontSize: 10 } },
      series: [
        { name: "收盘", type: "line", data: f.close, symbol: "none", lineStyle: { width: 1.4, color: palette[0] } },
        { name: "线性趋势", type: "line", data: f.trend_line, symbol: "none", lineStyle: { width: 1.2, type: "dashed", color: palette[4] } },
        { name: "蒙特卡洛中值", type: "line", data: f.median, symbol: "none", lineStyle: { width: 1.4, type: "dashed", color: palette[2] } },
        { name: "区间下限", type: "line", data: f.p5, stack: "band", symbol: "none", lineStyle: { opacity: 0 }, tooltip: { show: false } },
        { name: "5%-95% 区间", type: "line", data: band, stack: "band", symbol: "none", lineStyle: { opacity: 0 }, areaStyle: { color: f.bias === "up" ? up + "26" : down + "26" }, tooltip: { show: false } },
      ],
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [f, palette, resolved, axisColor, up, down]);

  useEChart(ref, option, [option]);

  if (loading) return <Skeleton className="h-[220px] w-full" />;
  if (unavailable) return <EmptyState illustration="search" mode="compact" text={unavailable} />;
  if (!f) return null;

  const items: { label: string; value: string; tone?: "up" | "down" }[] = [
    { label: "趋势倾向", value: f.bias === "up" ? "偏多" : f.bias === "down" ? "偏空" : "中性", tone: f.bias === "up" ? "up" : f.bias === "down" ? "down" : undefined },
    { label: "趋势斜率/期", value: f.slope_pct != null ? `${f.slope_pct >= 0 ? "+" : ""}${f.slope_pct.toFixed(2)}%` : "—", tone: f.slope_pct != null ? (f.slope_pct >= 0 ? "up" : "down") : undefined },
    { label: "年化波动率", value: f.vol_annual_pct != null ? `${f.vol_annual_pct.toFixed(1)}%` : "—" },
    { label: "MA20 偏离", value: f.mean_reversion_pct != null ? `${f.mean_reversion_pct >= 0 ? "+" : ""}${f.mean_reversion_pct.toFixed(1)}%` : "—", tone: f.mean_reversion_pct != null ? (f.mean_reversion_pct >= 0 ? "up" : "down") : undefined },
  ];

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 divide-x divide-border/70 overflow-hidden rounded-lg border border-border/70 bg-background sm:grid-cols-4">
        {items.map((it) => (
          <StatCell key={it.label} label={it.label} value={it.value} tone={it.tone} />
        ))}
      </div>
      <div ref={ref} className="h-[220px] w-full" />
      <div className="text-[11px] text-muted-foreground/70">{f.note}</div>
    </div>
  );
}

/** 回测指标条 + 资金曲线 + 参数控件 + 交易回合明细 */
function BacktestPanel({
  result,
  loading,
  unavailable,
  strategy,
  params,
  onParams,
}: {
  result: BacktestResult | undefined;
  loading: boolean;
  unavailable: string | undefined;
  strategy: "ma_cross" | "dca";
  params: { fast: number; slow: number; invest_amount: number; freq_days: number };
  onParams: (p: Partial<{ fast: number; slow: number; invest_amount: number; freq_days: number }>) => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const palette = usePalette();
  const { resolved } = useTheme();
  const axisColor = axisLabelColor(resolved);

  const option = useMemo(() => {
    if (!result) return null;
    return {
      backgroundColor: "transparent",
      animation: false,
      color: [palette[0], palette[3]],
      tooltip: { trigger: "axis", backgroundColor: resolved === "dark" ? "#1e293b" : "#fff", textStyle: { color: resolved === "dark" ? "#e2e8f0" : "#0f172a" } },
      legend: { top: 0, left: 0, textStyle: { color: axisColor, fontSize: 11 }, data: ["策略净值", "买入持有"] },
      grid: { left: 56, right: 16, top: 32, bottom: 24 },
      xAxis: { type: "category", data: result.curve.dates, axisLabel: { color: axisColor, fontSize: 10, interval: Math.floor(result.curve.dates.length / 6) }, axisLine: { lineStyle: { color: "#64748b60" } } },
      yAxis: { scale: true, splitLine: { lineStyle: { color: "#64748b20" } }, axisLabel: { color: axisColor, fontSize: 10 } },
      series: [
        { name: "策略净值", type: "line", data: result.curve.strategy, symbol: "none", lineStyle: { width: 2, color: palette[0] }, areaStyle: { color: palette[0] + "22" } },
        { name: "买入持有", type: "line", data: result.curve.benchmark, symbol: "none", lineStyle: { width: 1.2, type: "dashed", color: palette[3] } },
      ],
    };
  }, [result, palette, resolved, axisColor]);

  useEChart(ref, option, [option]);

  if (loading) return <Skeleton className="h-[260px] w-full" />;
  if (unavailable) return <EmptyState illustration="search" mode="compact" text={unavailable} />;
  if (!result) return null;

  const items: { label: string; value: string; tone?: "up" | "down" }[] = [
    { label: "策略总收益", value: fmtPct(result.total_return_pct), tone: (result.total_return_pct ?? 0) >= 0 ? "up" : "down" },
    { label: "同期买入持有", value: fmtPct(result.benchmark_return_pct), tone: (result.benchmark_return_pct ?? 0) >= 0 ? "up" : "down" },
    { label: "最大回撤", value: fmtPct(result.max_drawdown_pct), tone: "down" },
    { label: "夏普比率", value: result.sharpe !== null && result.sharpe !== undefined ? result.sharpe.toFixed(2) : "—" },
    ...(strategy === "ma_cross"
      ? [
          { label: "胜率", value: result.win_rate_pct !== null && result.win_rate_pct !== undefined ? `${result.win_rate_pct}%` : "—" },
          { label: "交易回合", value: `${result.rounds ?? 0}` },
        ]
      : [
          { label: "累计投入", value: fmtMoney(result.total_invested ?? 0, false, true) },
          { label: "期末市值", value: fmtMoney(result.final_value ?? 0, false, true) },
        ]),
  ];

  // 交易回合明细（双均线才有）：买卖配对展示
  const trades = result.trades ?? [];
  const pairs = trades.slice(-12).map((t) => ({ date: t.date, action: t.side, price: t.price, amount: t.amount }));

  return (
    <div className="flex flex-col gap-3">
      {/* 参数控件 */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {strategy === "ma_cross" ? (
          <>
            <label className="flex items-center gap-1.5 text-muted-foreground">
              快线
              <input
                type="number"
                min={2}
                max={60}
                value={params.fast}
                onChange={(e) => onParams({ fast: Math.max(2, Math.min(60, Number(e.target.value) || 2)) })}
                className="w-14 rounded-md border border-border/70 bg-background px-1.5 py-1 text-center tabular-nums outline-none focus:border-primary"
              />
            </label>
            <label className="flex items-center gap-1.5 text-muted-foreground">
              慢线
              <input
                type="number"
                min={5}
                max={120}
                value={params.slow}
                onChange={(e) => onParams({ slow: Math.max(5, Math.min(120, Number(e.target.value) || 5)) })}
                className="w-14 rounded-md border border-border/70 bg-background px-1.5 py-1 text-center tabular-nums outline-none focus:border-primary"
              />
            </label>
            <span className="text-[11px] text-muted-foreground/70">改参数即重新回测（含交易成本 0.03%/边）</span>
          </>
        ) : (
          <>
            <label className="flex items-center gap-1.5 text-muted-foreground">
              每期金额
              <input
                type="number"
                min={1}
                step={100}
                value={params.invest_amount}
                onChange={(e) => onParams({ invest_amount: Math.max(1, Number(e.target.value) || 1) })}
                className="w-20 rounded-md border border-border/70 bg-background px-1.5 py-1 text-center tabular-nums outline-none focus:border-primary"
              />
            </label>
            <label className="flex items-center gap-1.5 text-muted-foreground">
              间隔(交易日)
              <input
                type="number"
                min={1}
                max={60}
                value={params.freq_days}
                onChange={(e) => onParams({ freq_days: Math.max(1, Math.min(60, Number(e.target.value) || 1)) })}
                className="w-14 rounded-md border border-border/70 bg-background px-1.5 py-1 text-center tabular-nums outline-none focus:border-primary"
              />
            </label>
            <span className="text-[11px] text-muted-foreground/70">改参数即重新回测</span>
          </>
        )}
      </div>

      <div className="grid grid-cols-2 divide-x divide-border/70 overflow-hidden rounded-lg border border-border/70 bg-background sm:grid-cols-6">
        {items.map((it) => (
          <StatCell key={it.label} label={it.label} value={it.value} tone={it.tone} />
        ))}
      </div>
      <div ref={ref} className="h-[240px] w-full" />

      {pairs.length > 0 ? (
        <div className="overflow-hidden rounded-lg border border-border/70">
          <div className="border-b border-border/70 bg-muted/20 px-3 py-1.5 text-[11px] font-medium text-muted-foreground">
            最近交易回合（最多 12 笔）
          </div>
          <div className="max-h-40 overflow-auto">
            <table className="w-full text-[12px]">
              <tbody>
                {pairs.map((t, i) => (
                  <tr key={`${t.date}-${i}`} className="border-b border-border/40 last:border-0">
                    <td className="px-3 py-1 tabular-nums text-muted-foreground">{t.date}</td>
                    <td className={cn("px-3 py-1 font-medium", t.action === "buy" ? "text-up" : "text-down")}>
                      {t.action === "buy" ? "买入" : "卖出"}
                    </td>
                    <td className="px-3 py-1 text-right tabular-nums">{fmtMoney(t.price)}</td>
                    <td className="px-3 py-1 text-right tabular-nums text-muted-foreground">{fmtMoney(t.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function ResearchPage() {
  const [symbol, setSymbol] = useState<string>("600519");
  const [submitted, setSubmitted] = useState<string>("600519");
  const [strategy, setStrategy] = useState<"ma_cross" | "dca">("ma_cross");
  const [period, setPeriod] = useState<"daily" | "weekly" | "monthly">("daily");
  const [btParams, setBtParams] = useState({ fast: 5, slow: 20, invest_amount: 1000, freq_days: 5 });

  const analyze = useResearchAnalyze(submitted.trim() || null, period);
  const backtest = useResearchBacktest(submitted.trim() || null, strategy, btParams);
  const forecastQ = useResearchForecast(submitted.trim() || null, period, 20);
  const tech = analyze.data?.technical;
  const quote = analyze.data?.quote;

  const seriesWithOhlc = tech?.series;

  const bias = tech ? BIAS_META[tech.bias] : null;

  const submit = () => {
    const s = symbol.trim();
    if (s) setSubmitted(s);
  };

  return (
    <div className="flex flex-col gap-4">
      {/* 搜索条 */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1 sm:max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder="输入 A 股代码，如 600519"
            className="w-full rounded-lg border border-border/70 bg-background py-2 pl-8 pr-3 text-sm outline-none transition-colors focus:border-primary"
            aria-label="股票代码"
          />
        </div>
        <Button size="sm" onClick={submit} disabled={analyze.isFetching}>
          <RefreshCw className={cn("mr-1.5 h-3.5 w-3.5", analyze.isFetching && "animate-spin")} />
          分析
        </Button>
      </div>

      {analyze.isLoading ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-[320px] w-full" />
          <Skeleton className="h-[260px] w-full" />
        </div>
      ) : analyze.data?.available === false ? (
        <EmptyState illustration="search" title="无法分析该标的" desc={analyze.data.reason ?? "行情源不可用"} />
      ) : tech && analyze.data ? (
        <>
          {/* 现价条 */}
          <div className="grid grid-cols-2 divide-x divide-border/70 overflow-hidden rounded-lg border border-border/70 bg-background sm:grid-cols-6">
            <StatCell
              label={`${quote?.name || submitted} (${submitted})`}
              value={quote?.price != null ? fmtMoney(quote.price) : "—"}
              sub={quote?.source === "eastmoney" ? "东方财富实时" : "行情快照"}
              tone={quote && quote.change_pct != null ? (quote.change_pct >= 0 ? "up" : "down") : "default"}
              emphasis
            />
            <StatCell
              label="涨跌幅"
              value={quote?.change_pct != null ? fmtPct(quote.change_pct, true) : "—"}
              tone={quote && quote.change_pct != null ? (quote.change_pct >= 0 ? "up" : "down") : "default"}
            />
            <StatCell label="RSI(14)" value={tech.last.rsi != null ? tech.last.rsi.toFixed(1) : "—"} sub={tech.last.rsi != null ? (tech.last.rsi > 70 ? "超买区" : tech.last.rsi < 30 ? "超卖区" : "中性区") : undefined} />
            <StatCell label="MACD" value={tech.last.hist != null ? fmtMoney(tech.last.hist) : "—"} sub={tech.last.dif != null && tech.last.dea != null ? `DIF ${tech.last.dif.toFixed(3)} / DEA ${tech.last.dea.toFixed(3)}` : undefined} tone={tech.last.hist != null ? (tech.last.hist >= 0 ? "up" : "down") : "default"} />
            <StatCell label="MA20" value={tech.last.ma.ma20 != null ? fmtMoney(tech.last.ma.ma20) : "—"} sub={tech.last.ma.ma20 != null ? (tech.last.close >= tech.last.ma.ma20 ? "价格在其上" : "价格在其下") : undefined} tone={tech.last.ma.ma20 != null ? (tech.last.close >= tech.last.ma.ma20 ? "up" : "down") : "default"} />
            <div className="flex min-w-0 items-center justify-center px-3">
              {bias ? (
                <Badge className={cn("gap-1", bias.cls)}>
                  {tech.bias === "bull" ? <TrendingUp className="h-3.5 w-3.5" /> : tech.bias === "bear" ? <TrendingDown className="h-3.5 w-3.5" /> : <Activity className="h-3.5 w-3.5" />}
                  {bias.label} · {tech.bull_count}多/{tech.bear_count}空
                </Badge>
              ) : null}
            </div>
          </div>

          {/* 技术指标卡 */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <TechnicalCard
              label="均线排列"
              value={(() => {
                const ma = tech.last.ma;
                const above = ["ma5", "ma10", "ma20"].filter((k) => ma[k] != null && tech.last.close >= ma[k]!).length;
                return `${above}/3 在价上`;
              })()}
              hint={`MA5 ${tech.last.ma.ma5 != null ? tech.last.ma.ma5.toFixed(2) : "—"} · MA10 ${tech.last.ma.ma10 != null ? tech.last.ma.ma10.toFixed(2) : "—"} · MA60 ${tech.last.ma.ma60 != null ? tech.last.ma.ma60.toFixed(2) : "—"}`}
              tone={tech.last.close >= (tech.last.ma.ma20 ?? Infinity) ? "up" : "down"}
            />
            <TechnicalCard
              label="布林带位置"
              value={
                tech.last.boll.upper != null && tech.last.boll.lower != null
                  ? tech.last.close > tech.last.boll.upper
                    ? "突破上轨"
                    : tech.last.close < tech.last.boll.lower
                      ? "跌破下轨"
                      : "带内运行"
                  : "—"
              }
              hint={
                tech.last.boll.upper != null && tech.last.boll.lower != null
                  ? `上 ${tech.last.boll.upper.toFixed(2)} · 下 ${tech.last.boll.lower.toFixed(2)}`
                  : undefined
              }
              tone={
                tech.last.boll.upper != null && tech.last.boll.lower != null
                  ? tech.last.close > tech.last.boll.upper
                    ? "up"
                    : tech.last.close < tech.last.boll.lower
                      ? "down"
                      : "muted"
                  : "muted"
              }
            />
            <TechnicalCard
              label="KDJ"
              value={tech.last.kdj.k != null ? tech.last.kdj.k.toFixed(1) : "—"}
              hint={tech.last.kdj.k != null && tech.last.kdj.d != null ? `D ${tech.last.kdj.d.toFixed(1)} · J ${tech.last.kdj.j != null ? tech.last.kdj.j.toFixed(1) : "—"}` : undefined}
              tone={tech.last.kdj.k != null && tech.last.kdj.d != null ? (tech.last.kdj.k > tech.last.kdj.d ? "up" : "down") : "muted"}
            />
            <TechnicalCard
              label="数据量"
              value={`${tech.point_count} 根`}
              hint={`识别 ${tech.signals.length} 条信号`}
              tone="muted"
            />
          </div>

          {/* K 线主图 */}
          <Card className="p-3">
            {seriesWithOhlc ? (
              <KlineChart series={seriesWithOhlc} period={period} onPeriod={setPeriod} />
            ) : (
              <EmptyState illustration="search" mode="compact" text="K 线数据不可用" />
            )}
          </Card>

          {/* 信号流 */}
          {tech.signals.length > 0 ? (
            <Card className="p-3">
              <div className="mb-2 text-sm font-medium">技术信号流（近 12 条）</div>
              <div className="flex flex-col gap-1.5">
                {tech.signals.map((s, i) => (
                  <div key={`${s.date}-${s.code}-${i}`} className="flex items-center gap-2 text-[13px]">
                    <span className="w-20 shrink-0 text-muted-foreground tabular-nums">{s.date || "—"}</span>
                    <span className={cn("font-medium", SIGNAL_STYLE[s.side])}>
                      {s.side === "bull" ? "▲" : s.side === "bear" ? "▼" : "◆"} {s.text}
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          ) : null}

          {/* 统计预测 */}
          <Card className="p-3">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Activity className="h-4 w-4 text-primary" />
                价格统计预测（未来 20 期）
              </div>
              {forecastQ.isFetching ? (
                <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                  <RefreshCw className="h-3 w-3 animate-spin" /> 计算中…
                </span>
              ) : null}
            </div>
            <ForecastPanel
              forecast={forecastQ.data?.forecast}
              loading={forecastQ.isLoading}
              unavailable={forecastQ.data?.available === false ? forecastQ.data.reason : undefined}
            />
          </Card>

          {/* 文字结论 */}
          {analyze.data.trend_text ? (
            <Card className="p-3">
              <div className="mb-1 text-sm font-medium">技术面结论</div>
              <pre className="whitespace-pre-wrap font-sans text-[13px] leading-relaxed text-muted-foreground">{analyze.data.trend_text}</pre>
              {analyze.data.disclaimer ? <div className="mt-1 text-[11px] text-muted-foreground/70">{analyze.data.disclaimer}</div> : null}
            </Card>
          ) : null}

          {/* 策略回测 */}
          <Card className="p-3">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-sm font-medium">
                <LineChart className="h-4 w-4 text-primary" />
                策略回测
              </div>
              <div className="flex gap-1 rounded-lg bg-muted/40 p-1 text-xs">
                {(["ma_cross", "dca"] as const).map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setStrategy(s)}
                    className={cn(
                      "rounded-md px-2.5 py-1 transition-colors",
                      strategy === s ? "bg-background font-medium shadow-sm" : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {s === "ma_cross" ? "双均线(5/20)" : "定投"}
                  </button>
                ))}
              </div>
            </div>
            <BacktestPanel
              result={backtest.data?.result}
              loading={backtest.isLoading}
              unavailable={backtest.data?.available === false ? backtest.data.reason : undefined}
              strategy={strategy}
              params={btParams}
              onParams={(p) => setBtParams((old) => ({ ...old, ...p }))}
            />
          </Card>
        </>
      ) : null}
    </div>
  );
}

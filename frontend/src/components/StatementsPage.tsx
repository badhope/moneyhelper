/** 企业财报分析工作台（v4.0 财务工作台核心页）。
 *
 * 对标券商研报的财务分析模块：贴入三表 JSON → 20+ 指标看板。
 * 1. 输入区：JSON 编辑框 + 示例数据 + 分析（可选保存到本地）
 * 2. 指标卡：盈利能力 / 偿债能力 / 营运能力 / 现金流质量 四组
 * 3. 趋势图：营收&净利、盈利比率、偿债比率、经营现金流
 * 4. 财务雷达图：最新期五维盈利/效率形状
 * 5. 异常预警流 + 模板报告文本
 * 6. 历史记录：本地保存的三表，可重新加载/删除
 *
 * 全部数值由后端确定性引擎计算（报表口径还原，非审计、非投资建议）。
 */

import { useMemo, useRef, useState } from "react";
import { AlertTriangle, FileText, Plus, Save, Trash2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { useEChart, usePalette, useCandleColors, axisLabelColor } from "@/lib/charts";
import { useTheme } from "@/lib/theme";
import { api } from "@/lib/api";
import { fmtMoney, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  useStatementAnalyze,
  useStatementDelete,
  useStatementList,
  useStatementSave,
  type StatementAnalysis,
} from "@/lib/use-research";

/** 示例三表：一家高杠杆+低现金流质量的制造企业（能触发多条预警） */
const SAMPLE_PAYLOAD = `{
  "company": "示例制造公司",
  "currency": "CNY",
  "periods": [
    {
      "period": "2023-12-31",
      "balance_sheet": {
        "total_assets": 1000000, "total_liabilities": 600000, "total_equity": 400000,
        "current_assets": 300000, "current_liabilities": 350000,
        "cash_and_equivalents": 60000, "inventory": 120000, "accounts_receivable": 90000, "goodwill": 250000
      },
      "income_statement": {
        "revenue": 800000, "gross_profit": 320000, "operating_profit": 100000,
        "net_profit": 70000, "ebit": 105000, "interest_expense": 15000
      },
      "cashflow_statement": {
        "operating_cashflow": 20000, "investing_cashflow": -120000, "financing_cashflow": 80000
      }
    },
    {
      "period": "2024-12-31",
      "balance_sheet": {
        "total_assets": 1300000, "total_liabilities": 800000, "total_equity": 500000,
        "current_assets": 260000, "current_liabilities": 400000,
        "cash_and_equivalents": 50000, "inventory": 180000, "accounts_receivable": 160000, "goodwill": 250000
      },
      "income_statement": {
        "revenue": 900000, "gross_profit": 300000, "operating_profit": 90000,
        "net_profit": 60000, "ebit": 100000, "interest_expense": 20000
      },
      "cashflow_statement": {
        "operating_cashflow": -15000, "investing_cashflow": -150000, "financing_cashflow": 120000
      }
    }
  ]
}`;

function fmt(v: number | null | undefined, suffix = ""): string {
  return v != null ? `${v.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}${suffix}` : "—";
}

function MetricCell({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "up" | "down" | "muted" }) {
  const cls = tone === "up" ? "text-up" : tone === "down" ? "text-down" : tone === "muted" ? "text-muted-foreground" : "text-foreground";
  return (
    <div className="min-w-0 rounded-lg bg-muted/25 px-3 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("mt-1 truncate text-[15px] font-semibold tabular-nums num-in", cls)}>{value}</div>
      {hint ? <div className="mt-0.5 truncate text-[11px] text-muted-foreground/80">{hint}</div> : null}
    </div>
  );
}

function TrendChart({ title, periods, series }: { title: string; periods: string[]; series: { name: string; data: (number | null)[]; suffix?: string; secondary?: boolean }[] }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const palette = usePalette();
  const { resolved } = useTheme();
  const axisColor = axisLabelColor(resolved);

  const option = useMemo(() => {
    return {
      backgroundColor: "transparent",
      animation: false,
      color: palette,
      tooltip: {
        trigger: "axis",
        backgroundColor: resolved === "dark" ? "#1e293b" : "#fff",
        textStyle: { color: resolved === "dark" ? "#e2e8f0" : "#0f172a", fontSize: 12 },
        valueFormatter: (v: number | null) => (v == null ? "—" : Number(v).toLocaleString("zh-CN", { maximumFractionDigits: 2 })),
      },
      legend: { top: 0, right: 0, textStyle: { color: axisColor, fontSize: 10 } },
      grid: { left: 56, right: 16, top: 32, bottom: 24 },
      xAxis: { type: "category", data: periods, axisLabel: { color: axisColor, fontSize: 10 }, axisLine: { lineStyle: { color: "#64748b60" } } },
      yAxis: [
        { type: "value", scale: true, splitLine: { lineStyle: { color: "#64748b20" } }, axisLabel: { color: axisColor, fontSize: 10 } },
        ...(series.some((s) => s.secondary)
          ? [{ type: "value", scale: true, splitLine: { show: false }, axisLabel: { color: axisColor, fontSize: 10 } }]
          : []),
      ],
      series: series.map((s, i) => ({
        name: s.name,
        type: "line",
        data: s.data,
        yAxisIndex: s.secondary ? 1 : 0,
        symbol: "circle",
        symbolSize: 5,
        lineStyle: { width: s.secondary ? 1.2 : 2 },
        areaStyle: i === 0 ? { color: palette[i] + "1a" } : undefined,
        connectNulls: true,
      })),
    };
  }, [periods, series, palette, resolved, axisColor]);

  useEChart(ref, option, [option]);

  return (
    <div className="flex flex-col">
      <div className="mb-1 text-sm font-medium">{title}</div>
      <div ref={ref} className="h-[220px] w-full" />
    </div>
  );
}

function RadarChart({ latest }: { latest: Record<string, number | null> }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const palette = usePalette();
  const { resolved } = useTheme();
  const axisColor = axisLabelColor(resolved);

  const option = useMemo(() => {
    // 五维盈利/效率形状（量纲一致：百分比）
    const dims: { name: string; value: number | null; max: number }[] = [
      { name: "毛利率", value: latest.gross_margin_pct, max: 60 },
      { name: "净利率", value: latest.net_margin_pct, max: 30 },
      { name: "ROE", value: latest.roe_pct, max: 30 },
      { name: "营业利润率", value: latest.operating_margin_pct, max: 30 },
      { name: "现金营收比", value: latest.ocf_ratio_pct, max: 30 },
    ];
    const values = dims.map((d) => (d.value != null ? Math.min(100, Math.max(0, (d.value / d.max) * 100)) : 0));
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: { backgroundColor: resolved === "dark" ? "#1e293b" : "#fff", textStyle: { color: resolved === "dark" ? "#e2e8f0" : "#0f172a" } },
      radar: {
        indicator: dims.map((d) => ({ name: d.name, max: 100 })),
        radius: "62%",
        axisName: { color: axisColor, fontSize: 11 },
        splitLine: { lineStyle: { color: "#64748b30" } },
        splitArea: { areaStyle: { color: ["#ffffff00", "#64748b10"] } },
        axisLine: { lineStyle: { color: "#64748b40" } },
      },
      series: [
        {
          type: "radar",
          data: [{ value: values, name: "最新期", areaStyle: { color: palette[0] + "33" }, lineStyle: { color: palette[0] }, itemStyle: { color: palette[0] } }],
        },
      ],
      legend: { show: false },
    };
  }, [latest, palette, resolved, axisColor]);

  useEChart(ref, option, [option]);

  return (
    <div className="flex flex-col">
      <div className="mb-1 text-sm font-medium">最新期财务雷达（五维 × 满分归一）</div>
      <div ref={ref} className="h-[240px] w-full" />
      <div className="text-[11px] text-muted-foreground/70">雷达值为五维指标相对满分（毛利率 60%、其余 30%）的归一位置，用于看盈利结构形状，非绝对评分。</div>
    </div>
  );
}

/** 现金流三流堆叠柱状图（经营 / 投资 / 筹资） */
function CashflowStackChart({ result }: { result: StatementAnalysis }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const palette = usePalette();
  const { up } = useCandleColors();
  const { resolved } = useTheme();
  const axisColor = axisLabelColor(resolved);
  const stack = result.trends.cashflow_stack;

  const option = useMemo(() => {
    if (!stack) return null;
    const periods = result.trends.periods;
    return {
      backgroundColor: "transparent",
      animation: false,
      color: [up, palette[1], palette[7]],
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        backgroundColor: resolved === "dark" ? "#1e293b" : "#fff",
        textStyle: { color: resolved === "dark" ? "#e2e8f0" : "#0f172a", fontSize: 12 },
        valueFormatter: (v: number | null) => (v == null ? "—" : fmtMoney(v, true, true)),
      },
      legend: { top: 0, right: 0, textStyle: { color: axisColor, fontSize: 10 }, data: ["经营现金流", "投资现金流", "筹资现金流"] },
      grid: { left: 64, right: 16, top: 32, bottom: 24 },
      xAxis: { type: "category", data: periods, axisLabel: { color: axisColor, fontSize: 10 }, axisLine: { lineStyle: { color: "#64748b60" } } },
      yAxis: { type: "value", splitLine: { lineStyle: { color: "#64748b20" } }, axisLabel: { color: axisColor, fontSize: 10 } },
      series: [
        { name: "经营现金流", type: "bar", stack: "cf", data: stack.operating, barWidth: "46%" },
        { name: "投资现金流", type: "bar", stack: "cf", data: stack.investing, barWidth: "46%" },
        { name: "筹资现金流", type: "bar", stack: "cf", data: stack.financing, barWidth: "46%" },
      ],
    };
  }, [stack, result.trends.periods, palette, resolved, axisColor, up]);

  useEChart(ref, option, [option]);

  if (!stack) return null;
  return (
    <div className="flex flex-col">
      <div className="mb-1 text-sm font-medium">现金流结构（经营 / 投资 / 筹资）</div>
      <div ref={ref} className="h-[220px] w-full" />
      <div className="text-[11px] text-muted-foreground/70">
        {(() => {
          // 最新期三流合计 = 现金净增加额
          const n = stack.operating.length - 1;
          const total =
            (stack.operating[n] ?? 0) + (stack.investing[n] ?? 0) + (stack.financing[n] ?? 0);
          return total !== 0
            ? `最新期现金净增加额约 ${fmtMoney(total, true, true)}（经营+投资+筹资）`
            : "最新期三流数据缺失，无法汇总净增加额";
        })()}
      </div>
    </div>
  );
}

/** 杜邦拆解条图：ROE = 净利率 × 总资产周转率 × 权益乘数（量纲归一展示） */
function DupontChart({ dupont }: { dupont: StatementAnalysis["dupont"] }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const palette = usePalette();
  const { resolved } = useTheme();
  const axisColor = axisLabelColor(resolved);

  const option = useMemo(() => {
    // 三因子统一归一（%）：净利率直接用 %；周转率 ×100 转 %；权益乘数 ×100 转 %
    const rows: { name: string; value: number | null; max: number }[] = [
      { name: "净利率", value: dupont.net_margin_pct, max: 40 },
      { name: "总资产周转率", value: dupont.asset_turnover != null ? dupont.asset_turnover * 100 : null, max: 200 },
      { name: "权益乘数", value: dupont.equity_multiplier != null ? dupont.equity_multiplier * 100 : null, max: 300 },
    ];
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        backgroundColor: resolved === "dark" ? "#1e293b" : "#fff",
        textStyle: { color: resolved === "dark" ? "#e2e8f0" : "#0f172a" },
        valueFormatter: (v: number | null) => (v == null ? "—" : `${v.toFixed(1)}（归一%）`),
      },
      grid: { left: 16, right: 90, top: 16, bottom: 16, containLabel: true },
      xAxis: { type: "value", axisLabel: { show: false }, splitLine: { show: false } },
      yAxis: { type: "category", inverse: true, data: rows.map((r) => r.name), axisLabel: { color: axisColor, fontSize: 11 }, axisLine: { show: false }, axisTick: { show: false } },
      series: [
        {
          type: "bar",
          barWidth: 18,
          data: rows.map((r, i) => ({
            value: r.value != null ? Math.min(r.max, Math.max(0, r.value)) : null,
            itemStyle: { color: dupont.complete ? palette[i] : "#64748b55", borderRadius: 4 },
            // 用 label 显示真实值
          })),
          label: {
            show: true,
            position: "right",
            color: axisColor,
            fontSize: 11,
            formatter: (p: { dataIndex: number }) => {
              const r = rows[p.dataIndex];
              if (r.value == null) return "—";
              const name = r.name;
              return name === "净利率"
                ? `${dupont.net_margin_pct?.toFixed(2)}%`
                : name === "总资产周转率"
                  ? `${dupont.asset_turnover?.toFixed(2)} 次`
                  : `${dupont.equity_multiplier?.toFixed(2)} 倍`;
            },
          },
        },
      ],
    };
  }, [dupont, palette, resolved, axisColor]);

  useEChart(ref, option, [option]);

  return (
    <div className="flex flex-col">
      <div className="mb-1 text-sm font-medium">杜邦拆解（ROE = 净利率 × 周转率 × 权益乘数）</div>
      <div ref={ref} className="h-[150px] w-full" />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px]">
        <span>
          净利率 <b className="tabular-nums">{dupont.net_margin_pct != null ? `${dupont.net_margin_pct}%` : "—"}</b>
        </span>
        <span className="text-muted-foreground">×</span>
        <span>
          总资产周转率 <b className="tabular-nums">{dupont.asset_turnover != null ? `${dupont.asset_turnover} 次` : "—"}</b>
        </span>
        <span className="text-muted-foreground">×</span>
        <span>
          权益乘数 <b className="tabular-nums">{dupont.equity_multiplier != null ? `${dupont.equity_multiplier} 倍` : "—"}</b>
        </span>
        <span className="text-muted-foreground">=</span>
        <span>
          ROE <b className="tabular-nums text-up">{dupont.roe_pct != null ? `${dupont.roe_pct}%` : "—"}</b>
        </span>
        {!dupont.complete ? <span className="text-[11px] text-amber-500/90">（部分因子数据缺失，拆解不完整）</span> : null}
      </div>
    </div>
  );
}

/** 多期指标对比明细表：periods × 关键指标 */
const TABLE_ROWS: { label: string; key: string; fmt?: (v: number | null) => string }[] = [
  { label: "营业收入", key: "revenue", fmt: (v) => fmtMoney(v ?? 0, true, true) },
  { label: "净利润", key: "net_profit", fmt: (v) => fmtMoney(v ?? 0, true, true) },
  { label: "毛利率", key: "gross_margin_pct", fmt: (v) => fmtPct(v) },
  { label: "净利率", key: "net_margin_pct", fmt: (v) => fmtPct(v) },
  { label: "ROE", key: "roe_pct", fmt: (v) => fmtPct(v) },
  { label: "ROA", key: "roa_pct", fmt: (v) => fmtPct(v) },
  { label: "资产负债率", key: "debt_ratio_pct", fmt: (v) => fmtPct(v) },
  { label: "流动比率", key: "current_ratio", fmt: (v) => fmt(v) },
  { label: "速动比率", key: "quick_ratio", fmt: (v) => fmt(v) },
  { label: "总资产周转率", key: "asset_turnover", fmt: (v) => fmt(v, " 次") },
  { label: "经营现金流", key: "ocf", fmt: (v) => fmtMoney(v ?? 0, true, true) },
  { label: "现金营收比", key: "ocf_ratio_pct", fmt: (v) => fmtPct(v) },
  { label: "营收同比", key: "revenue_yoy_pct", fmt: (v) => fmtPct(v, true) },
  { label: "净利同比", key: "net_profit_yoy_pct", fmt: (v) => fmtPct(v, true) },
];

function ComparisonTable({ result }: { result: StatementAnalysis }) {
  const periods = result.periods;
  return (
    <div className="overflow-hidden rounded-lg border border-border/70">
      <div className="border-b border-border/70 bg-muted/20 px-3 py-1.5 text-[11px] font-medium text-muted-foreground">
        多期指标对比（{periods.length} 期）
      </div>
      <div className="max-h-80 overflow-auto">
        <table className="w-full text-[12px]">
          <thead className="sticky top-0 bg-muted/40 text-left text-[11px] text-muted-foreground">
            <tr>
              <th className="px-3 py-1.5 font-medium">指标</th>
              {periods.map((p) => (
                <th key={p.period} className="px-3 py-1.5 text-right font-medium tabular-nums">{p.period}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {TABLE_ROWS.map((row) => (
              <tr key={row.key} className="border-b border-border/40 last:border-0">
                <td className="px-3 py-1 text-muted-foreground">{row.label}</td>
                {periods.map((p) => {
                  const v = (p.metrics[row.key] as number | null) ?? null;
                  const text = row.fmt ? row.fmt(v) : fmt(v);
                  return (
                    <td key={p.period} className={cn("px-3 py-1 text-right tabular-nums", (row.key === "revenue_yoy_pct" || row.key === "net_profit_yoy_pct" || row.key === "ocf" || row.key === "roe_pct") && v != null ? (v >= 0 ? "text-up" : "text-down") : undefined)}>
                      {text}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function StatementsPage() {
  const [input, setInput] = useState<string>(SAMPLE_PAYLOAD);
  const [payload, setPayload] = useState<Record<string, unknown> | null>(() => {
    try {
      return JSON.parse(SAMPLE_PAYLOAD) as Record<string, unknown>;
    } catch {
      return null;
    }
  });

  const analyze = useStatementAnalyze();
  const save = useStatementSave();
  const del = useStatementDelete();
  const list = useStatementList();

  const result: StatementAnalysis | undefined = analyze.data;
  const parsingError = analyze.isError ? (analyze.error as Error).message : null;
  const [jsonError, setJsonError] = useState<string | null>(null);

  const submit = () => {
    try {
      const parsed = JSON.parse(input) as Record<string, unknown>;
      setPayload(parsed);
      setJsonError(null);
      analyze.mutate(parsed);
    } catch (e) {
      setPayload(null);
      setJsonError(e instanceof Error ? e.message : "JSON 解析失败");
    }
  };

  const latest = result?.latest ?? {};

  const groups: { title: string; items: { label: string; key: string; fmt?: (v: number | null) => string; tone?: "up" | "down" | "muted" }[] }[] = [
    {
      title: "盈利能力",
      items: [
        { label: "毛利率", key: "gross_margin_pct", fmt: (v) => fmtPct(v) },
        { label: "净利率", key: "net_margin_pct", fmt: (v) => fmtPct(v) },
        { label: "ROE", key: "roe_pct", fmt: (v) => fmtPct(v) },
        { label: "ROA", key: "roa_pct", fmt: (v) => fmtPct(v) },
        { label: "营业利润率", key: "operating_margin_pct", fmt: (v) => fmtPct(v) },
      ],
    },
    {
      title: "偿债能力",
      items: [
        { label: "资产负债率", key: "debt_ratio_pct", fmt: (v) => fmtPct(v), tone: "down" },
        { label: "流动比率", key: "current_ratio", fmt: (v) => fmt(v) },
        { label: "速动比率", key: "quick_ratio", fmt: (v) => fmt(v) },
        { label: "利息保障倍数", key: "interest_coverage", fmt: (v) => fmt(v) },
      ],
    },
    {
      title: "营运能力",
      items: [
        { label: "总资产周转率", key: "asset_turnover", fmt: (v) => fmt(v, " 次") },
        { label: "存货周转率", key: "inventory_turnover", fmt: (v) => fmt(v, " 次") },
        { label: "应收账款周转率", key: "receivables_turnover", fmt: (v) => fmt(v, " 次") },
      ],
    },
    {
      title: "现金流质量",
      items: [
        { label: "经营现金流", key: "ocf", fmt: (v) => fmtMoney(v ?? 0, true, true), tone: (latest.ocf ?? 0) >= 0 ? "up" : "down" },
        { label: "现金营收比", key: "ocf_ratio_pct", fmt: (v) => fmtPct(v) },
        { label: "利润含金量", key: "ocf_to_np", fmt: (v) => fmt(v), tone: (latest.ocf_to_np ?? 0) >= 0.5 ? "up" : "down" },
        { label: "营收同比", key: "revenue_yoy_pct", fmt: (v) => fmtPct(v, true), tone: (latest.revenue_yoy_pct ?? 0) >= 0 ? "up" : "down" },
        { label: "净利同比", key: "net_profit_yoy_pct", fmt: (v) => fmtPct(v, true), tone: (latest.net_profit_yoy_pct ?? 0) >= 0 ? "up" : "down" },
      ],
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      {/* 输入区 */}
      <Card className="p-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-medium">
            <FileText className="h-4 w-4 text-primary" />
            三表数据输入（JSON）
          </div>
          <div className="flex gap-1.5">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setInput(SAMPLE_PAYLOAD);
                setPayload(JSON.parse(SAMPLE_PAYLOAD) as Record<string, unknown>);
              }}
            >
              载入示例
            </Button>
            <Button size="sm" onClick={submit} disabled={analyze.isPending}>
              {analyze.isPending ? "分析中…" : "开始分析"}
            </Button>
          </div>
        </div>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          spellCheck={false}
          className="h-48 w-full resize-y rounded-lg border border-border/70 bg-background p-3 font-mono text-xs leading-relaxed outline-none transition-colors focus:border-primary"
          placeholder='{ "company": "公司名", "periods": [ { "period": "2024-12-31", "balance_sheet": {...}, "income_statement": {...}, "cashflow_statement": {...} } ] }'
          aria-label="三表 JSON"
        />
        <div className="mt-1.5 text-[11px] text-muted-foreground/70">
          字段：balance_sheet.total_assets / total_liabilities / total_equity / current_assets / current_liabilities / inventory / accounts_receivable / goodwill；
          income_statement.revenue / gross_profit / operating_profit / net_profit / ebit / interest_expense；
          cashflow_statement.operating_cashflow / investing_cashflow / financing_cashflow。缺字段的指标会标注「—」，不会编造。
        </div>
      </Card>

      {/* 结果区 */}
      {analyze.isPending ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-lg bg-muted/30" />
          ))}
        </div>
      ) : jsonError ? (
        <EmptyState icon={<AlertTriangle className="h-8 w-8 text-red-500/60" />} title="JSON 解析失败" desc={jsonError} />
      ) : parsingError ? (
        <EmptyState icon={<AlertTriangle className="h-8 w-8 text-red-500/60" />} title="分析失败" desc={parsingError} />
      ) : result ? (
        <>
          {/* 标题 + 保存 */}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-base font-semibold">
              {result.company}
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                {result.period_count} 期 · 币种 {result.currency}
              </span>
            </div>
            <div className="flex gap-1.5">
              {save.isPending ? (
                <Button size="sm" disabled>保存中…</Button>
              ) : save.data ? (
                <Badge className="bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">已保存 ✓</Badge>
              ) : (
                <Button size="sm" variant="outline" onClick={() => payload && save.mutate(payload)}>
                  <Save className="mr-1.5 h-3.5 w-3.5" />
                  保存到本地
                </Button>
              )}
            </div>
          </div>

          {/* 指标分组 */}
          <div className="flex flex-col gap-3">
            {groups.map((g) => (
              <Card key={g.title} className="p-3">
                <div className="mb-2 text-sm font-medium text-muted-foreground">{g.title}</div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                  {g.items.map((it) => (
                    <MetricCell
                      key={it.key}
                      label={it.label}
                      value={it.fmt ? it.fmt(latest[it.key] as number | null) : fmt(latest[it.key] as number | null)}
                      tone={it.tone ?? ((latest[it.key] as number | null) ?? 0) >= 0 ? "up" : "down"}
                    />
                  ))}
                </div>
              </Card>
            ))}
          </div>

          {/* 趋势 + 雷达 */}
          <div className="grid gap-3 lg:grid-cols-2">
            <Card className="p-3">
              <TrendChart
                title="营收 & 净利润（元）"
                periods={result.trends.periods}
                series={[
                  { name: "营收", data: result.trends.revenue },
                  { name: "净利润", data: result.trends.net_profit, secondary: true },
                ]}
              />
            </Card>
            <Card className="p-3">
              <TrendChart
                title="盈利比率趋势（%）"
                periods={result.trends.periods}
                series={[
                  { name: "毛利率", data: result.trends.gross_margin },
                  { name: "净利率", data: result.trends.net_margin, secondary: true },
                  { name: "ROE", data: result.trends.roe, secondary: true },
                ]}
              />
            </Card>
            <Card className="p-3">
              <TrendChart
                title="偿债能力趋势"
                periods={result.trends.periods}
                series={[
                  { name: "资产负债率(%)", data: result.trends.debt_ratio },
                  { name: "流动比率", data: result.trends.current_ratio, secondary: true },
                ]}
              />
            </Card>
            <Card className="p-3">
              <TrendChart
                title="经营现金流（元）"
                periods={result.trends.periods}
                series={[{ name: "经营现金流", data: result.trends.ocf }]}
              />
            </Card>
          </div>

          {/* 现金流三流堆叠 + 杜邦拆解 */}
          <div className="grid gap-3 lg:grid-cols-2">
            <Card className="p-3">
              <CashflowStackChart result={result} />
            </Card>
            <Card className="p-3">
              <DupontChart dupont={result.dupont} />
            </Card>
          </div>

          <Card className="p-3">
            <RadarChart latest={latest} />
          </Card>

          {/* 多期对比明细表 */}
          {result.periods.length > 0 ? (
            <Card className="p-3">
              <ComparisonTable result={result} />
            </Card>
          ) : null}

          {/* 预警 */}
          {result.alerts.length > 0 ? (
            <Card className="p-3">
              <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                <AlertTriangle className="h-4 w-4 text-amber-500" />
                异常预警（{result.alerts.length} 项）
              </div>
              <div className="flex flex-col gap-1.5">
                {result.alerts.map((a, i) => (
                  <div key={`${a.code}-${i}`} className="flex items-start gap-2 text-[13px]">
                    <Badge className={cn("mt-0.5 shrink-0", a.level === "bad" ? "bg-red-500/10 text-red-600 dark:text-red-400" : "bg-amber-500/10 text-amber-600 dark:text-amber-400")}>
                      {a.level === "bad" ? "风险" : "关注"}
                    </Badge>
                    <span className="leading-relaxed text-foreground/90">{a.text}</span>
                  </div>
                ))}
              </div>
            </Card>
          ) : (
            <Card className="p-3">
              <div className="text-sm text-emerald-600 dark:text-emerald-400">✓ 未发现明显异常预警项</div>
            </Card>
          )}

          {/* 报告 */}
          <Card className="p-3">
            <div className="mb-1 text-sm font-medium">分析报告</div>
            <pre className="whitespace-pre-wrap font-sans text-[13px] leading-relaxed text-muted-foreground">{result.report_text}</pre>
          </Card>
        </>
      ) : null}

      {/* 历史记录 */}
      <Card className="p-3">
        <div className="mb-2 flex items-center gap-2 text-sm font-medium">
          <FileText className="h-4 w-4 text-primary" />
          本地保存的财报（{list.data?.total ?? 0}）
        </div>
        {list.isLoading ? (
          <div className="h-10 animate-pulse rounded-lg bg-muted/30" />
        ) : list.data && list.data.items.length > 0 ? (
          <div className="flex flex-col divide-y divide-border/60">
            {list.data.items.map((it) => (
              <div key={it.id} className="flex items-center justify-between gap-2 py-2">
                <div className="min-w-0">
                  <div className="truncate text-[13px] font-medium">{it.company}</div>
                  <div className="truncate text-[11px] text-muted-foreground">{it.summary} · {it.created_at?.slice(0, 10)}</div>
                </div>
                <div className="flex shrink-0 gap-1.5">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      void api<{ payload?: Record<string, unknown> }>(`/api/statements/${it.id}`).then((r) => {
                        if (r.payload) {
                          setInput(JSON.stringify(r.payload, null, 2));
                          analyze.mutate(r.payload);
                        }
                      });
                    }}
                  >
                    <Plus className="mr-1 h-3.5 w-3.5" />
                    重新分析
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-red-500/70 hover:text-red-500"
                    onClick={() => del.mutate(it.id)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState illustration="folder" mode="compact" text="还没有保存的财报，分析后可一键保存" />
        )}
      </Card>
    </div>
  );
}

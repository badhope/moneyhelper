/** 团队模拟盘工作台（v4.2）：券商终端式团队炒股看板。
 *
 * 1. 团队摘要条：账户数 / 总资产 / 总收益 / 团队收益率 / 活跃持仓
 * 2. 排行看板：成员收益率横向条形图（红涨绿跌）+ 账户明细行
 * 3. 账户详情：净值曲线（对 1.0 基准）、持仓饼图、持仓表、最近交易
 * 4. 交易区：下单表单（整手校验提示 + 费用预估）+ 开户表单 + 删除账户
 *
 * 数据确定性：持仓/现金由交易事件重放（后端 calculations/paper.py），
 * 估值按最近成交价；下单时前端填现价实现近似实时。模拟数据不构成投资建议。
 */

import { useMemo, useState } from "react";
import { AlertTriangle, Plus, RefreshCw, Trash2, TrendingUp, UserPlus } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { useEChart, usePalette, useCandleColors, axisLabelColor } from "@/lib/charts";
import { useTheme } from "@/lib/theme";
import { fmtMoney, fmtPct, pnlClass, fmtDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  paperDelete,
  paperOpen,
  paperTrade,
  usePaperDetail,
  usePaperList,
  type PaperAccount,
} from "@/lib/use-paper";

function MetricCell({ label, value, tone, hint }: { label: string; value: string; tone?: "up" | "down" | "muted"; hint?: string }) {
  const cls = tone === "up" ? "text-up" : tone === "down" ? "text-down" : tone === "muted" ? "text-muted-foreground" : "text-foreground";
  return (
    <div className="min-w-0 rounded-lg bg-muted/25 px-3 py-2">
      <div className="truncate text-xs text-muted-foreground">{label}</div>
      <div className={cn("mt-1 truncate text-[15px] font-semibold tabular-nums num-in", cls)}>{value}</div>
      {hint ? <div className="mt-0.5 truncate text-[11px] text-muted-foreground/80">{hint}</div> : null}
    </div>
  );
}

/** 团队收益率横向条形图：红涨绿跌，正负分色 */
function RankingBarChart({ items }: { items: PaperAccount[] }) {
  const ref = useMemo(() => ({ current: null as HTMLDivElement | null }), []);
  const palette = usePalette();
  const { resolved } = useTheme();
  const axisColor = axisLabelColor(resolved);
  const { up, down } = useCandleColors();

  const option = useMemo(() => {
    const names = items.map((a) => a.name || a.account_id.slice(0, 6));
    const values = items.map((a) => a.return_pct);
    return {
      backgroundColor: "transparent",
      animation: false,
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        backgroundColor: resolved === "dark" ? "#1e293b" : "#fff",
        textStyle: { color: resolved === "dark" ? "#e2e8f0" : "#0f172a", fontSize: 12 },
        valueFormatter: (v: number | null) => (v == null ? "—" : `${v.toFixed(2)}%`),
      },
      grid: { left: 76, right: 44, top: 8, bottom: 20 },
      xAxis: {
        type: "value",
        axisLabel: { color: axisColor, fontSize: 10, formatter: "{value}%" },
        splitLine: { lineStyle: { color: "#64748b20" } },
      },
      yAxis: { type: "category", data: names, axisLabel: { color: axisColor, fontSize: 11 }, axisLine: { lineStyle: { color: "#64748b60" } } },
      series: [
        {
          name: "收益率",
          type: "bar",
          data: values.map((v) => ({ value: v, itemStyle: { color: v >= 0 ? up : down, borderRadius: [0, 4, 4, 0] } })),
          barWidth: 16,
          label: { show: true, position: "right", color: axisColor, fontSize: 10, formatter: "{c}%" },
        },
      ],
    };
  }, [items, up, down, axisColor, resolved]);

  useEChart(ref, option, [option]);
  void palette;
  return <div ref={ref} className="h-[220px] w-full" />;
}

/** 账户净值曲线：相对净值 vs 1.0 基准线 */
function EquityCurveChart({ dates, equity, bench }: { dates: string[]; equity: number[]; bench: number[] }) {
  const ref = useMemo(() => ({ current: null as HTMLDivElement | null }), []);
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
        valueFormatter: (v: number | null) => (v == null ? "—" : v.toFixed(4)),
      },
      legend: { top: 0, right: 0, textStyle: { color: axisColor, fontSize: 10 } },
      grid: { left: 48, right: 16, top: 28, bottom: 24 },
      xAxis: { type: "category", data: dates, axisLabel: { color: axisColor, fontSize: 9, hideOverlap: true }, axisLine: { lineStyle: { color: "#64748b60" } } },
      yAxis: { type: "value", scale: true, splitLine: { lineStyle: { color: "#64748b20" } }, axisLabel: { color: axisColor, fontSize: 10 } },
      series: [
        {
          name: "净值",
          type: "line",
          data: equity,
          symbol: "circle",
          symbolSize: 5,
          lineStyle: { width: 2 },
          areaStyle: { color: palette[0] + "1a" },
        },
        {
          name: "基准 1.0",
          type: "line",
          data: bench,
          symbol: "none",
          lineStyle: { width: 1.2, type: "dashed", color: "#64748b80" },
        },
      ],
    };
  }, [dates, equity, bench, palette, axisColor, resolved]);

  useEChart(ref, option, [option]);
  return <div ref={ref} className="h-[240px] w-full" />;
}

/** 持仓市值饼图（donut） */
function HoldingsDonut({ positions }: { positions: { symbol: string; market_value: number }[] }) {
  const ref = useMemo(() => ({ current: null as HTMLDivElement | null }), []);
  const palette = usePalette();
  const { resolved } = useTheme();
  const axisColor = axisLabelColor(resolved);

  const option = useMemo(() => {
    return {
      backgroundColor: "transparent",
      animation: false,
      color: palette,
      tooltip: {
        trigger: "item",
        backgroundColor: resolved === "dark" ? "#1e293b" : "#fff",
        textStyle: { color: resolved === "dark" ? "#e2e8f0" : "#0f172a", fontSize: 12 },
        formatter: (p: { name: string; value: number; percent: number }) => `${p.name} · ${fmtMoney(p.value)} · ${p.percent.toFixed(1)}%`,
      },
      legend: { bottom: 0, textStyle: { color: axisColor, fontSize: 10 }, type: "scroll" },
      series: [
        {
          name: "持仓",
          type: "pie",
          radius: ["48%", "72%"],
          center: ["50%", "44%"],
          avoidLabelOverlap: true,
          itemStyle: { borderRadius: 4, borderColor: resolved === "dark" ? "#0b1220" : "#fff", borderWidth: 1 },
          label: { color: axisColor, fontSize: 10, formatter: "{b}" },
          data: positions.map((p) => ({ name: p.symbol, value: p.market_value })),
        },
      ],
    };
  }, [positions, palette, axisColor, resolved]);

  useEChart(ref, option, [option]);
  return <div ref={ref} className="h-[220px] w-full" />;
}

const COMMISSION_RATE = 0.00025;
const COMMISSION_MIN = 5;
const STAMP_TAX = 0.0005;

function estFee(side: "buy" | "sell", amount: number): number {
  if (amount <= 0) return 0;
  const commission = Math.max(COMMISSION_MIN, amount * COMMISSION_RATE);
  return side === "sell" ? commission + amount * STAMP_TAX : commission;
}

export function PaperTradingPage() {
  const { data, error, loading, reload } = usePaperList();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const detail = usePaperDetail(selectedId);

  // 下单表单
  const [tradeSide, setTradeSide] = useState<"buy" | "sell">("buy");
  const [tradeSymbol, setTradeSymbol] = useState("");
  const [tradePrice, setTradePrice] = useState("");
  const [tradeShares, setTradeShares] = useState("");
  const [tradeBusy, setTradeBusy] = useState(false);
  const [tradeMsg, setTradeMsg] = useState<string | null>(null);

  // 开户表单
  const [openName, setOpenName] = useState("");
  const [openCash, setOpenCash] = useState("100000");
  const [openBusy, setOpenBusy] = useState(false);
  const [openMsg, setOpenMsg] = useState<string | null>(null);

  const summary = data?.summary;
  const items = data?.items ?? [];
  const selected = detail.data?.account ?? items.find((a) => a.account_id === selectedId) ?? null;

  const price = Number(tradePrice) || 0;
  const shares = Number(tradeShares) || 0;
  const amount = price * shares;
  const fee = estFee(tradeSide, amount);
  const lotHint = tradeSide === "buy" && shares > 0 && shares % 100 !== 0 ? "买入需 100 股整数倍" : null;
  const buyShort = tradeSide === "buy" && selected && amount + estFee("buy", amount) > selected.cash ? "现金不足" : null;

  async function submitTrade() {
    if (!selectedId) return;
    if (!tradeSymbol.trim() || price <= 0 || shares <= 0) {
      setTradeMsg("请填写代码 / 价格 / 股数");
      return;
    }
    setTradeBusy(true);
    setTradeMsg(null);
    try {
      await paperTrade(selectedId, {
        symbol: tradeSymbol.trim(),
        side: tradeSide,
        price,
        shares,
      });
      setTradeMsg("已成交");
      setTradeSymbol("");
      setTradePrice("");
      setTradeShares("");
      await reload();
      await detail.reload();
    } catch (e) {
      setTradeMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setTradeBusy(false);
    }
  }

  async function submitOpen() {
    setOpenBusy(true);
    setOpenMsg(null);
    try {
      await paperOpen(openName.trim() || "模拟账户", Number(openCash) || 100000);
      setOpenName("");
      setOpenCash("100000");
      await reload();
    } catch (e) {
      setOpenMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setOpenBusy(false);
    }
  }

  async function removeAccount() {
    if (!selectedId) return;
    try {
      await paperDelete(selectedId);
      setSelectedId(null);
      await reload();
    } catch (e) {
      setTradeMsg(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* 团队摘要条 */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        <MetricCell label="账户数" value={String(summary?.account_count ?? 0)} hint="团队模拟账户" />
        <MetricCell label="总资产" value={fmtMoney(summary?.total_equity ?? 0, false, true)} hint={`初始 ${fmtMoney(summary?.total_initial_cash ?? 0, false, true)}`} />
        <MetricCell label="总收益" value={fmtMoney(summary?.total_pnl ?? 0, true, true)} tone={(summary?.total_pnl ?? 0) > 0 ? "up" : (summary?.total_pnl ?? 0) < 0 ? "down" : "muted"} />
        <MetricCell label="团队收益率" value={fmtPct(summary?.return_pct ?? 0, true)} tone={(summary?.return_pct ?? 0) > 0 ? "up" : (summary?.return_pct ?? 0) < 0 ? "down" : "muted"} />
        <MetricCell label="活跃持仓" value={String(summary?.active_positions ?? 0)} hint="事件溯源重放" />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        {/* 左：排行 + 详情 */}
        <div className="flex flex-col gap-4 lg:col-span-3">
          <Card>
            <div className="flex items-center justify-between border-b border-border/70 px-4 py-3">
              <div className="flex items-center gap-2">
                <TrendingUp className="h-4 w-4 text-up" />
                <span className="text-sm font-medium">团队排行</span>
                <Badge variant="secondary">{data?.valuation_source === "last_trade" ? "按最近成交价估值" : "实时"}</Badge>
              </div>
              <Button variant="ghost" size="sm" onClick={() => void reload()} disabled={loading}>
                <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
              </Button>
            </div>
            <div className="p-4">
              {loading && !data ? (
                <div className="py-10 text-center text-sm text-muted-foreground">加载中…</div>
              ) : items.length === 0 ? (
                <EmptyState title="还没有模拟账户" desc="右侧开户后即可下单，持仓/净值由事件溯源重放计算" />
              ) : (
                <>
                  <RankingBarChart items={items} />
                  <div className="mt-3 overflow-x-auto scroll-thin">
                    <table className="w-full min-w-[560px] text-left text-[13px]">
                      <thead>
                        <tr className="border-b border-border/70 text-xs text-muted-foreground">
                          <th className="py-2 pr-2 font-medium">排名</th>
                          <th className="py-2 pr-2 font-medium">成员</th>
                          <th className="py-2 pr-2 text-right font-medium">总资产</th>
                          <th className="py-2 pr-2 text-right font-medium">收益率</th>
                          <th className="py-2 pr-2 text-right font-medium">盈亏</th>
                          <th className="py-2 pr-2 text-right font-medium">持仓</th>
                          <th className="py-2 font-medium">操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {items.map((a, i) => {
                          const active = a.account_id === selectedId;
                          return (
                            <tr
                              key={a.account_id}
                              onClick={() => setSelectedId(a.account_id)}
                              className={cn(
                                "cursor-pointer border-b border-border/40 transition-colors",
                                active ? "bg-muted/40" : "hover:bg-muted/20",
                              )}
                            >
                              <td className="py-2 pr-2 tabular-nums">{i + 1}</td>
                              <td className="py-2 pr-2">
                                <div className="flex items-center gap-1.5">
                                  <span className="font-medium">{a.name}</span>
                                  {i === 0 && items.length > 1 && <span className="text-xs text-amber-500">🏆</span>}
                                </div>
                              </td>
                              <td className="py-2 pr-2 text-right tabular-nums">{fmtMoney(a.equity, false, true)}</td>
                              <td className={cn("py-2 pr-2 text-right font-semibold tabular-nums", pnlClass(a.return_pct))}>{fmtPct(a.return_pct, true)}</td>
                              <td className={cn("py-2 pr-2 text-right tabular-nums", pnlClass(a.total_pnl))}>{fmtMoney(a.total_pnl, true)}</td>
                              <td className="py-2 pr-2 text-right tabular-nums">{a.position_count}</td>
                              <td className="py-2 text-right">
                                <button type="button" className="text-xs text-primary hover:underline" onClick={(e) => { e.stopPropagation(); setSelectedId(a.account_id); }}>
                                  详情
                                </button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>
          </Card>

          {selected ? (
            <Card>
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/70 px-4 py-3">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{selected.name}</span>
                  <span className="text-xs text-muted-foreground tabular-nums">#{selected.account_id.slice(0, 6)}</span>
                  <Badge variant="secondary" className={cn(pnlClass(selected.return_pct))}>
                    {fmtPct(selected.return_pct, true)}
                  </Badge>
                </div>
                <div className="flex items-center gap-1">
                  <Button variant="ghost" size="sm" onClick={() => void detail.reload()} disabled={detail.loading}>
                    <RefreshCw className={cn("h-3.5 w-3.5", detail.loading && "animate-spin")} />
                  </Button>
                  <Button variant="ghost" size="sm" className="text-down" onClick={() => void removeAccount()}>
                    <Trash2 className="h-3.5 w-3.5" />
                    删除
                  </Button>
                </div>
              </div>
              <div className="p-4">
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <MetricCell label="可用现金" value={fmtMoney(selected.cash, false, true)} />
                  <MetricCell label="持仓市值" value={fmtMoney(selected.market_value, false, true)} />
                  <MetricCell label="总资产" value={fmtMoney(selected.equity, false, true)} />
                  <MetricCell label="交易笔数" value={String(selected.trade_count)} hint={selected.stale ? "部分持仓按最后成交价" : "按最近成交价估值"} />
                </div>

                <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
                  {detail.data ? (
                    <EquityCurveChart dates={detail.data.curve.dates} equity={detail.data.curve.equity} bench={detail.data.curve.bench} />
                  ) : (
                    <div className="flex h-[240px] items-center justify-center text-sm text-muted-foreground">净值曲线加载中…</div>
                  )}
                  {selected.holdings.length > 0 ? (
                    <HoldingsDonut positions={selected.holdings.map((h) => ({ symbol: h.symbol, market_value: h.market_value }))} />
                  ) : (
                    <div className="flex h-[220px] items-center justify-center text-sm text-muted-foreground">暂无持仓</div>
                  )}
                </div>

                {/* 持仓表 */}
                {selected.holdings.length > 0 && (
                  <div className="mt-4 overflow-x-auto scroll-thin">
                    <table className="w-full min-w-[560px] text-left text-[13px]">
                      <thead>
                        <tr className="border-b border-border/70 text-xs text-muted-foreground">
                          <th className="py-2 pr-2 font-medium">代码</th>
                          <th className="py-2 pr-2 text-right font-medium">持股</th>
                          <th className="py-2 pr-2 text-right font-medium">成本</th>
                          <th className="py-2 pr-2 text-right font-medium">现价</th>
                          <th className="py-2 pr-2 text-right font-medium">市值</th>
                          <th className="py-2 pr-2 text-right font-medium">盈亏</th>
                          <th className="py-2 text-right font-medium">盈亏%</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selected.holdings.map((h) => (
                          <tr key={h.symbol} className="border-b border-border/40">
                            <td className="py-2 pr-2 font-medium">{h.symbol}</td>
                            <td className="py-2 pr-2 text-right tabular-nums">{h.shares}</td>
                            <td className="py-2 pr-2 text-right tabular-nums">{fmtMoney(h.cost)}</td>
                            <td className="py-2 pr-2 text-right tabular-nums">{fmtMoney(h.last)}</td>
                            <td className="py-2 pr-2 text-right tabular-nums">{fmtMoney(h.market_value)}</td>
                            <td className={cn("py-2 pr-2 text-right tabular-nums", pnlClass(h.pnl))}>{fmtMoney(h.pnl, true)}</td>
                            <td className={cn("py-2 text-right tabular-nums", pnlClass(h.pnl_pct))}>{fmtPct(h.pnl_pct ?? 0, true)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* 最近交易 */}
                {detail.data && detail.data.trades.length > 0 && (
                  <div className="mt-4 overflow-x-auto scroll-thin">
                    <div className="mb-1 text-xs font-medium text-muted-foreground">最近交易（最新 60 笔内）</div>
                    <table className="w-full min-w-[560px] text-left text-[13px]">
                      <thead>
                        <tr className="border-b border-border/70 text-xs text-muted-foreground">
                          <th className="py-2 pr-2 font-medium">时间</th>
                          <th className="py-2 pr-2 font-medium">方向</th>
                          <th className="py-2 pr-2 font-medium">代码</th>
                          <th className="py-2 pr-2 text-right font-medium">价格</th>
                          <th className="py-2 pr-2 text-right font-medium">股数</th>
                          <th className="py-2 pr-2 text-right font-medium">成交额</th>
                          <th className="py-2 text-right font-medium">费用</th>
                        </tr>
                      </thead>
                      <tbody>
                        {detail.data.trades.slice(0, 20).map((t) => (
                          <tr key={t.id} className="border-b border-border/40">
                            <td className="py-2 pr-2 text-xs tabular-nums text-muted-foreground">{fmtDate(t.date)}</td>
                            <td className="py-2 pr-2">
                              <span className={cn("rounded px-1.5 py-0.5 text-xs font-medium", t.side === "buy" ? "bg-up/10 text-up" : "bg-down/10 text-down")}>
                                {t.side === "buy" ? "买入" : "卖出"}
                              </span>
                            </td>
                            <td className="py-2 pr-2 font-medium">{t.symbol}</td>
                            <td className="py-2 pr-2 text-right tabular-nums">{fmtMoney(t.price)}</td>
                            <td className="py-2 pr-2 text-right tabular-nums">{t.shares}</td>
                            <td className="py-2 pr-2 text-right tabular-nums">{fmtMoney(t.amount)}</td>
                            <td className="py-2 text-right tabular-nums text-muted-foreground">{fmtMoney(t.fee)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </Card>
          ) : (
            <Card>
              <EmptyState title="选择一个账户查看详情" desc="点击排行中的账户行，查看净值曲线、持仓结构与交易明细" />
            </Card>
          )}
        </div>

        {/* 右：下单 + 开户 */}
        <div className="flex flex-col gap-4 lg:col-span-2">
          <Card>
            <div className="border-b border-border/70 px-4 py-3">
              <span className="text-sm font-medium">下单交易</span>
            </div>
            <div className="flex flex-col gap-3 p-4">
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant={tradeSide === "buy" ? "default" : "outline"}
                  onClick={() => setTradeSide("buy")}
                  className={cn(tradeSide === "buy" && "bg-up text-white hover:bg-up/90")}
                >
                  买入
                </Button>
                <Button
                  size="sm"
                  variant={tradeSide === "sell" ? "default" : "outline"}
                  onClick={() => setTradeSide("sell")}
                  className={cn(tradeSide === "sell" && "bg-down text-white hover:bg-down/90")}
                >
                  卖出
                </Button>
                <div className="ml-auto text-xs text-muted-foreground">
                  {selected ? `账户：${selected.name}` : "先选择账户"}
                </div>
              </div>

              {selected && (
                <div className="flex flex-col gap-2">
                  <div className="grid grid-cols-3 gap-2">
                    <label className="flex flex-col gap-1">
                      <span className="text-xs text-muted-foreground">代码</span>
                      <input
                        value={tradeSymbol}
                        onChange={(e) => setTradeSymbol(e.target.value)}
                        placeholder="600519"
                        className="rounded-md border border-border bg-background px-2 py-1.5 text-sm tabular-nums focus:border-primary focus:outline-none"
                      />
                    </label>
                    <label className="flex flex-col gap-1">
                      <span className="text-xs text-muted-foreground">价格（现价）</span>
                      <input
                        value={tradePrice}
                        onChange={(e) => setTradePrice(e.target.value)}
                        placeholder="100.00"
                        type="number"
                        min="0"
                        className="rounded-md border border-border bg-background px-2 py-1.5 text-sm tabular-nums focus:border-primary focus:outline-none"
                      />
                    </label>
                    <label className="flex flex-col gap-1">
                      <span className="text-xs text-muted-foreground">股数</span>
                      <input
                        value={tradeShares}
                        onChange={(e) => setTradeShares(e.target.value)}
                        placeholder="100"
                        type="number"
                        min="0"
                        className="rounded-md border border-border bg-background px-2 py-1.5 text-sm tabular-nums focus:border-primary focus:outline-none"
                      />
                    </label>
                  </div>

                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">
                      预估成交 {fmtMoney(amount)} · 费用 {fmtMoney(fee)}（佣金 0.025% 最低 5 元{tradeSide === "sell" ? " + 印花税 0.05%" : ""}）
                    </span>
                  </div>

                  {lotHint && <div className="flex items-center gap-1 text-xs text-amber-500"><AlertTriangle className="h-3 w-3" />{lotHint}</div>}
                  {buyShort && <div className="flex items-center gap-1 text-xs text-down"><AlertTriangle className="h-3 w-3" />{buyShort}</div>}

                  <Button onClick={() => void submitTrade()} disabled={tradeBusy || !selectedId || !tradeSymbol.trim() || price <= 0 || shares <= 0} className={cn(tradeSide === "sell" && "bg-down text-white hover:bg-down/90")}>
                    {tradeBusy ? "提交中…" : tradeSide === "buy" ? "买入成交" : "卖出成交"}
                  </Button>
                  {tradeMsg && <div className={cn("text-xs", tradeMsg === "已成交" ? "text-up" : "text-muted-foreground")}>{tradeMsg}</div>}
                </div>
              )}
            </div>
          </Card>

          <Card>
            <div className="flex items-center gap-2 border-b border-border/70 px-4 py-3">
              <UserPlus className="h-4 w-4" />
              <span className="text-sm font-medium">开户（加入团队）</span>
            </div>
            <div className="flex flex-col gap-3 p-4">
              <div className="grid grid-cols-2 gap-2">
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">成员名</span>
                  <input
                    value={openName}
                    onChange={(e) => setOpenName(e.target.value)}
                    placeholder="小明 / 主力户"
                    className="rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:border-primary focus:outline-none"
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">初始资金</span>
                  <input
                    value={openCash}
                    onChange={(e) => setOpenCash(e.target.value)}
                    type="number"
                    min="1000"
                    className="rounded-md border border-border bg-background px-2 py-1.5 text-sm tabular-nums focus:border-primary focus:outline-none"
                  />
                </label>
              </div>
              <Button variant="outline" onClick={() => void submitOpen()} disabled={openBusy}>
                <Plus className="h-3.5 w-3.5" />
                {openBusy ? "开户中…" : "开户"}
              </Button>
              {openMsg && <div className="text-xs text-muted-foreground">{openMsg}</div>}
              <p className="text-[11px] leading-relaxed text-muted-foreground/70">
                模拟盘数据由交易事件重放计算，仅用于团队策略演练，不构成投资建议。
              </p>
            </div>
          </Card>

          {error && (
            <Card>
              <div className="flex items-center gap-2 px-4 py-3 text-sm text-down">
                <AlertTriangle className="h-4 w-4" />
                {error}
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, LineChart, Pencil, Trash2, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { fmtMoney, fmtPct, pnlClass } from "@/lib/format";
import type { Position } from "@/lib/types";
import { useI18n } from "@/lib/i18n";
import { KlineDialog } from "@/components/KlineDialog";

type SortKey = "weight" | "market_value" | "pnl" | "pnl_pct";

/** 持仓数据表：可排序、数字右对齐等宽、盈亏红涨绿跌；点行可查看 K 线走势。
 *  市值/盈亏由后端算好传入（与问答、图表同源，避免口径不一致）。
 *  传入 ops 时，每行/卡增加「编辑 / 删除 / 追加」操作入口。 */
export type PositionOps = {
  onEdit: (p: Position) => void;
  onDelete: (p: Position) => void;
  onAppend: (p: Position, payload: { shares: number; cost: number; last?: number }) => void | Promise<void>;
};

export function PositionsTable({
  rows,
  total,
  className,
  compact = false,
  ops,
}: {
  rows: Position[];
  total?: number;
  className?: string;
  compact?: boolean;
  ops?: PositionOps;
}) {
  const { t: tr } = useI18n();
  const [sortKey, setSortKey] = useState<SortKey>("market_value");
  const [desc, setDesc] = useState(true);
  const [klineSymbol, setKlineSymbol] = useState<string | null>(null);

  const computed = useMemo(() => {
    // 「占比」列 = 相对**总市值**（含现金），各项之和为 100%，与资产分布饼图一致。
    // 集中度判定另有一套「相对可投资资产」的口径，在持仓页右侧面板单独展示；
    // 两个口径各有用处，但不能混在同一列里——曾经现金也按非现金分母算，
    // 导致这一列合计 126%，用户一眼就看出不对。
    const totalMv = total ?? rows.reduce((s, r) => s + r.market_value, 0);
    return rows
      .map((r) => ({ ...r, weight: totalMv ? (r.market_value / totalMv) * 100 : 0 }))
      .sort((a, b) => (desc ? b[sortKey] - a[sortKey] : a[sortKey] - b[sortKey]));
  }, [rows, total, sortKey, desc]);

  const toggle = (k: SortKey) => {
    if (k === sortKey) setDesc((v) => !v);
    else {
      setSortKey(k);
      setDesc(true);
    }
  };

  const SortHead = ({ k, label }: { k: SortKey; label: string }) => (
    <th
      className="cursor-pointer select-none whitespace-nowrap px-2 py-1.5 font-medium text-muted-foreground transition-colors hover:text-foreground text-right"
      onClick={() => toggle(k)}
    >
      <span className="inline-flex items-center gap-0.5">
        {label}
        {sortKey === k ? (
          desc ? <ArrowDown className="h-3 w-3" /> : <ArrowUp className="h-3 w-3" />
        ) : (
          <ArrowUpDown className="h-2.5 w-2.5 opacity-40" />
        )}
      </span>
    </th>
  );

  const clicked = rows.find((r) => r.symbol === klineSymbol);

  return (
    <>
      {/* 宽容器（≥36rem）：7 列可排序表格；窄容器（侧面板/移动端）：卡片视图。
          用容器查询而非视口断点：本组件主要渲染在 400-440px 的侧面板内，
          桌面视口虽宽但面板很窄，md: 视口断点会把 8 列表格挤进面板。 */}
      <div className={cn("scroll-thin hidden overflow-x-auto rounded-lg border border-border bg-card @xl:block", className)}>
        <table className="w-full border-collapse text-xs" style={{ fontVariantNumeric: "tabular-nums" }}>
          <thead>
            <tr className="border-b border-border bg-muted/50">
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">{tr("pos.symbol")}</th>
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">{tr("pos.kind")}</th>
              <SortHead k="weight" label={tr("pos.weight")} />
              <th className="px-2 py-1.5 text-right font-medium text-muted-foreground">{tr("pos.price")}</th>
              <SortHead k="market_value" label={tr("pos.marketValue")} />
              <SortHead k="pnl" label={tr("pos.pnl")} />
              <SortHead k="pnl_pct" label={`${tr("pos.pnl")}%`} />
              {ops && <th className="px-2 py-1.5 text-right font-medium text-muted-foreground">{tr("pos.ops")}</th>}
            </tr>
          </thead>
          <tbody>
            {computed.map((r) => (
              <tr key={r.symbol} className="border-b border-border/60 last:border-0 hover:bg-accent/40">
                <td className="px-2 py-1.5">
                  <button
                    type="button"
                    className="text-left group inline-flex items-center gap-1"
                    onClick={() => setKlineSymbol(r.symbol)}
                    aria-label={tr("pos.viewK", { name: r.name })}
                  >
                    <span className="font-medium text-foreground group-hover:text-primary">{r.name}</span>
                    <span className="text-[11px] text-muted-foreground">{r.symbol}</span>
                    <LineChart className="w-3 h-3 text-muted-foreground/50 group-hover:text-primary" />
                  </button>
                </td>
                <td className="px-2 py-1.5 text-muted-foreground">{r.kind}</td>
                <td className="px-2 py-1.5 text-right">
                  <span
                    className={cn(
                      "rounded px-1 py-0.5",
                      r.weight > 40 ? "bg-amber-100 text-amber-700" : "text-foreground",
                    )}
                  >
                    {r.weight.toFixed(1)}%
                  </span>
                </td>
                <td className="px-2 py-1.5 text-right text-muted-foreground">{fmtMoney(r.last, false, compact)}</td>
                <td className="px-2 py-1.5 text-right font-medium">{fmtMoney(r.market_value, false, compact)}</td>
                <td className={cn("px-2 py-1.5 text-right", pnlClass(r.pnl))}>{fmtMoney(r.pnl, true, compact)}</td>
                <td className={cn("px-2 py-1.5 text-right", pnlClass(r.pnl))}>{fmtPct(r.pnl_pct, true)}</td>
                {ops && (
                  <td className="px-2 py-1.5">
                    <span className="flex items-center justify-end gap-1">
                      <button
                        type="button"
                        className="rounded p-0.5 text-muted-foreground hover:text-primary hover:bg-primary/10"
                        onClick={() => ops.onEdit(r)}
                        aria-label={tr("pos.edit", { name: r.name })}
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </button>
                      <button
                        type="button"
                        className="rounded p-0.5 text-muted-foreground hover:text-amber-600 hover:bg-amber-500/10"
                        onClick={() => void ops.onAppend(r, { shares: r.shares, cost: r.cost_per_share ?? (r.shares > 0 ? r.cost / r.shares : 0) })}
                        aria-label={tr("pos.append", { name: r.name })}
                        title={tr("pos.append", { name: r.name })}
                      >
                        <Plus className="w-3.5 h-3.5" />
                      </button>
                      <button
                        type="button"
                        className="rounded p-0.5 text-muted-foreground hover:text-red-600 hover:bg-red-500/10"
                        onClick={() => ops.onDelete(r)}
                        aria-label={tr("pos.delete", { name: r.name })}
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </span>
                  </td>
                )}
              </tr>
            ))}
            {computed.length === 0 && (
              <tr>
                <td colSpan={ops ? 8 : 7} className="px-2 py-3 text-center text-muted-foreground">
                  {tr("pos.empty")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* 窄容器：每持仓一张卡片（整卡可点开 K 线），替代 7 列宽表 */}
      <div className={cn("space-y-2 @xl:hidden", className)}>
        {computed.length === 0 && (
          <p className="rounded-lg border border-border bg-card px-3 py-4 text-center text-sm text-muted-foreground">
            {tr("pos.empty")}
          </p>
        )}
        {computed.map((r) => (
          <div
            key={r.symbol}
            role="button"
            tabIndex={0}
            onClick={() => setKlineSymbol(r.symbol)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setKlineSymbol(r.symbol);
              }
            }}
            aria-label={tr("pos.viewK", { name: r.name })}
            className="block w-full cursor-pointer rounded-lg border border-border bg-card p-3 text-left transition-colors hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="min-w-0">
                <span className="font-medium text-foreground">{r.name}</span>
                <span className="ml-1.5 text-xs text-muted-foreground">{r.symbol}</span>
                <span className="ml-1.5 text-xs text-muted-foreground">{r.kind}</span>
              </span>
              <span
                className={cn(
                  "shrink-0 rounded px-1 py-0.5 text-xs tabular-nums",
                  r.weight > 40 ? "bg-amber-100 text-amber-700" : "text-muted-foreground",
                )}
              >
                {tr("pos.weight")} {r.weight.toFixed(1)}%
              </span>
            </div>
            <div className="mt-2 flex items-baseline justify-between gap-2 text-sm">
              <span className="text-muted-foreground">
                {tr("pos.price")} {fmtMoney(r.last, false, compact)}
              </span>
              <span className="font-medium tabular-nums">
                {tr("pos.marketValue")} {fmtMoney(r.market_value, false, compact)}
              </span>
            </div>
            <div className="mt-1 flex items-baseline justify-between gap-2 text-sm">
              <span className={cn("tabular-nums", pnlClass(r.pnl))}>{fmtMoney(r.pnl, true, compact)}</span>
              <span className={cn("tabular-nums", pnlClass(r.pnl))}>{fmtPct(r.pnl_pct, true)}</span>
            </div>
            {ops && (
              <div className="mt-2 flex items-center gap-2 border-t border-border/60 pt-1.5">
                <button
                  type="button"
                  className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-muted-foreground hover:text-primary hover:bg-primary/10"
                  onClick={(e) => {
                    e.stopPropagation();
                    ops.onEdit(r);
                  }}
                >
                  <Pencil className="w-3 h-3" /> {tr("entry.edit")}
                </button>
                <button
                  type="button"
                  className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-muted-foreground hover:text-amber-600 hover:bg-amber-500/10"
                  onClick={(e) => {
                    e.stopPropagation();
                    void ops.onAppend(r, { shares: r.shares, cost: r.cost_per_share ?? (r.shares > 0 ? r.cost / r.shares : 0) });
                  }}
                >
                  <Plus className="w-3 h-3" /> {tr("pos.appendShort")}
                </button>
                <button
                  type="button"
                  className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-muted-foreground hover:text-red-600 hover:bg-red-500/10"
                  onClick={(e) => {
                    e.stopPropagation();
                    ops.onDelete(r);
                  }}
                >
                  <Trash2 className="w-3 h-3" /> {tr("pos.delShort")}
                </button>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* K 线详情：点标的行/卡打开 */}
      <KlineDialog
        symbol={clicked?.symbol ?? ""}
        name={clicked?.name ?? ""}
        open={klineSymbol !== null}
        onOpenChange={(o) => !o && setKlineSymbol(null)}
      />
    </>
  );
}

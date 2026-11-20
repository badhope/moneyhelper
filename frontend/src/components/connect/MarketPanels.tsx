/** 连接中心深化面板 · 市场：市场温度（涨跌家数/涨跌停/情绪刻度）、个股档案。 */

/** 连接中心深化面板（v4.5）：市场温度 / 个股档案 / 预交易检查 / 风控参数 / 条件单 / 发票 / 券商对账。
 *
 * 拆成独立文件：ConnectPage 已 900+ 行，继续内联会让单文件失控；这些面板都只依赖
 * use-connect 的 hooks，彼此独立，按需渲染。
 */

import { useState } from "react";

import { Gauge } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";

import { useI18n } from "@/lib/i18n";


import { fmtPct, pnlClass } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useBreadth, useStockProfile } from "@/lib/use-connect";

const MOOD_STYLE: Record<string, string> = {
  hot: "text-red-600 dark:text-red-400",
  warm: "text-amber-600 dark:text-amber-400",
  neutral: "text-muted-foreground",
  cool: "text-sky-600 dark:text-sky-400",
  cold: "text-emerald-600 dark:text-emerald-400",
};


/** 市场温度：涨跌家数 + 涨跌停 + 情绪刻度 */
export function BreadthCard() {
  const { t } = useI18n();
  const q = useBreadth();
  const d = q.data;
  if (q.isPending) {
    return (
      <Card className="p-[var(--card-pad)]">
        <Skeleton className="h-28 w-full" />
      </Card>
    );
  }
  if (!d?.available) {
    return (
      <Card className="p-[var(--card-pad)]">
        <EmptyState mode="compact" text={d?.reason || t("connect.noData")} />
      </Card>
    );
  }
  const temp = d.temperature ?? 0;
  return (
    <Card className="p-[var(--card-pad)]">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-[13px] font-semibold">
          <Gauge className="h-4 w-4 text-primary" />
          {t("connect.breadthTitle")}
        </div>
        <span className={cn("text-[11px]", MOOD_STYLE[d.mood ?? "neutral"])}>
          {t(`connect.mood.${d.mood ?? "neutral"}`)}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
        {[
          { label: t("connect.breadthUp"), value: d.up, tone: "text-up" },
          { label: t("connect.breadthDown"), value: d.down, tone: "text-down" },
          { label: t("connect.breadthLimitUp"), value: d.limit_up, tone: "text-up" },
          { label: t("connect.breadthLimitDown"), value: d.limit_down, tone: "text-down" },
          { label: t("connect.breadthStrong"), value: d.strong, tone: "text-foreground" },
        ].map((x) => (
          <div key={x.label} className="rounded-lg bg-muted/25 px-2.5 py-2">
            <div className="text-[10.5px] text-muted-foreground">{x.label}</div>
            <div className={cn("mt-0.5 text-base font-bold tabular-nums", x.tone)}>{x.value ?? "-"}</div>
          </div>
        ))}
      </div>
      <div className="mt-2">
        <div className="flex items-center justify-between text-[11px] text-muted-foreground">
          <span>{t("connect.temperature")}</span>
          <span className="font-medium tabular-nums">{temp.toFixed(1)} / 100</span>
        </div>
        <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div
            className={cn(
              "h-full rounded-full",
              temp >= 55 ? "bg-red-500" : temp >= 45 ? "bg-amber-500" : "bg-emerald-500",
            )}
            style={{ width: `${Math.max(2, Math.min(100, temp))}%` }}
          />
        </div>
        <div className="mt-1.5 text-[10.5px] text-muted-foreground">
          {t("connect.breadthRatio", { up: d.up_ratio_pct ?? 0, total: d.total ?? 0 })}
        </div>
      </div>
    </Card>
  );
}

/** 个股档案：价格 + 估值 + 规模 + 活跃度 */
export function StockProfileCard({ defaultSymbol }: { defaultSymbol: string }) {
  const { t } = useI18n();
  const [sym, setSym] = useState(defaultSymbol);
  const [query, setQuery] = useState(defaultSymbol);
  const q = useStockProfile(query);
  const d = q.data;
  return (
    <Card className="p-[var(--card-pad)]">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="text-[13px] font-semibold">{t("connect.profileTitle")}</div>
        <div className="flex items-center gap-1.5">
          <input
            value={sym}
            onChange={(e) => setSym(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") setQuery(sym.trim());
            }}
            placeholder="600519"
            className="w-28 rounded-md border border-border bg-background px-2 py-1 text-[12px]"
          />
          <Button size="sm" variant="outline" onClick={() => setQuery(sym.trim())}>
            {t("connect.query")}
          </Button>
        </div>
      </div>
      {q.isPending ? (
        <Skeleton className="h-24 w-full" />
      ) : q.isError || !d ? (
        <EmptyState mode="compact" text={t("connect.profileFail")} />
      ) : (
        <>
          <div className="flex items-baseline gap-2">
            <span className="text-[15px] font-semibold">{d.name || d.symbol}</span>
            <span className="text-lg font-bold tabular-nums">{d.price}</span>
            <span className={cn("text-[12px] tabular-nums", pnlClass(d.change_pct))}>
              {fmtPct(d.change_pct, true)}
            </span>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              { label: t("connect.pe"), value: d.pe_ttm != null ? d.pe_ttm.toFixed(2) : "-", tone: "" },
              { label: t("connect.pb"), value: d.pb != null ? d.pb.toFixed(2) : "-", tone: "" },
              {
                label: t("connect.totalMv"),
                value: d.total_mv_yi != null ? `${d.total_mv_yi.toFixed(0)} ${t("connect.mvUnit")}` : "-",
                tone: "",
              },
              {
                label: t("connect.turnoverRate"),
                value: d.turnover_pct != null ? `${d.turnover_pct.toFixed(2)}%` : "-",
                tone: "",
              },
              {
                label: t("connect.volumeRatio"),
                value: d.volume_ratio != null ? d.volume_ratio.toFixed(2) : "-",
                tone: "",
              },
              {
                label: t("connect.amplitude"),
                value: d.amplitude_pct != null ? `${d.amplitude_pct.toFixed(2)}%` : "-",
                tone: "",
              },
              { label: t("connect.limitUp"), value: d.limit_up != null ? String(d.limit_up) : "-", tone: "text-up" },
              {
                label: t("connect.limitDown"),
                value: d.limit_down != null ? String(d.limit_down) : "-",
                tone: "text-down",
              },
            ].map((x) => (
              <div key={x.label} className="rounded-lg bg-muted/25 px-2 py-1.5">
                <div className="text-[10.5px] text-muted-foreground">{x.label}</div>
                <div className={cn("text-[13px] font-semibold tabular-nums", x.tone)}>{x.value}</div>
              </div>
            ))}
          </div>
          {d.valuation?.pe_note ? (
            <p className="mt-1.5 text-[10.5px] text-amber-600 dark:text-amber-400">{d.valuation.pe_note}</p>
          ) : null}
        </>
      )}
    </Card>
  );
}

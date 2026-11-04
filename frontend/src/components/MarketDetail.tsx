import { useQuery } from "@tanstack/react-query";
import { Loader2, LineChart as LineChartIcon } from "lucide-react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { fmtMoney, fmtPct, pnlClass } from "@/lib/format";
import { MiniSparkline } from "@/components/MiniSparkline";
import type { KlinePoint } from "@/components/KlineDialog";

/**
 * 行情详情栏（右侧）：选中标的的迷你走势 + 关键价位。
 * 借鉴股票软件的"列表 + 详情"双栏：列表扫一遍，详情看一只。
 */
export function MarketDetail({
  symbol,
  name,
  kind,
  price,
  changePct,
  onOpenKline,
}: {
  symbol: string;
  name: string;
  kind?: string;
  price?: number | null;
  changePct?: number | null;
  onOpenKline: () => void;
}) {
  const { t } = useI18n();
  // 与后端对齐：场外基金/现金没有 K 线，不发请求（否则控制台每次一条 404）
  const supported = (() => {
    const s = (symbol || "").trim().toUpperCase();
    if (!/^\d{6}$/.test(s)) return false;
    return s[0] === "6" || s[0] === "5" || s[0] === "0" || s[0] === "3" || s.startsWith("15") || s.startsWith("16");
  })();
  const q = useQuery({
    queryKey: ["/api/kline", symbol, "spark"],
    queryFn: () =>
      api<{ points: KlinePoint[] }>(`/api/kline?symbol=${encodeURIComponent(symbol)}&period=daily&limit=60`),
    staleTime: 5 * 60_000,
    retry: 0,
    enabled: supported,
  });

  const points = q.data?.points ?? [];
  const first = points[0]?.close;
  const last = points[points.length - 1]?.close;
  const periodPct = first && last ? ((last - first) / first) * 100 : null;
  const highs = points.map((p) => p.close);
  const hi = highs.length ? Math.max(...highs) : null;
  const lo = highs.length ? Math.min(...highs) : null;

  return (
    <div className="rounded-2xl border border-border bg-card p-3.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">{name}</div>
          <div className="mt-0.5 text-[11px] text-muted-foreground">
            {kind ? `${kind} · ` : ""}
            {symbol}
          </div>
        </div>
        <button
          type="button"
          onClick={onOpenKline}
          className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <LineChartIcon className="h-3.5 w-3.5" />
          {t("market.openKline")}
        </button>
      </div>

      <div className="mt-3 flex items-baseline gap-2">
        <span className="text-2xl font-semibold tabular-nums">
          {price != null ? fmtMoney(price, false, true) : "—"}
        </span>
        <span className={cn("text-sm tabular-nums", pnlClass(changePct ?? 0))}>
          {changePct != null ? fmtPct(changePct, true) : ""}
        </span>
      </div>

      {/* 先判 supported：enabled=false 时 TanStack 的 isPending 仍为 true，
          会让场外基金/现金永远转圈「加载中」，用户以为网络卡住。 */}
      {!supported ? (
        <div className="flex h-24 items-center justify-center text-xs text-muted-foreground">
          {t("market.noKline")}
        </div>
      ) : q.isPending ? (
        <div className="flex h-24 items-center justify-center text-xs text-muted-foreground">
          <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> {t("pos.loading")}
        </div>
      ) : points.length ? (
        <>
          <MiniSparkline points={points} className="mt-2 h-24 w-full" />
          <dl className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
            <div>
              <dt className="text-muted-foreground">{t("market.periodChange")}</dt>
              <dd className={cn("tabular-nums", pnlClass(periodPct ?? 0))}>
                {periodPct != null ? fmtPct(periodPct, true) : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">{t("market.high60")}</dt>
              <dd className="tabular-nums">{hi != null ? fmtMoney(hi, false, true) : "—"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">{t("market.low60")}</dt>
              <dd className="tabular-nums">{lo != null ? fmtMoney(lo, false, true) : "—"}</dd>
            </div>
          </dl>
        </>
      ) : (
        <p className="mt-3 rounded-lg bg-muted/50 px-2.5 py-3 text-center text-[11px] text-muted-foreground">
          {t("pos.noKline")}
        </p>
      )}
    </div>
  );
}

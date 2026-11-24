/** 个人资产调优（4.19.0）：确定性候选 + 风险说明，不代下单。 */
import { ArrowRight, ShieldAlert, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { fmtMoney } from "@/lib/format";
import type { AssetTune } from "@/lib/types";

const KIND_KEY: Record<string, string> = {
  liquidity: "assetTune.kindLiquidity",
  debt: "assetTune.kindDebt",
  concentration: "assetTune.kindConcentration",
  rebalance: "assetTune.kindRebalance",
  savings: "assetTune.kindSavings",
};

export function AssetTuneCard({
  data,
  onNavigate,
}: {
  data?: AssetTune | null;
  onNavigate?: (tab: string) => void;
}) {
  const { t } = useI18n();
  if (!data || !data.candidates.length) return null;

  return (
    <section className="rounded-xl border border-border/70 bg-card">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          <Sparkles className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-medium">{t("assetTune.title")}</h2>
          <Badge variant="muted">{data.count}</Badge>
        </div>
        <span className="text-[11px] text-muted-foreground">{t("assetTune.hint")}</span>
      </header>
      <ul className="divide-y divide-border/50">
        {data.candidates.map((c, i) => {
          const urgent = c.priority <= 10;
          return (
            <li key={`${c.kind}-${c.symbol}-${i}`} className="relative flex gap-3 px-4 py-3">
              <span
                className={cn(
                  "absolute left-0 top-0 h-full w-[3px]",
                  urgent ? "bg-red-500" : c.priority <= 20 ? "bg-amber-500" : "bg-primary/60",
                )}
                aria-hidden
              />
              <ShieldAlert
                className={cn(
                  "mt-0.5 h-4 w-4 shrink-0",
                  urgent ? "text-red-600 dark:text-red-400" : "text-muted-foreground",
                )}
              />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  <span className="text-[13.5px] font-medium">{c.title}</span>
                  <span className="rounded bg-foreground/[0.05] px-1.5 py-px text-[10.5px] text-muted-foreground">
                    {t(KIND_KEY[c.kind] ?? "assetTune.kindSavings")}
                  </span>
                  {c.amount > 0 && (
                    <span className="text-[11px] tabular-nums text-foreground/70">
                      {t("assetTune.amount")} {fmtMoney(c.amount)}
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-[12.5px] leading-relaxed text-muted-foreground">{c.detail}</p>
                         <p className="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground/85">
                  {c.impact}
                </p>
                <p className="mt-1 flex items-start gap-1 text-[11px] leading-relaxed text-amber-700 dark:text-amber-400">
                  <ShieldAlert className="mt-0.5 h-3 w-3 shrink-0" />
                  {c.risk}
                </p>
              </div>
              {c.action_tab && onNavigate && (
                <button
                  type="button"
                  onClick={() => onNavigate(c.action_tab)}
                  className="mt-0.5 inline-flex shrink-0 items-center gap-1 self-start rounded-lg border border-border/80 px-2 py-1 text-[12px] text-foreground/80 transition-colors hover:bg-accent hover:text-foreground"
                >
                  {t("assetTune.go")}
                  <ArrowRight className="h-3 w-3" />
                </button>
              )}
            </li>
          );
        })}
      </ul>
      <div className="border-t border-border/50 px-4 py-2 text-[10.5px] leading-relaxed text-muted-foreground">
        {data.boundary}
      </div>
    </section>
  );
}

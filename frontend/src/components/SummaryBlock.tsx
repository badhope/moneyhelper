import { Badge } from "@/components/ui/badge";
import { Sparkles } from "lucide-react";
import { fmtMoney, pnlClass } from "@/lib/format";
import { isLevelAlert, levelLabel } from "@/lib/level";
import type { AnswerMeta } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";

/** 健康指标进度条：把关键财务比例可视化为小条（低于阈值=警示色）。 */
function MetricBar({
  label,
  value,
  target,
  hint,
  good,
}: {
  label: string;
  value: number;
  target: number;
  hint: string;
  good: boolean;
}) {
  const pct = Math.max(0, Math.min(100, (value / target) * 100));
  return (
    <div className="flex items-center gap-2">
      <span className="w-20 shrink-0 text-[11px] text-muted-foreground">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-foreground/10">
        <div
          className={cn("h-full rounded-full transition-all", good ? "bg-emerald-500/80" : "bg-amber-500/80")}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={cn("w-14 shrink-0 text-right text-[11px] tabular-nums", good ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400")}>
        {hint}
      </span>
    </div>
  );
}

/** 回答尾部摘要：等级 + 关键数字 + 风险提示（全部来自后端 final 事件，口径唯一）。
 *
 * compact=true 用于「已有富回答块」的场景：此时指标与风险已在块里展示，
 * 这里只保留「Moneyhelper 的理解」（意图识别），避免同一组数字重复三遍。
 */
export function SummaryBlock({ meta, compact = false }: { meta: AnswerMeta; compact?: boolean }) {
  const { t } = useI18n();
  const m = meta.metrics;
  const chips: { label: string; value: string; cls?: string }[] = [];
  if (m.total_market_value != null)
    chips.push({ label: t("summary.marketValue"), value: fmtMoney(m.total_market_value) });
  if (m.total_pnl != null)
    chips.push({
      label: t("summary.totalPnl"),
      value: fmtMoney(m.total_pnl, true),
      cls: pnlClass(m.total_pnl),
    });
  if (m.net != null) chips.push({ label: t("summary.monthlyNet"), value: fmtMoney(m.net, true) });
  if (m.savings_rate != null) chips.push({ label: t("summary.savingsRate"), value: `${m.savings_rate}%` });
  if (m.debt_monthly != null)
    chips.push({ label: t("summary.debtMonthly"), value: `${fmtMoney(m.debt_monthly)}/mo` });

  const levelText = levelLabel(t, meta.level);
  const isAlert = isLevelAlert(meta.level);
  const hasChips = chips.length > 0;

  // 健康条：储蓄率(target 20%) / 负债收入比(target 30%) / 盈亏率。来自 final 指标，口径唯一。
  const bars: { label: string; value: number; target: number; hint: string; good: boolean }[] = [];
  if (m.savings_rate != null)
    bars.push({ label: t("summary.savingsRate"), value: m.savings_rate, target: 20, hint: `${m.savings_rate}%`, good: m.savings_rate >= 20 });
  if (m.dti_pct != null)
    bars.push({ label: t("summary.debtRatio"), value: m.dti_pct, target: 30, hint: `${m.dti_pct}%`, good: m.dti_pct <= 30 });
  if (m.total_pnl_pct != null)
    bars.push({ label: t("summary.returnPct"), value: Math.abs(m.total_pnl_pct), target: 5, hint: `${m.total_pnl_pct}%`, good: m.total_pnl_pct >= 0 });

  // 无等级也无指标时整块为空 → 什么都不渲染（来源徽章已在消息顶部，不在此重复）
  if (!levelText && !hasChips && bars.length === 0) return null;

  return (
    <div className="mt-4">
      {/* 意图识别显性化：Moneyhelper 把这句话读成什么（差异化「懂钱」的特征，前端直接亮给用户看） */}
      {meta.route && meta.route_reason && meta.route !== "general" && meta.route !== "nl_add" && (
        <div className="mb-2 inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/5 px-2.5 py-1 text-[11px] text-primary">
          <Sparkles className="w-3 h-3 shrink-0" />
          <span className="opacity-80">{t("agent.understood")}</span>
          <span className="font-medium">{meta.route_reason}</span>
        </div>
      )}
      {levelText && !compact && (
        <div className="flex items-center gap-2">
          <Badge variant={isAlert ? "warn" : "ok"}>{levelText}</Badge>
        </div>
      )}
      {hasChips && !compact && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm tabular-nums">
          {chips.map((c) => (
            <span key={c.label} className="text-muted-foreground">
              {c.label}
              <b className={cn("ml-1 text-foreground", c.cls)}>{c.value}</b>
            </span>
          ))}
        </div>
      )}
      {bars.length > 0 && !compact && (
        <div className="mt-2.5 space-y-1.5">
          {bars.map((b) => (
            <MetricBar key={b.label} {...b} />
          ))}
        </div>
      )}
    </div>
  );
}

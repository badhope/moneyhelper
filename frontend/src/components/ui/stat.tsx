import { cn } from "@/lib/utils";

/** 账本抬头栏统计格：label + 大数字 + sub 说明；tone 控制涨跌色（竖线分隔由外层 grid divide-x 提供）。 */
export function StatCell({
  label,
  value,
  sub,
  tone,
  valueClass,
  emphasis = false,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "up" | "down" | "default";
  /** 直接覆盖数值行颜色（替代 tone 的场景，如 0 值走 muted） */
  valueClass?: string;
  /** 核心指标（如总资产）突出层级：字号更大、子行更淡 */
  emphasis?: boolean;
}) {
  const color = valueClass ?? (tone === "up" ? "text-up" : tone === "down" ? "text-down" : "text-foreground");
  return (
    <div className="min-w-0 px-3 py-2 first:pl-0 sm:px-4">
      <div className={cn("text-xs", emphasis ? "text-foreground/80 font-medium" : "text-muted-foreground")}>{label}</div>
      <div className={cn("mt-1 whitespace-nowrap tabular-nums num-in leading-tight", color, emphasis ? "text-2xl font-bold" : "text-lg font-bold sm:text-xl")}>{value}</div>
      {sub ? <div className="mt-1 text-xs text-muted-foreground/80 leading-snug">{sub}</div> : null}
    </div>
  );
}

/**
 * 圆角浅底指标格：财报 / 回测 / 模拟盘里"一格一个指标"的通用写法。
 *
 * 此前这套样式在 StatementsPage / PaperTradingPage / StrategyPage 各写了一份
 * （字号 15px vs 18px、label 11px vs 12px 的差别），本质是同一个指标格。
 * 差异收敛成两个参数：`size`（sm=卡片内密排 / md=指标条）与 `truncate`。
 */
export function StatTile({
  label,
  value,
  hint,
  tone = "default",
  size = "sm",
  truncate = true,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "up" | "down" | "muted" | "default";
  /** sm：卡片内密排（15px）；md：指标条（18px，label 更小） */
  size?: "sm" | "md";
  truncate?: boolean;
}) {
  const color =
    tone === "up" ? "text-up" : tone === "down" ? "text-down" : tone === "muted" ? "text-muted-foreground" : "text-foreground";
  return (
    <div className="min-w-0 rounded-lg bg-muted/25 px-3 py-2">
      <div className={cn("text-muted-foreground", size === "sm" ? "text-xs" : "text-[11px]", truncate && "truncate")}>
        {label}
      </div>
      <div
        className={cn(
          "mt-1 font-semibold tabular-nums num-in",
          size === "sm" ? "text-[15px]" : "text-lg font-bold leading-tight",
          color,
          truncate && "truncate",
        )}
      >
        {value}
      </div>
      {hint ? (
        <div className={cn("mt-0.5 text-[11px] text-muted-foreground/80", truncate && "truncate")}>{hint}</div>
      ) : null}
    </div>
  );
}

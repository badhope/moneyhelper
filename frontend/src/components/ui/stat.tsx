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

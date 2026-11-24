/** 外部协同页的轻量可视化原件：环形占比、指标块、现金安全垫、比例条。
 *  不引入额外图表依赖，颜色全部走主题令牌，亮暗主题切换即时生效。 */
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type Accent = "primary" | "amber" | "indigo" | "emerald" | "red";

const ACCENTS: Record<Accent, { icon: string; bar: string; glow: string }> = {
  primary: {
    icon: "bg-primary/10 text-primary",
    bar: "bg-primary",
    glow: "from-primary/12 via-primary/5 to-transparent",
  },
  emerald: {
    icon: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300",
    bar: "bg-emerald-500",
    glow: "from-emerald-500/12 via-emerald-500/5 to-transparent",
  },
  amber: {
    icon: "bg-amber-500/14 text-amber-700 dark:text-amber-300",
    bar: "bg-amber-500",
    glow: "from-amber-500/14 via-amber-500/5 to-transparent",
  },
  indigo: {
    icon: "bg-indigo-500/12 text-indigo-700 dark:text-indigo-300",
    bar: "bg-indigo-500",
    glow: "from-indigo-500/12 via-indigo-500/5 to-transparent",
  },
  red: {
    icon: "bg-red-500/12 text-red-700 dark:text-red-300",
    bar: "bg-red-500",
    glow: "from-red-500/12 via-red-500/5 to-transparent",
  },
};

export function OverviewMetric({
  icon,
  label,
  value,
  hint,
  accent = "primary",
  progress,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  hint: string;
  accent?: Accent;
  progress?: number;
}) {
  const theme = ACCENTS[accent];
  return (
    <div className="group relative overflow-hidden rounded-2xl border border-border/50 bg-background/55 p-3.5 backdrop-blur-sm transition-all duration-300 hover:-translate-y-0.5 hover:border-border hover:shadow-[var(--shadow-soft)]">
      <div
        className={cn(
          "pointer-events-none absolute inset-0 bg-gradient-to-br opacity-0 transition-opacity duration-300 group-hover:opacity-100",
          theme.glow,
        )}
      />
      <div className="relative flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[12px] font-medium tracking-wide text-muted-foreground">{label}</div>
          <div className="mt-1 text-[26px] font-bold leading-none tracking-tight tabular-nums num-in">{value}</div>
          <div className="mt-2 line-clamp-2 min-h-[2.1em] text-[11.5px] leading-relaxed [text-wrap:balance] text-muted-foreground/85">{hint}</div>
        </div>
        <div className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-xl", theme.icon)}>{icon}</div>
      </div>
      {progress == null ? null : (
        <div className="relative mt-3 h-1 overflow-hidden rounded-full bg-border/60">
          <div
            className={cn("h-full rounded-full transition-[width] duration-700", theme.bar)}
            style={{ width: `${Math.max(0, Math.min(progress, 100))}%` }}
          />
        </div>
      )}
    </div>
  );
}

export function FigureBlock({
  label,
  value,
  hint,
  tone = "default",
  bar,
  barTone = "primary",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "default" | "positive" | "negative" | "muted";
  bar?: number;
  barTone?: Accent;
}) {
  const color =
    tone === "positive"
      ? "text-emerald-700 dark:text-emerald-400"
      : tone === "negative"
        ? "text-red-700 dark:text-red-400"
        : tone === "muted"
          ? "text-muted-foreground"
          : "text-foreground";
  return (
    <div className="rounded-xl border border-border/45 bg-background/45 px-3 py-2.5">
      <div className="text-[11.5px] text-muted-foreground">{label}</div>
      <div className={cn("mt-1 text-[17px] font-semibold leading-tight tabular-nums", color)}>{value}</div>
      {hint ? <div className="mt-1 truncate text-[11px] text-muted-foreground/80">{hint}</div> : null}
      {bar == null ? null : (
        <div className="mt-2 h-1 overflow-hidden rounded-full bg-border/55">
          <div
            className={cn("h-full rounded-full", ACCENTS[barTone].bar)}
            style={{ width: `${Math.max(0, Math.min(bar, 100))}%` }}
          />
        </div>
      )}
    </div>
  );
}

/** 双段以上环形占比。segments 的总和自动归一化；空数据时显示空心轨道。 */
export function DonutRing({
  segments,
  center,
  size = 132,
  thickness = 11,
  ariaLabel,
}: {
  segments: { value: number; color: string }[];
  center: ReactNode;
  size?: number;
  thickness?: number;
  ariaLabel?: string;
}) {
  const total = segments.reduce((sum, item) => sum + Math.max(0, item.value), 0);
  const safe = total > 0 ? total : 1;
  let cursor = 0;
  const stops = segments.map((item) => {
    const start = cursor;
    cursor += (Math.max(0, item.value) / safe) * 360;
    return `${item.color} ${start}deg ${cursor}deg`;
  });
  const background =
    total > 0
      ? `conic-gradient(from -90deg, ${stops.join(", ")})`
      : "hsl(var(--muted))";
  return (
    <div
      className="relative shrink-0 rounded-full shadow-[0_10px_30px_-16px_rgba(15,23,42,.55)]"
      style={{ width: size, height: size, background, padding: thickness }}
      aria-label={ariaLabel}
      role="img"
    >
      <div className="flex h-full w-full flex-col items-center justify-center rounded-full bg-card/95 text-center shadow-inner backdrop-blur">
        {center}
      </div>
    </div>
  );
}

export function ProgressLine({
  value,
  tone = "primary",
  className,
}: {
  value: number;
  tone?: Accent;
  className?: string;
}) {
  return (
    <div className={cn("h-1.5 overflow-hidden rounded-full bg-border/55", className)}>
      <div
        className={cn("h-full rounded-full transition-[width] duration-700", ACCENTS[tone].bar)}
        style={{ width: `${Math.max(0, Math.min(value, 100))}%` }}
      />
    </div>
  );
}

export function BlockHeading({
  icon,
  title,
  hint,
  aside,
}: {
  icon: ReactNode;
  title: string;
  hint?: string;
  aside?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-2">
      <div className="flex min-w-0 items-center gap-2.5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted/55 text-muted-foreground">
          {icon}
        </div>
        <div className="min-w-0">
          <div className="text-[14px] font-semibold">{title}</div>
          {hint ? <div className="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">{hint}</div> : null}
        </div>
      </div>
      {aside}
    </div>
  );
}

/** 现金安全垫：三根柱 + 0 基线 + 安全垫虚线。负的支付后现金会落到基线下。 */
export function CashFlowChart({
  opening,
  outflow,
  closing,
  floor,
  labels,
  formatter,
}: {
  opening: number;
  outflow: number;
  closing: number;
  floor: number;
  labels: [string, string, string];
  formatter: (value: number) => string;
}) {
  const max = Math.max(opening, outflow, floor, 1);
  const min = Math.min(0, closing, floor);
  const range = Math.max(max - min, 1);
  const top = 18;
  const plot = 126;
  const y = (value: number) => top + ((max - value) / range) * plot;
  const zeroY = y(0);
  const floorY = y(floor);
  const width = 62;
  const xs = [105, 268, 431];
  const values = [opening, outflow, closing];
  const colors = ["hsl(var(--primary))", "#d97706", "#dc2626"];
  const tops = values.map((value) => (value >= 0 ? y(value) : zeroY));
  const heights = values.map((value) => Math.max(Math.abs(value) / range * plot, 2));
  const aria = `${labels[0]} ${formatter(opening)}, ${labels[1]} ${formatter(outflow)}, ${labels[2]} ${formatter(closing)}`;
  return (
    <div>
      <div className="relative overflow-hidden rounded-2xl border border-border/45 bg-background/45 px-3 pt-2">
        <svg viewBox="0 0 600 172" className="h-[166px] w-full" preserveAspectRatio="none" aria-label={aria}>
          <line x1="20" y1={zeroY} x2="580" y2={zeroY} stroke="hsl(var(--border))" strokeWidth="1.5" />
          <line
            x1="20"
            y1={floorY}
            x2="580"
            y2={floorY}
            stroke="#d97706"
            strokeWidth="1.4"
            strokeDasharray="7 5"
            opacity="0.8"
          />
          {values.map((value, index) => (
            <g key={index}>
              <rect
                x={xs[index]}
                y={tops[index]}
                width={width}
                height={heights[index]}
                rx="8"
                fill={colors[index]}
                opacity={index === 2 && value < 0 ? 0.9 : 0.82}
              />
              <rect x={xs[index]} y={tops[index]} width={width} height="3" rx="2" fill="#ffffff" opacity="0.22" />
            </g>
          ))}
        </svg>
        <div className="grid grid-cols-3 gap-2 pb-3 pt-1">
          {labels.map((label, index) => (
            <div key={label} className="text-center">
              <div className="text-[11px] font-medium text-muted-foreground">{label}</div>
              <div
                className={cn(
                  "mt-0.5 text-[13.5px] font-semibold tabular-nums",
                  index === 2 && closing < floor ? "text-red-700 dark:text-red-400" : "text-foreground",
                )}
              >
                {formatter(values[index])}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function ScaleRow({
  label,
  value,
  ratio,
  color,
  hint,
}: {
  label: string;
  value: string;
  ratio: number;
  color: string;
  hint?: string;
}) {
  return (
    <div className="py-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[12px] font-medium text-muted-foreground">{label}</span>
        <span className="text-[16px] font-semibold tabular-nums">{value}</span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-border/55">
        <div
          className="h-full rounded-full transition-[width] duration-700"
          style={{ width: `${Math.max(3, Math.min(ratio, 100))}%`, background: color }}
        />
      </div>
      {hint ? <div className="mt-1 text-[10.5px] text-muted-foreground/80">{hint}</div> : null}
    </div>
  );
}

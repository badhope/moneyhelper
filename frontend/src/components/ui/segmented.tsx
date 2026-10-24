import { cn } from "@/lib/utils";

/** 分段选择器（主题模式 / 密度等）。 */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  size = "md",
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  size?: "sm" | "md";
}) {
  return (
    // 允许换行：7 个供应商按钮在 390px 下总宽 394px，不外溢就只能换行。
    // shrink-0 会把容器钉死在内容宽度，导致右端按钮被裁掉、无法点选。
    <div className="flex max-w-full flex-wrap items-center gap-0.5 rounded-lg bg-muted p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={cn(
            "whitespace-nowrap rounded-md font-medium transition-colors",
            size === "sm" ? "px-2 py-1 text-xs" : "px-2 py-1.5 text-[12px] sm:px-3 sm:text-sm",
            value === o.value
              ? "bg-card text-foreground shadow-xs"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

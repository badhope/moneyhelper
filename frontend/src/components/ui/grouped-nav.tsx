import { useMemo, useState } from "react";
import { ChevronDown } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";

/**
 * 分组导航：把扁平 tab 条按「看/管/算」的认知分组收纳。
 *
 * 为什么改：11 个同级 tab 平铺时，用户每次都要在整条里线性扫描，且看不出
 * 哪个是「日常必看」、哪个是「偶尔配置」。分组后每屏只暴露一组（3-4 项），
 * 当前组用滑块指示，跨组切换是一次显式动作——认知负担从 O(n) 降到 O(1)。
 *
 * 设计取舍：
 *  - 分组由调用方声明（GROUPS），组件不内置业务知识，便于随功能演进调整；
 *  - 当前激活项所在组自动展开，跨组记忆靠「最近访问组」；
 *  - 移动端横向滚动保留，但组标题固定，避免滑到中间失去上下文。
 */

export type NavGroup<T extends string> = {
  id: string;
  labelKey: string;
  items: { key: T; labelKey: string; icon: LucideIcon }[];
};

export function GroupedNav<T extends string>({
  groups,
  value,
  onChange,
}: {
  groups: NavGroup<T>[];
  value: T;
  onChange: (k: T) => void;
}) {
  const { t } = useI18n();
  const activeGroup = useMemo(
    () => groups.find((g) => g.items.some((i) => i.key === value))?.id ?? groups[0]?.id,
    [groups, value],
  );
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const shown = groups.find((g) => g.id === (openGroup ?? activeGroup)) ?? groups[0];

  return (
    <div className="shrink-0 border-b border-border/70 bg-background/80 backdrop-blur-sm">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-1 px-4 py-2 sm:px-6">
        {/* 组选择行：一眼看出分了几类，且当前在哪一类 */}
        <div className="flex items-center gap-1 overflow-x-auto scroll-thin">
          {groups.map((g) => {
            const active = g.id === shown?.id;
            return (
              <button
                key={g.id}
                type="button"
                onClick={() => setOpenGroup(g.id)}
                aria-pressed={active}
                className={cn(
                  "relative shrink-0 rounded-full px-3 py-1 text-[12.5px] transition-colors",
                  active
                    ? "bg-foreground/[0.06] font-medium text-foreground"
                    : "text-muted-foreground hover:bg-foreground/[0.04] hover:text-foreground",
                )}
              >
                {t(g.labelKey)}
                {g.items.some((i) => i.key === value) && !active && (
                  <span className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-primary align-middle" />
                )}
              </button>
            );
          })}
        </div>

        {/* 当前组的子项：图标 + 文案，滑块指示激活态 */}
        {shown && (
          <div
            role="tablist"
            aria-label={t(shown.labelKey)}
            className="flex items-center gap-0.5 overflow-x-auto scroll-thin"
          >
            {shown.items.map((item) => {
              const Icon = item.icon;
              const active = item.key === value;
              return (
                <button
                  key={item.key}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => onChange(item.key)}
                  className={cn(
                    "relative flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] transition-colors",
                    active
                      ? "bg-primary/10 font-medium text-primary"
                      : "text-muted-foreground hover:bg-foreground/[0.04] hover:text-foreground",
                  )}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {t(item.labelKey)}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * 折叠面板：把「次要但需要时可查」的内容收起来，保持首屏信息密度。
 * 默认收起，展开状态由用户控制（不记忆，避免回来时状态错位）。
 */
export function Disclosure({
  title,
  hint,
  children,
  defaultOpen = false,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-border/70 bg-card">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <span className="min-w-0">
          <span className="block text-sm font-medium">{title}</span>
          {hint && <span className="mt-0.5 block text-[11.5px] text-muted-foreground">{hint}</span>}
        </span>
        <ChevronDown
          className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")}
        />
      </button>
      {open && <div className="border-t border-border/60 px-4 py-3">{children}</div>}
    </div>
  );
}

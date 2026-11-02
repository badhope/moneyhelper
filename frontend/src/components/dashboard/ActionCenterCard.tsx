import { ArrowRight, CircleAlert, Sparkles } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type { ActionCenter, ActionItem } from "@/lib/types";

/**
 * 决策中心：把「风险提示 + 目标进度 + 税负机会」收敛成一张可执行清单。
 *
 * 为什么放在总览最上方：用户在总览页的问题是「我现在该做什么」，
 * 而不是「我有多少数据」。原有页面先给一堆指标、把建议埋在底部或另一个
 * 页面里，等于把排序工作推给用户。这里把最紧急的一条置顶并给出一键跳转。
 *
 * 分级视觉：urgent（已发生损失）用警示色 + 左侧色条；其余用中性卡片。
 * 条目自带 impact 文案——没有可量化收益的建议不进清单（后端已过滤）。
 */

const URGENT = 15;

function tone(item: ActionItem) {
  if (item.priority <= URGENT) {
    return {
      wrap: "border-amber-500/35 bg-amber-500/[0.04]",
      bar: "bg-amber-500",
      title: "text-amber-900 dark:text-amber-200",
      icon: "text-amber-600 dark:text-amber-400",
    };
  }
  return {
    wrap: "border-border/70 bg-card",
    bar: "bg-primary/60",
    title: "text-foreground",
    icon: "text-primary",
  };
}

export function ActionCenterCard({
  actions,
  onNavigate,
}: {
  actions?: ActionCenter | null;
  onNavigate?: (tab: string) => void;
}) {
  const { t } = useI18n();
  if (!actions || !actions.items.length) return null;

  return (
    <section className="rounded-xl border border-border/70 bg-card">
      <header className="flex items-center justify-between gap-2 border-b border-border/60 px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          <Sparkles className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-medium">{t("actions.title")}</h2>
          {actions.count > actions.items.length && (
            <span className="rounded-full bg-foreground/[0.06] px-1.5 py-0.5 text-[10.5px] text-muted-foreground">
              {t("actions.more", { n: actions.count - actions.items.length })}
            </span>
          )}
        </div>
        <span className="text-[11px] text-muted-foreground">{t("actions.hint")}</span>
      </header>

      <ul className="divide-y divide-border/50">
        {actions.items.map((item, i) => {
          const c = tone(item);
          const urgent = item.priority <= URGENT;
          return (
            <li key={`${item.domain}-${i}`} className={cn("relative flex gap-3 px-4 py-3", c.wrap)}>
              <span className={cn("absolute left-0 top-0 h-full w-[3px]", c.bar)} aria-hidden />
              <span className="mt-0.5 shrink-0">
                {urgent ? (
                  <CircleAlert className={cn("h-4 w-4", c.icon)} />
                ) : (
                  <span className={cn("mt-1 block h-1.5 w-1.5 rounded-full", c.bar)} />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  <span className={cn("text-[13.5px] font-medium", c.title)}>{item.title}</span>
                  <span className="rounded bg-foreground/[0.05] px-1.5 py-px text-[10.5px] text-muted-foreground">
                    {item.domain_label}
                  </span>
                </div>
                <p className="mt-0.5 text-[12.5px] leading-relaxed text-muted-foreground">
                  {item.detail}
                </p>
                {item.impact && (
                  <p className="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground/85">
                    {item.impact}
                  </p>
                )}
              </div>
              {item.action && item.action_tab && onNavigate && (
                <button
                  type="button"
                  onClick={() => onNavigate(item.action_tab)}
                  className="mt-0.5 inline-flex shrink-0 items-center gap-1 self-start rounded-lg border border-border/80 px-2 py-1 text-[12px] text-foreground/80 transition-colors hover:bg-accent hover:text-foreground"
                >
                  {item.action}
                  <ArrowRight className="h-3 w-3" />
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

import { useEffect, useState } from "react";
import { HeartPulse, Loader2 } from "lucide-react";
import { fetchHealthCheck } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type { HealthReport } from "@/lib/types";

type Status = "good" | "warn" | "bad";

const STATUS_STYLE: Record<Status, { ring: string; text: string; bg: string }> = {
  good: { ring: "border-emerald-500/30", text: "text-emerald-700 dark:text-emerald-400", bg: "bg-emerald-500/10" },
  warn: { ring: "border-amber-500/30", text: "text-amber-700 dark:text-amber-400", bg: "bg-amber-500/10" },
  bad: { ring: "border-red-500/30", text: "text-red-700 dark:text-red-400", bg: "bg-red-500/10" },
};

const asStatus = (s: string): Status => (s === "good" || s === "bad" ? s : "warn");

/** 财务体检整页：评分 + 五维明细。原先是侧栏里的裸文本（直接显示 warn/bad），改为可读的状态卡。 */
export function HealthPage() {
  const { t } = useI18n();
  const [report, setReport] = useState<HealthReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetchHealthCheck(t("hc.locale"))
      .then((r) => alive && setReport(r))
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [t]);

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> {t("hc.checking")}
      </div>
    );
  }
  if (error) return <div className="py-8 text-sm text-red-600">{error}</div>;
  if (!report) return null;

  // 数据不足时后端返回 score=0 + 空 dimensions：不该展示"0 分"（会被误读为极度不健康），
  // 也不该出现三个全 0 的徽章，直接给引导态。
  if (report.dimensions.length === 0) {
    return (
      <div className="rounded-2xl border border-border bg-card px-6 py-14 text-center">
        <HeartPulse className="mx-auto h-8 w-8 text-muted-foreground/50" />
        <p className="mt-3 text-sm font-medium">{t("hc.notEnough")}</p>
        <p className="mt-1.5 text-xs text-muted-foreground">{t("notAdvice")}</p>
      </div>
    );
  }

  const scoreTone =
    report.score >= 80 ? "text-emerald-600" : report.score >= 60 ? "text-amber-600" : "text-red-600";
  const counts = report.dimensions.reduce(
    (acc, d) => {
      acc[asStatus(String(d.status))] += 1;
      return acc;
    },
    { good: 0, warn: 0, bad: 0 } as Record<Status, number>,
  );

  // 维度按状态分组：风险在前、需关注其次、健康最后（用户先看要处理的）
  const order: Record<Status, number> = { bad: 0, warn: 1, good: 2 };
  const sorted = [...report.dimensions].sort((a, b) => order[asStatus(String(a.status))] - order[asStatus(String(b.status))]);

  return (
    <div className="space-y-4">
      {/* 顶部：评分 + 结论 + 五维条，横向铺满（原来 4 张卡在 3 列网格里留空） */}
      <div className="grid gap-4 lg:grid-cols-[16rem_minmax(0,1fr)]">
        <div className="rounded-2xl border border-border bg-card p-5">
          <div className="text-xs text-muted-foreground">{t("hc.score")}</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className={cn("text-5xl font-semibold tabular-nums", scoreTone)}>{report.score}</span>
            <span className="text-sm text-muted-foreground">/ 100</span>
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5 text-[11px]">
            <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-emerald-700 dark:text-emerald-400">
              {t("hc.good")} {counts.good}
            </span>
            <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-amber-700 dark:text-amber-400">
              {t("hc.warn")} {counts.warn}
            </span>
            <span className="rounded-full bg-red-500/10 px-2 py-0.5 text-red-700 dark:text-red-400">
              {t("hc.bad")} {counts.bad}
            </span>
          </div>

          {/* 五维进度条：一眼看出哪一维拖分 */}
          <ul className="mt-4 space-y-2">
            {sorted.map((d) => {
              const st = asStatus(String(d.status));
              const fill =
                st === "good" ? "bg-emerald-500" : st === "warn" ? "bg-amber-500" : "bg-red-500";
              return (
                <li key={d.key}>
                  <div className="flex items-baseline justify-between gap-2 text-[11.5px]">
                    <span className="min-w-0 truncate text-foreground/75">{d.title}</span>
                    <span className={cn("shrink-0", STATUS_STYLE[st].text)}>{t(`hc.${st}`)}</span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
                    <div
                      className={cn("h-full rounded-full", fill)}
                      style={{ width: st === "good" ? "100%" : st === "warn" ? "55%" : "28%" }}
                    />
                  </div>
                </li>
              );
            })}
          </ul>
        </div>

        <div className="rounded-2xl border border-border bg-card p-5">
          <div className="text-sm font-medium">{t("hc.title")}</div>
          <p className="mt-2 text-[15px] leading-relaxed text-foreground/85">{report.summary}</p>

          {/* 优先处理清单：把"要做什么"直接列出来，而不是让用户自己从五维里找 */}
          {sorted.filter((d) => asStatus(String(d.status)) !== "good").length > 0 && (
            <>
              <div className="mt-4 text-xs font-medium text-muted-foreground">{t("hc.todo")}</div>
              <ol className="mt-1.5 space-y-1.5">
                {sorted
                  .filter((d) => asStatus(String(d.status)) !== "good")
                  .slice(0, 4)
                  .map((d) => (
                    <li key={d.key} className="flex gap-2 text-[13px] leading-relaxed">
                      <span className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", STATUS_STYLE[asStatus(String(d.status))].text.replace("text-", "bg-"))} />
                      <span>
                        <b className="font-medium text-foreground/85">{d.title}</b>
                        <span className="ml-1 text-foreground/70">{d.suggestion || d.detail}</span>
                      </span>
                    </li>
                  ))}
              </ol>
            </>
          )}

          <p className="mt-4 text-[11px] text-muted-foreground">{t("notAdvice")}</p>
        </div>
      </div>

      {/* 维度明细：上面已经给了评分与优先处理，这里只放"这一维具体是什么情况 + 建议"。
          不再重复标题状态徽章（那是顶部五维条的职责）。 */}
      <div className="grid gap-3 sm:grid-cols-2">
        {sorted.map((d) => {
          const st = asStatus(String(d.status));
          return (
            <div key={d.key} className="rounded-xl border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <span className={cn("h-2 w-2 rounded-full", STATUS_STYLE[st].text.replace("text-", "bg-"))} />
                <span className="text-sm font-medium">{d.title}</span>
                <span className={cn("ml-auto text-[11px]", STATUS_STYLE[st].text)}>{t(`hc.${st}`)}</span>
              </div>
              <p className="mt-2 text-[13px] leading-relaxed text-foreground/75">{d.detail}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** 模型评测（M6.3）：把「这个模型能不能管钱」变成可复现的分数。
 *
 * 为什么值得放在设置里：用户换模型时最想知道的是"新的比旧的好吗"。
 * 这里用同一套 50 道确定性判据的题跑一遍，给出分类得分与逐题明细，
 * 不用主观印象，也不让 LLM 给自己打分。
 */

import { useState } from "react";
import { Award, FlaskConical, Play, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Section } from "./shared";

interface CategoryScore {
  passed: number;
  total: number;
  weight_earned: number;
  weight_total: number;
  accuracy_pct: number;
}

interface Detail {
  id: string;
  category: string;
  weight: number;
  passed: boolean;
  reason: string;
  answer_preview: string;
}

interface EvalResult {
  scored?: boolean;
  reason?: string;
  score_pct?: number;
  passed?: number;
  question_count?: number;
  weight_earned?: number;
  weight_total?: number;
  by_category?: Record<string, CategoryScore>;
  details?: Detail[];
  model?: string;
  duration_seconds?: number;
  failures?: string[];
}

interface LeaderRow {
  model: string;
  score_pct: number;
  passed: number;
  question_count: number;
  graded_at: string;
}

export function EvalSection() {
  const { t } = useI18n();
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<EvalResult | null>(null);
  const [rows, setRows] = useState<LeaderRow[]>([]);
  const [error, setError] = useState("");
  const [showDetails, setShowDetails] = useState(false);

  const run = async (maxQuestions = 0) => {
    setRunning(true);
    setError("");
    try {
      const r = await api<EvalResult>("/api/eval/run", {
        method: "POST",
        body: JSON.stringify({ max_questions: maxQuestions }),
      });
      setResult(r);
      if (r.scored) {
        const lb = await api<{ leaderboard: LeaderRow[] }>("/api/eval/leaderboard");
        setRows(lb.leaderboard ?? []);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <Section
      title={t("settings.navEval")}
      icon={<FlaskConical className="w-4 h-4 text-muted-foreground" />}
      desc={t("settings.evalDesc")}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => void run(0)} disabled={running}>
          {running ? (
            <RefreshCw className="w-3.5 h-3.5 mr-1.5 animate-spin" />
          ) : (
            <Play className="w-3.5 h-3.5 mr-1.5" />
          )}
          {running ? t("settings.evalRunning") : t("settings.evalRun")}
        </Button>
        <Button size="sm" variant="outline" onClick={() => void run(5)} disabled={running}>
          {t("settings.evalQuick")}
        </Button>
        <span className="text-[11px] text-muted-foreground">{t("settings.evalHint")}</span>
      </div>

      {error && <div className="mb-2 text-xs text-red-500">{error}</div>}

      {result && !result.scored && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/[0.06] px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
          {result.reason || t("settings.evalNotConfigured")}
        </div>
      )}

      {result?.scored && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-baseline gap-3 rounded-lg border border-border bg-muted/20 px-3 py-2.5">
            <span className="text-3xl font-bold tabular-nums">{result.score_pct}</span>
            <span className="text-xs text-muted-foreground">
              / 100 · {result.passed}/{result.question_count} {t("settings.evalPassed")}
            </span>
            <Badge variant="muted" className="ml-auto">
              {result.model} · {result.duration_seconds}s
            </Badge>
          </div>

          <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
            {Object.entries(result.by_category ?? {}).map(([cat, v]) => (
              <div key={cat} className="rounded border border-border px-2 py-1.5">
                <div className="flex items-baseline justify-between">
                  <span className="text-[11px] text-muted-foreground">{t(`settings.evalCat.${cat}`)}</span>
                  <span className="text-[11px] tabular-nums">{v.accuracy_pct}%</span>
                </div>
                <div className="mt-1 h-1 overflow-hidden rounded-full bg-muted">
                  <div
                    className={cn("h-full rounded-full", v.accuracy_pct >= 80 ? "bg-emerald-500" : v.accuracy_pct >= 50 ? "bg-amber-400" : "bg-red-500")}
                    style={{ width: `${v.accuracy_pct}%` }}
                  />
                </div>
              </div>
            ))}
          </div>

          {result.failures && result.failures.length > 0 && (
            <div className="text-[11px] text-amber-600 dark:text-amber-400">
              {t("settings.evalFailures", { n: result.failures.length })}: {result.failures.join("; ")}
            </div>
          )}

          <button
            type="button"
            onClick={() => setShowDetails((v) => !v)}
            className="text-[11px] text-primary hover:underline"
          >
            {showDetails ? t("settings.evalHideDetails") : t("settings.evalShowDetails")}
          </button>

          {showDetails && (
            <div className="max-h-72 space-y-1 overflow-y-auto scroll-thin">
              {(result.details ?? []).map((d) => (
                <div
                  key={d.id}
                  className={cn(
                    "rounded border px-2 py-1 text-[11px]",
                    d.passed ? "border-border" : "border-red-500/30 bg-red-500/[0.04]",
                  )}
                >
                  <div className="flex items-baseline gap-1.5">
                    <span className={cn("font-mono", d.passed ? "text-emerald-600" : "text-red-500")}>
                      {d.passed ? "PASS" : "FAIL"}
                    </span>
                    <span className="font-medium">{d.id}</span>
                    <span className="text-muted-foreground">{t(`settings.evalCat.${d.category}`)}</span>
                    <span className="ml-auto text-muted-foreground">{d.weight}分</span>
                  </div>
                  {!d.passed && (
                    <div className="mt-0.5 text-muted-foreground">
                      {d.reason}
                      {d.answer_preview && <span className="ml-1">· 回答：{d.answer_preview}</span>}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {rows.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 flex items-center gap-1.5 text-xs font-medium">
            <Award className="w-3.5 h-3.5 text-muted-foreground" />
            {t("settings.evalLeaderboard")}
          </div>
          <div className="space-y-0.5">
            {rows.map((r, i) => (
              <div key={`${r.model}-${r.graded_at}-${i}`} className="flex items-baseline gap-2 text-[11px]">
                <span className="w-4 text-muted-foreground">{i + 1}</span>
                <span className="min-w-0 flex-1 truncate">{r.model}</span>
                <span className="tabular-nums">{r.score_pct}</span>
                <span className="text-muted-foreground">
                  {r.passed}/{r.question_count}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">{t("settings.evalFoot")}</p>
    </Section>
  );
}

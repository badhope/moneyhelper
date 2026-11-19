import { useState } from "react";
import { Plus, Target, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { FieldError } from "@/components/ui/field-error";
import { ProgressBar } from "@/components/ui/progress-bar";
import { createGoal, deleteGoal, listGoals, updateGoal } from "@/lib/api";
import { useMutate } from "@/lib/use-mutate";
import { fmtMoney } from "@/lib/format";
import type { Goal } from "@/lib/types";
import { useI18n } from "@/lib/i18n";
import { errMsg } from "@/lib/utils";
import { inputClsCompact as inputCls, labelCls } from "@/components/ui/field";

export function GoalsPanel({ onDone }: { onDone: () => void }) {
  const { t } = useI18n();
  const [f, setF] = useState({ name: "", target: "", saved: "", deadline: "" });
  const [err, setErr] = useState("");

  const create = useMutate<undefined, void>({
    fn: async () => {
      await createGoal({
        name: f.name.trim(),
        target: Number(f.target),
        saved: f.saved ? Number(f.saved) : 0,
        deadline: f.deadline.trim(),
      });
      return undefined;
    },
    key: undefined,
    silentError: true,
    onSettled: (_res, e) => {
      if (e) {
        setErr(errMsg(e));
        return;
      }
      setF({ name: "", target: "", saved: "", deadline: "" });
      onDone();
    },
  });

  const submit = () => {
    setErr("");
    if (!f.name.trim() || !Number(f.target)) {
      setErr(t("goals.errRequired"));
      return;
    }
    void create.mutate(undefined);
  };

  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-2 gap-2.5">
        <div>
          <label className={labelCls}>{t("goals.name")}</label>
          <input className={inputCls} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder={t("goals.namePh")} />
        </div>
        <div>
          <label className={labelCls}>{t("goals.amount")}</label>
          <input className={inputCls} type="number" value={f.target} onChange={(e) => setF({ ...f, target: e.target.value })} placeholder="200000" />
        </div>
        <div>
          <label className={labelCls}>{t("goals.saved")}</label>
          <input className={inputCls} type="number" value={f.saved} onChange={(e) => setF({ ...f, saved: e.target.value })} placeholder="50000" />
        </div>
        <div>
          <label className={labelCls}>{t("goals.deadline")}</label>
          <input className={inputCls} value={f.deadline} onChange={(e) => setF({ ...f, deadline: e.target.value })} placeholder="2027-06" />
        </div>
      </div>
      {err ? <FieldError>{err}</FieldError> : null}
      <Button size="sm" onClick={submit} disabled={create.isPending || !f.name || !f.target}>
        <Plus className="w-3.5 h-3.5" /> {t("goals.add")}
      </Button>
    </div>
  );
}

/** 目标列表：进度 + 建议月存 + 快捷追加 + 删除 */
export function GoalsList({ goals, onDone, onRequestDelete }: { goals: Goal[]; onDone: () => void; onRequestDelete?: (name: string) => void }) {
  const { t } = useI18n();

  const bump = useMutate<{ name: string; amount: number }, void>({
    fn: async (a) => {
      // 拉最新数据再算增量，避免基于闭包旧值（连点两次会丢一次）
      const latest = await listGoals();
      const g = latest.find((x) => x.name === a.name);
      if (g) await updateGoal(a.name, { saved: Math.max(0, g.saved + a.amount) });
      return undefined;
    },
    key: undefined,
    onSettled: (_res, e) => {
      if (!e) onDone();
    },
  });

  const del = useMutate<string, void>({
    fn: (name) => deleteGoal(name).then(() => undefined),
    key: "goals.deleted",
    vars: (a) => ({ name: a }),
    onSettled: (_res, e) => {
      if (!e) onDone();
    },
  });

  if (goals.length === 0) {
    return <EmptyState mode="compact" text={t("goals.empty")} />;
  }

  return (
    <div className="space-y-2.5">
      {goals.map((g) => (
        <div key={g.name} className="rounded-lg border border-border bg-card px-3 py-2">
          <div className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 text-sm font-medium min-w-0">
              <Target className="w-3.5 h-3.5 text-primary shrink-0" />
              <span className="truncate">{g.name}</span>
              {g.done && <Badge variant="ok">{t("goals.done")}</Badge>}
            </span>
            <span className="text-xs text-muted-foreground tabular-nums shrink-0">
              {fmtMoney(g.saved, false)} / {fmtMoney(g.target, false)}
            </span>
          </div>
          <div className="mt-1.5 flex items-center gap-2">
            <div className="flex-1">
              <ProgressBar pct={g.pct} />
            </div>
            <span className="text-xs tabular-nums text-muted-foreground">{g.pct}%</span>
          </div>
          <div className="mt-1.5 flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>
              {g.months_left != null && g.monthly_suggest != null
                ? `${t("goals.daysTo", { d: g.deadline, n: g.months_left })} · ${t("goals.suggest")} ${fmtMoney(g.monthly_suggest, false)}`
                : g.deadline
                  ? t("goals.by", { d: g.deadline })
                  : t("goals.noDeadline")}
              {g.gap > 0 && ` · ${t("goals.gap")} ${fmtMoney(g.gap, false)}`}
            </span>
            <span className="flex items-center gap-1 shrink-0">
              <Button
                size="sm"
                variant="outline"
                className="h-6 px-2"
                disabled={bump.isPending}
                onClick={() => bump.mutate({ name: g.name, amount: 1000 })}
              >
                +1k
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-6 px-2"
                disabled={bump.isPending}
                onClick={() => bump.mutate({ name: g.name, amount: -1000 })}
              >
                -1k
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-6 px-1.5 text-muted-foreground hover:text-red-600"
                aria-label={t("goals.delete", { name: g.name })}
                onClick={() => onRequestDelete ? onRequestDelete(g.name) : del.mutate(g.name)}
              >
                <Trash2 className="w-3.5 h-3.5" />
              </Button>
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

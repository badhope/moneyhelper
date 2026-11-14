import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useMutate } from "@/lib/use-mutate";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { fmtMoney } from "@/lib/format";
import { AiSuggestCard } from "./ai-suggest-card";
import { Section, inputCls, labelCls } from "./shared";

/** 解析每行「类别 金额」→ [{ name, amount }]；忽略格式不正确的行 */
function parseCats(text: string): { name: string; amount: number }[] {
  const out: { name: string; amount: number }[] = [];
  for (const line of text.split("\n")) {
    const m = line.trim().match(/^(.+?)\s+(\d+(?:\.\d+)?)$/);
    if (m && Number(m[2]) > 0) out.push({ name: m[1].trim(), amount: Number(m[2]) });
  }
  return out;
}

type BudgetSuggestion = { total: number; categories: Record<string, number> };

/** 预算编辑（总额 + 分类行），状态与保存逻辑已下沉到本组件 */
export function BudgetSection() {
  const { t } = useI18n();
  const { toast } = useToast();
  const [budgetTotal, setBudgetTotal] = useState("");
  const [budgetCats, setBudgetCats] = useState("");

  const applySuggestion = (s: BudgetSuggestion) => {
    setBudgetTotal(String(s.total));
    setBudgetCats(Object.entries(s.categories).map(([k, v]) => `${k} ${v}`).join("\n"));
    toast(t("settings.budgetAiApplied"), "ok");
  };

  const save = useMutate<{ category: string; amount: number }[], void>({
    fn: async (items) => {
      await api("/api/budgets", { method: "PUT", body: JSON.stringify({ budgets: items }) });
      return undefined;
    },
    key: "settings.budgetSaved",
  });

  useEffect(() => {
    let alive = true;
    api<{ budgets: { key: string; amount: number }[] }>("/api/budgets")
      .then((d) => {
        if (!alive) return;
        const total = d.budgets.find((b) => b.key === "__total");
        setBudgetTotal(total ? String(total.amount) : "");
        setBudgetCats(
          d.budgets
            .filter((b) => b.key !== "__total")
            .map((b) => `${b.key} ${b.amount}`)
            .join("\n"),
        );
      })
      .catch(() => {
        /* 预算读取失败不阻塞设置页 */
      });
    return () => {
      alive = false;
    };
  }, []);

  const doSave = () => {
    const items: { category: string; amount: number }[] = [];
    const total = Number(budgetTotal);
    if (Number.isFinite(total) && total > 0) items.push({ category: "__total", amount: total });
    for (const c of parseCats(budgetCats)) items.push({ category: c.name, amount: c.amount });
    void save.mutate(items);
  };

  // 实时预览：总预算 vs 分类合计（类别颜色与占比），保存前往分配是否合理一眼可见
  const previewTotal = Number(budgetTotal) || 0;
  const previewCats = useMemo(() => parseCats(budgetCats), [budgetCats]);
  const catsSum = previewCats.reduce((s, c) => s + c.amount, 0);

  return (
    <Section title={t("settings.navBudget")} desc={t("settings.budgetDesc")}>
      <div className="space-y-3">
        <div>
          <label className={labelCls} htmlFor="budgetsect-1">{t("settings.budgetTotal")}</label>
          <input id="budgetsect-1" className={inputCls} type="number" min="0" value={budgetTotal} onChange={(e) => setBudgetTotal(e.target.value)} placeholder={t("settings.budgetTotalPh")} />
        </div>
        <div>
          <label className={labelCls} htmlFor="budgetsect-2">{t("settings.budgetCats")}</label>
          <textarea id="budgetsect-2"
            className={`${inputCls} min-h-24`}
            value={budgetCats}
            onChange={(e) => setBudgetCats(e.target.value)}
            placeholder={t("settings.budgetCatsPh")}
          />
        </div>
        {/* AI 建议预算：按近两月实际支出生成，采用后填入上方表单（人工确认再保存） */}
        <AiSuggestCard<BudgetSuggestion>
          title={t("settings.budgetAi")}
          hint={t("settings.budgetAiHint")}
          endpoint="/api/budgets/suggest"
          onAdopt={applySuggestion}
          renderSuggestion={(s) => (
            <>
              <div className="text-sm font-medium">
                {t("settings.budgetAiTotal")} {fmtMoney(s.total)}
              </div>
              <ul className="mt-1 space-y-0.5">
                {Object.entries(s.categories).map(([k, v]) => (
                  <li key={k} className="flex justify-between text-xs">
                    <span>{k}</span>
                    <span className="tabular-nums">{fmtMoney(v)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        />

        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            {budgetTotal ? `${t("settings.budgetTotalLabel")} ${fmtMoney(previewTotal)}` : t("settings.budgetNone")} · {t("settings.budgetCatCount", { n: previewCats.length })}
          </span>
          <Button variant="outline" size="sm" onClick={doSave} disabled={save.isPending}>
            {t("settings.saveBudget")}
          </Button>
        </div>

        {/* 实时预览：各类别占总额比例。总额未设置时以分类合计为分母 */}
        {previewCats.length > 0 && (
          <div className="rounded-lg border border-dashed border-border bg-muted/20 p-3">
            <div className="text-xs text-muted-foreground mb-1.5">{t("settings.budgetPreview")}</div>
            {(() => {
              const denom = previewTotal > 0 ? previewTotal : catsSum;
              const ordered = [...previewCats].sort((a, b) => b.amount - a.amount);
              return (
                <>
                  <div className="flex h-2 w-full overflow-hidden rounded-full bg-muted">
                    {ordered.map((c, i) => {
                      const segPct = denom > 0 ? (c.amount / denom) * 100 : 0;
                      const color = ["bg-rose-500", "bg-sky-500", "bg-amber-500", "bg-emerald-500", "bg-violet-500", "bg-orange-500"][i % 6];
                      return segPct > 0
                        ? <div key={c.name} className={`h-full ${color}`} style={{ width: `${segPct}%` }} />
                        : null;
                    })}
                  </div>
                  <ul className="mt-2 space-y-0.5">
                    {ordered.slice(0, 5).map((c, i) => {
                      const pct = denom > 0 ? Math.round((c.amount / denom) * 100) : 0;
                      const color = ["bg-rose-500", "bg-sky-500", "bg-amber-500", "bg-emerald-500", "bg-violet-500", "bg-orange-500"][i % 6];
                      return (
                        <li key={c.name} className="flex items-center gap-2 text-xs">
                          <span className={`w-2 h-2 rounded-full shrink-0 ${color}`} />
                          <span className="truncate">{c.name}</span>
                          <span className="ml-auto tabular-nums text-muted-foreground">{fmtMoney(c.amount)} · {pct}%</span>
                        </li>
                      );
                    })}
                    {previewCats.length > 5 && <li className="text-xs text-muted-foreground">+{previewCats.length - 5}</li>}
                  </ul>
                  {previewTotal > 0 && catsSum > previewTotal && (
                    <div className="mt-1 text-xs text-red-500">{t("settings.budgetOverBy", { over: fmtMoney(catsSum - previewTotal) })}</div>
                  )}
                </>
              );
            })()}
          </div>
        )}
      </div>
    </Section>
  );
}

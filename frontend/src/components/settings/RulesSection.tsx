import { useState } from "react";
import { Wallet } from "lucide-react";
import { Section, inputCls, labelCls } from "./shared";
import { AiSuggestCard } from "./ai-suggest-card";
import { useI18n } from "@/lib/i18n";

type RulesSuggestion = {
  monthly_income: number;
  emergency_target_months: number;
  essential_categories: string;
  savings_goal: number;
};

/** 账本假设表单（月收入 / 应急目标 / 必选类别 / 储蓄比例），走底部批量保存。
 *  「AI 建议假设」按近两月收支生成建议，采用后填入表单（仍需底部保存生效）。 */
export function RulesSection({
  form,
  onField,
}: {
  form: Record<string, string>;
  onField: (k: string, v: string) => void;
}) {
  const { t } = useI18n();
  const [adopted, setAdopted] = useState(false);

  const apply = (s: RulesSuggestion) => {
    onField("monthly_income", String(s.monthly_income));
    onField("emergency_target_months", String(s.emergency_target_months));
    onField("essential_categories", s.essential_categories);
    onField("savings_goal", String(s.savings_goal));
    setAdopted(true);
  };

  return (
    <Section title={t("settings.navRules")} icon={<Wallet className="w-4 h-4 text-muted-foreground" />} desc={t("settings.rulesDesc")}>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelCls} htmlFor="rulessecti-1">{t("settings.monthlyIncome")}</label>
          <input id="rulessecti-1" className={inputCls} type="number" value={form.monthly_income ?? ""} onChange={(e) => onField("monthly_income", e.target.value)} />
        </div>
        <div>
          <label className={labelCls} htmlFor="rulessecti-2">{t("settings.emergencyTarget")}</label>
          <input id="rulessecti-2" className={inputCls} type="number" value={form.emergency_target_months ?? ""} onChange={(e) => onField("emergency_target_months", e.target.value)} />
        </div>
        <div className="col-span-2">
          <label className={labelCls} htmlFor="rulessecti-3">{t("settings.essentialCats")}</label>
          <input id="rulessecti-3" className={inputCls} value={form.essential_categories ?? ""} onChange={(e) => onField("essential_categories", e.target.value)} placeholder={t("settings.essentialPh")} />
        </div>
        <div>
          <label className={labelCls} htmlFor="rulessecti-4">{t("settings.savingsGoal")}</label>
          <input id="rulessecti-4" className={inputCls} type="number" value={form.savings_goal ?? "20"} onChange={(e) => onField("savings_goal", e.target.value)} />
        </div>
      </div>

      {/* AI 建议账本假设：按近两月收支生成，采用后填入表单 */}
      <div className="mt-3">
        <AiSuggestCard<RulesSuggestion>
          title={t("settings.rulesAi")}
          hint={t("settings.rulesAiHint")}
          endpoint="/api/rules/suggest"
          onAdopt={apply}
          renderSuggestion={(s) => (
            <div className="grid grid-cols-2 gap-1 text-xs">
              <span className="text-muted-foreground">{t("settings.monthlyIncome")}</span>
              <span className="text-right tabular-nums">{s.monthly_income}</span>
              <span className="text-muted-foreground">{t("settings.emergencyTarget")}</span>
              <span className="text-right tabular-nums">{s.emergency_target_months}</span>
              <span className="text-muted-foreground">{t("settings.savingsGoal")}</span>
              <span className="text-right tabular-nums">{s.savings_goal}%</span>
              <span className="text-muted-foreground">{t("settings.essentialCats")}</span>
              <span className="text-right">{s.essential_categories}</span>
            </div>
          )}
        />
        {adopted && <div className="mt-1 text-xs text-muted-foreground">{t("settings.rulesAiApplied")}</div>}
      </div>
    </Section>
  );
}

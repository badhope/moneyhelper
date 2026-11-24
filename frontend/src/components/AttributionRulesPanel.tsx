/** 归因规则（4.17.3）：自定义关键词优先于内置规则，只产候选、不自动改账。 */

import { useEffect, useState } from "react";
import { AlertTriangle, Pencil, Plus, Sparkles, Trash2, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/lib/i18n";
import {
  useAttributionRules,
  useAttributionStats,
  useCreateAttributionRule,
  useDeleteAttributionRule,
  useTestAttributionRule,
  useUpdateAttributionRule,
  type AttributionRule,
} from "@/lib/use-finance-tax";

type Draft = {
  name: string;
  keyword: string;
  category: string;
  direction: "" | "收入" | "支出";
  priority: string;
  merchant: string;
  minAmount: string;
  maxAmount: string;
  memberId: string;
};

const EMPTY_DRAFT: Draft = {
  name: "",
  keyword: "",
  category: "",
  direction: "",
  priority: "0",
  merchant: "",
  minAmount: "",
  maxAmount: "",
  memberId: "",
};

export function AttributionRulesPanel({ ruleHits = {} }: { ruleHits?: Record<string, number> }) {
  const { t } = useI18n();
  const { data, isLoading, error } = useAttributionRules();
  const stats = useAttributionStats();
  const create = useCreateAttributionRule();
  const update = useUpdateAttributionRule();
  const remove = useDeleteAttributionRule();
  const test = useTestAttributionRule();
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState("");
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [testItem, setTestItem] = useState("");

  useEffect(() => {
    if (!editingId) return;
    const rule = data?.rules.find((r) => r.rule_id === editingId);
    if (!rule) return;
    setDraft({
      name: rule.name,
      keyword: rule.keyword,
      category: rule.category,
      direction: rule.direction,
      priority: String(rule.priority),
      merchant: rule.merchant ?? "",
      minAmount: rule.min_amount_cents ? String(rule.min_amount_cents / 100) : "",
      maxAmount: rule.max_amount_cents ? String(rule.max_amount_cents / 100) : "",
      memberId: rule.member_id ? String(rule.member_id) : "",
    });
  }, [data, editingId]);

  if (isLoading) {
    return (
      <Card className="p-[var(--card-pad)]">
        <Skeleton className="mb-3 h-4 w-32" />
        <Skeleton className="h-20 w-full" />
      </Card>
    );
  }
  if (error) {
    return (
      <Card className="p-[var(--card-pad)]">
        <div className="flex items-center gap-2 text-[12px] text-down">
          <AlertTriangle className="h-4 w-4" />
          {error instanceof Error ? error.message : String(error)}
        </div>
      </Card>
    );
  }
  if (!data) return null;

  const busy = create.isPending || update.isPending || remove.isPending;
  const actionError = create.error || update.error || remove.error;

  const save = () => {
    const body = {
      name: draft.name.trim() || draft.keyword.trim(),
      keyword: draft.keyword.trim(),
      category: draft.category,
      direction: draft.direction,
      priority: Number(draft.priority || 0),
      merchant: draft.merchant.trim(),
      min_amount_cents: draft.minAmount ? Math.round(Number(draft.minAmount) * 100) : 0,
      max_amount_cents: draft.maxAmount ? Math.round(Number(draft.maxAmount) * 100) : 0,
      member_id: draft.memberId ? Number(draft.memberId) : null,
    };
    if (editingId) {
      update.mutate(
        { ruleId: editingId, body },
        {
          onSuccess: () => {
            setEditingId("");
            setShowForm(false);
            setDraft(EMPTY_DRAFT);
          },
        },
      );
      return;
    }
    create.mutate(body, {
      onSuccess: () => {
        setShowForm(false);
        setDraft(EMPTY_DRAFT);
        setTestItem("");
        test.reset();
      },
    });
  };

  const startEdit = (rule: AttributionRule) => {
    setEditingId(rule.rule_id);
    setShowForm(true);
    test.reset();
  };

  const cancel = () => {
    setEditingId("");
    setShowForm(false);
    setDraft(EMPTY_DRAFT);
    test.reset();
  };

  const fields = (
    <div className="mt-2 grid gap-2 sm:grid-cols-2">
      <label className="text-[10.5px] text-muted-foreground">
        {t("tax.attrRuleName")}
        <input
          value={draft.name}
          onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
          placeholder={t("tax.attrRuleName")}
          className="mt-1 h-8 w-full rounded-md border border-border bg-background px-2 text-[11.5px]"
        />
      </label>
      <label className="text-[10.5px] text-muted-foreground">
        {t("tax.attrRuleKeyword")}
        <input
          value={draft.keyword}
          onChange={(e) => setDraft((d) => ({ ...d, keyword: e.target.value }))}
          placeholder="云 GPU / 打车 / 房租"
          className="mt-1 h-8 w-full rounded-md border border-border bg-background px-2 text-[11.5px]"
        />
      </label>
      <label className="text-[10.5px] text-muted-foreground">
        {t("tax.attrRuleCategory")}
        <input
          list="attribution-categories"
          value={draft.category}
          onChange={(e) => setDraft((d) => ({ ...d, category: e.target.value }))}
          placeholder="办公软件 / 餐饮 / 交通"
          className="mt-1 h-8 w-full rounded-md border border-border bg-background px-2 text-[11.5px]"
        />
        <datalist id="attribution-categories">
          {data.categories.map((cat) => (
            <option key={cat} value={cat} />
          ))}
        </datalist>
      </label>
      <div className="grid grid-cols-2 gap-2">
        <label className="text-[10.5px] text-muted-foreground">
          {t("tax.attrRuleDirection")}
          <select
            value={draft.direction}
            onChange={(e) =>
              setDraft((d) => ({ ...d, direction: e.target.value as Draft["direction"] }))
            }
            className="mt-1 h-8 w-full rounded-md border border-border bg-background px-2 text-[11.5px]"
          >
            <option value="">{t("tax.attrRuleDirectionAny")}</option>
            <option value="支出">支出</option>
            <option value="收入">收入</option>
          </select>
        </label>
        <label className="text-[10.5px] text-muted-foreground">
          {t("tax.attrRulePriority")}
          <input
            type="number"
            min={-100}
            max={100}
            value={draft.priority}
            onChange={(e) => setDraft((d) => ({ ...d, priority: e.target.value }))}
            className="mt-1 h-8 w-full rounded-md border border-border bg-background px-2 text-[11.5px]"
          />
        </label>
      </div>
      <label className="text-[10.5px] text-muted-foreground">
        {t("tax.attrRuleMerchant")}
        <input
          value={draft.merchant}
          onChange={(e) => setDraft((d) => ({ ...d, merchant: e.target.value }))}
          placeholder={t("tax.attrRuleMerchantHint")}
          className="mt-1 h-8 w-full rounded-md border border-border bg-background px-2 text-[11.5px]"
        />
      </label>
      <label className="text-[10.5px] text-muted-foreground">
        {t("tax.attrRuleMember")}
        <input
          type="number"
          min={1}
          value={draft.memberId}
          onChange={(e) => setDraft((d) => ({ ...d, memberId: e.target.value }))}
          placeholder={t("tax.attrRuleAny")}
          className="mt-1 h-8 w-full rounded-md border border-border bg-background px-2 text-[11.5px]"
        />
      </label>
      <div className="grid grid-cols-2 gap-2">
        <label className="text-[10.5px] text-muted-foreground">
          {t("tax.attrRuleMin")}
          <input
            type="number"
            min={0}
            step="0.01"
            value={draft.minAmount}
            onChange={(e) => setDraft((d) => ({ ...d, minAmount: e.target.value }))}
            placeholder={t("tax.attrRuleAny")}
            className="mt-1 h-8 w-full rounded-md border border-border bg-background px-2 text-[11.5px]"
          />
        </label>
        <label className="text-[10.5px] text-muted-foreground">
          {t("tax.attrRuleMax")}
          <input
            type="number"
            min={0}
            step="0.01"
            value={draft.maxAmount}
            onChange={(e) => setDraft((d) => ({ ...d, maxAmount: e.target.value }))}
            placeholder={t("tax.attrRuleAny")}
            className="mt-1 h-8 w-full rounded-md border border-border bg-background px-2 text-[11.5px]"
          />
        </label>
      </div>
      <div className="sm:col-span-2 rounded-md bg-muted/40 p-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <input
            value={testItem}
            onChange={(e) => setTestItem(e.target.value)}
            placeholder={t("tax.attrRuleTestHint")}
            className="h-8 min-w-[10rem] flex-1 rounded-md border border-border bg-background px-2 text-[11px]"
          />
          <Button
            size="sm"
            variant="outline"
            disabled={!testItem.trim() || !draft.keyword.trim() || !draft.category}
            onClick={() =>
              test.mutate({
                item: testItem,
                direction: draft.direction || "支出",
                amount: (() => {
                  const n = Number(draft.minAmount || draft.maxAmount || 100);
                  return draft.direction === "收入" ? n : -n;
                })(),
                rule: {
                  name: draft.name,
                  keyword: draft.keyword,
                  category: draft.category,
                  direction: draft.direction,
                  priority: Number(draft.priority || 0),
                  merchant: draft.merchant.trim(),
                  min_amount_cents: draft.minAmount ? Math.round(Number(draft.minAmount) * 100) : 0,
                  max_amount_cents: draft.maxAmount ? Math.round(Number(draft.maxAmount) * 100) : 0,
                  member_id: draft.memberId ? Number(draft.memberId) : null,
                },
              })
            }
          >
            {t("tax.attrRuleTest")}
          </Button>
        </div>
        {test.data ? (
          <p
            className={`mt-1 text-[10.5px] ${
              test.data.matched ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground"
            }`}
          >
            {test.data.matched
              ? t("tax.attrRuleTestMatched", { c: test.data.candidate?.category ?? "" })
              : t("tax.attrRuleTestMiss")}
          </p>
        ) : null}
        {test.error ? (
          <p className="mt-1 text-[10.5px] text-down">
            {test.error instanceof Error ? test.error.message : String(test.error)}
          </p>
        ) : null}
      </div>
      <div className="sm:col-span-2 flex items-center justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={cancel}>
          <X className="mr-1 h-3.5 w-3.5" />
          {t("tax.attrRuleCancel")}
        </Button>
        <Button size="sm" disabled={busy} onClick={save}>
          {busy ? t("tax.attrRuleSaving") : t("tax.attrRuleSave")}
        </Button>
      </div>
    </div>
  );

  return (
    <Card className="p-[var(--card-pad)]">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-1.5 text-[13px] font-medium">
            <Sparkles className="h-4 w-4 text-primary" />
            {t("tax.attrRules")}
          </div>
          <p className="mt-1 max-w-2xl text-[11.5px] leading-relaxed text-muted-foreground">
            {t("tax.attrRulesDesc")}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="muted">{data.count}/{data.max_rules}</Badge>
          {stats.data ? (
            <>
              <Badge variant="ok">{t("tax.attrResolved", { n: String(stats.data.confirmed_total) })}</Badge>
              {stats.data.reverted_total ? (
                <Badge variant="warn">
                  {t("tax.attrRollback")} {stats.data.reverted_total}
                </Badge>
              ) : null}
            </>
          ) : null}
          {!showForm ? (
            <Button
              size="sm"
              variant="outline"
              disabled={data.count >= data.max_rules}
              onClick={() => {
                setEditingId("");
                setDraft(EMPTY_DRAFT);
                setShowForm(true);
              }}
            >
              <Plus className="mr-1 h-3.5 w-3.5" />
              {t("tax.attrRuleNew")}
            </Button>
          ) : null}
        </div>
      </div>

      {actionError ? (
        <p className="mt-2 text-[11px] text-down">
          {actionError instanceof Error ? actionError.message : String(actionError)}
        </p>
      ) : null}

      {showForm ? (
        <div className="mt-2 rounded-md border border-border/70 p-2">
          {fields}
        </div>
      ) : null}

      {data.rules.length === 0 && !showForm ? (
        <div className="mt-2">
          <EmptyState mode="compact" text={t("tax.attrRuleEmpty")} />
        </div>
      ) : (
        <div className="mt-2 divide-y divide-border/70">
          {data.rules.map((rule) => (
            <div key={rule.rule_id} className="py-2">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="truncate text-[12px] font-medium">{rule.name}</span>
                    <Badge variant={rule.enabled ? "ok" : "muted"}>
                      {rule.enabled ? t("tax.attrRuleEnabled") : t("tax.attrRuleDisabled")}
                    </Badge>
                    <Badge variant="default">{rule.category}</Badge>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10.5px] text-muted-foreground">
                    <code className="rounded bg-muted/60 px-1 py-0.5">“{rule.keyword}”</code>
                    <span>→ {rule.category}</span>
                    <span>· {rule.direction || t("tax.attrRuleDirectionAny")}</span>
                    <span>· P{rule.priority}</span>
                    {rule.merchant ? <span>· {t("tax.attrRuleMerchant")} {rule.merchant}</span> : null}
                    {rule.min_amount_cents || rule.max_amount_cents ? (
                      <span>
                        · {t("tax.attrRuleAmount")} {" "}
                        {rule.min_amount_cents ? `≥${rule.min_amount_cents / 100}` : ""}
                        {rule.min_amount_cents && rule.max_amount_cents ? "-" : ""}
                        {rule.max_amount_cents ? `≤${rule.max_amount_cents / 100}` : ""}
                      </span>
                    ) : null}
                    {rule.member_id ? <span>· {t("tax.attrRuleMember")} #{rule.member_id}</span> : null}
                  </div>
                  <p className="mt-1 text-[10px] text-muted-foreground">
                    {t("tax.attrRuleStats", {
                      n: String(ruleHits[rule.rule_id] ?? 0),
                      c: String(rule.confirmed),
                      r: String(rule.reverted),
                    })}
                  </p>
                </div>
                <div className="flex items-center gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      update.mutate({ ruleId: rule.rule_id, body: { enabled: !rule.enabled } })
                    }
                  >
                    {rule.enabled ? t("tax.attrRuleDisabled") : t("tax.attrRuleEnabled")}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => startEdit(rule)}>
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      if (window.confirm(`${t("tax.attrRuleDelete")} “${rule.name}”?`)) {
                        remove.mutate(rule.rule_id);
                      }
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5 text-down" />
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      <p className="mt-2 text-[10px] text-muted-foreground">
        {t("tax.attrRuleLimit", { n: String(data.max_rules) })} · {data.boundary}
      </p>
    </Card>
  );
}

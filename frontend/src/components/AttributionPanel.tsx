/** 收支归因确认（4.17.1）：规则/历史候选，用户点确认后才写回分类。
 *
 * 这里刻意不做“AI 猜完直接改账”：每条候选都显示来源、规则 id 与置信度，
 * 兜底行要求用户自己选分类，避免把错误归因静默写进账本。
 */

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ListChecks,
  Loader2,
  Settings2,
  Sparkles,
  Undo2,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { fmtMoney, pnlClass } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { AttributionRulesPanel } from "@/components/AttributionRulesPanel";
import {
  useAttributionCandidates,
  useAttributionStats,
  useConfirmAttribution,
  useConfirmAttributionBatch,
  useConfirmedAttributions,
  useRollbackAttribution,
  type AttributionRow,
} from "@/lib/use-finance-tax";

type Pick = {
  category: string;
  source: string;
  confidence: number;
  rule_id: string;
  matched: string[];
};

function sourceLabel(source: string, t: (k: string) => string): string {
  if (source === "custom_rule") return t("tax.attrSourceCustom");
  if (source === "rule") return t("tax.attrRule");
  if (source === "history") return t("tax.attrHistory");
  if (source === "existing") return t("tax.attrExisting");
  return t("tax.attrFallback");
}

function badgeVariant(source: string): "default" | "ok" | "warn" | "muted" {
  if (source === "custom_rule" || source === "rule") return "default";
  if (source === "history") return "ok";
  if (source === "existing") return "muted";
  return "warn";
}

export function AttributionPanel() {
  const { t } = useI18n();
  const { data, isLoading, error } = useAttributionCandidates(50);
  const confirm = useConfirmAttribution();
  const batch = useConfirmAttributionBatch();
  const rollback = useRollbackAttribution();
  const confirmedList = useConfirmedAttributions(12);
  const stats = useAttributionStats();
  const [picks, setPicks] = useState<Record<number, Pick>>({});
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [showRules, setShowRules] = useState(false);

  useEffect(() => {
    if (!data) return;
    setPicks((prev) => {
      const next = { ...prev };
      for (const row of data.transactions) {
        const current = next[row.transaction_id];
        if (current?.source === "manual") continue;
        if (row.candidate.source === "fallback") {
          delete next[row.transaction_id];
          continue;
        }
        const changed =
          !current ||
          current.category !== row.candidate.category ||
          current.source !== row.candidate.source ||
          current.rule_id !== row.candidate.rule_id;
        if (changed) {
          next[row.transaction_id] = {
            category: row.candidate.category,
            source: row.candidate.source,
            confidence: row.candidate.confidence,
            rule_id: row.candidate.rule_id,
            matched: row.candidate.matched,
          };
        }
      }
      return next;
    });
  }, [data]);

  const rows = useMemo(() => data?.transactions ?? [], [data]);
  // 已选分类可能来自刚被删除/停用的规则；把它并入下拉选项，避免 select 显示空值却仍可提交。
  const categoryOptions = useMemo(
    () =>
      Array.from(
        new Set([
          ...(data?.categories ?? []),
          ...Object.values(picks)
            .map((pick) => pick.category)
            .filter(Boolean),
        ]),
      ),
    [data, picks],
  );
  const selectedRows = useMemo(
    () => rows.filter((row) => selected.has(row.transaction_id)),
    [rows, selected],
  );
  const selectedReady =
    selectedRows.length > 0 &&
    selectedRows.every((row) => Boolean(picks[row.transaction_id]?.category));
  const done = confirm.isSuccess || batch.isSuccess;

  if (isLoading) {
    return (
      <Card className="p-[var(--card-pad)]">
        <Skeleton className="mb-3 h-4 w-40" />
        <Skeleton className="h-36 w-full" />
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

  const selectPick = (row: AttributionRow, category: string, meta?: Partial<Pick>) => {
    setPicks((prev) => ({
      ...prev,
      [row.transaction_id]: {
        category,
        source: meta?.source ?? row.candidate.source,
        confidence: meta?.confidence ?? row.candidate.confidence,
        rule_id: meta?.rule_id ?? row.candidate.rule_id,
        matched: meta?.matched ?? row.candidate.matched,
      },
    }));
  };

  return (
    <div className="space-y-3">
      <Card className="p-[var(--card-pad)]">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <div className="flex items-center gap-1.5 text-[13px] font-medium">
              <Sparkles className="h-4 w-4 text-primary" />
              {t("tax.attrTitle")}
            </div>
            <p className="mt-1 max-w-2xl text-[11.5px] leading-relaxed text-muted-foreground">
              {t("tax.attrDesc")}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="warn">{t("tax.attrPending", { n: String(data.pending) })}</Badge>
            <Badge variant="ok">{t("tax.attrResolved", { n: String(data.resolved) })}</Badge>
            {stats.data?.reverted_total ? (
              <Badge variant="muted">
                {t("tax.attrRollback")} {stats.data.reverted_total}
              </Badge>
            ) : null}
            <Button size="sm" variant="outline" onClick={() => setShowRules((v) => !v)}>
              <Settings2 className="mr-1 h-3.5 w-3.5" />
              {t("tax.attrRuleManage")}
            </Button>
          </div>
        </div>
        {done ? (
          <div className="mt-2 flex items-center gap-1.5 text-[11.5px] text-emerald-600 dark:text-emerald-400">
            <CheckCircle2 className="h-3.5 w-3.5" />
            {t("tax.attrConfirmed")}
          </div>
        ) : null}
        {confirm.error ? (
          <div className="mt-2 flex items-center gap-1.5 text-[11.5px] text-red-600 dark:text-red-400">
            <AlertTriangle className="h-3.5 w-3.5" />
            {confirm.error instanceof Error ? confirm.error.message : String(confirm.error)}
          </div>
        ) : null}
        <p className="mt-2 text-[10.5px] text-muted-foreground">
          {t("tax.attrScanLimit", { n: String(data.scan_limit) })}
        </p>
      </Card>

      {showRules ? <AttributionRulesPanel ruleHits={data.custom_rule_hits} /> : null}

      {rows.length ? (
        <Card className="flex flex-wrap items-center gap-2 p-[var(--card-pad)]">
          <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <input
              type="checkbox"
              checked={selectedRows.length === rows.length && rows.length > 0}
              onChange={(e) =>
                setSelected(
                  e.target.checked
                    ? new Set(rows.map((row) => row.transaction_id))
                    : new Set(),
                )
              }
            />
            {t("tax.attrBatchAll")}
          </label>
          <Badge variant="muted">
            {t("tax.attrBatchSelected", { n: String(selectedRows.length) })}
          </Badge>
          {selectedRows.length ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setSelected(new Set())}
            >
              {t("tax.attrBatchClear")}
            </Button>
          ) : null}
          <div className="ml-auto flex items-center gap-2">
            {selectedRows.length && !selectedReady ? (
              <span className="text-[10.5px] text-amber-600 dark:text-amber-400">
                {t("tax.attrBatchNeedPick")}
              </span>
            ) : null}
            <Button
              size="sm"
              disabled={!selectedReady || batch.isPending}
              onClick={() =>
                batch.mutate(
                  selectedRows.map((row) => {
                    const pick = picks[row.transaction_id];
                    return {
                      transaction_id: row.transaction_id,
                      category: pick.category,
                      source: pick.source,
                      rule_id: pick.rule_id,
                      confidence: pick.confidence,
                      matched: pick.matched,
                    };
                  }),
                  { onSuccess: () => setSelected(new Set()) },
                )
              }
            >
              {batch.isPending ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <ListChecks className="mr-1 h-3.5 w-3.5" />
              )}
              {t("tax.attrBatchSelect")}
            </Button>
          </div>
          {batch.isSuccess ? (
            <span className="w-full text-[10.5px] text-emerald-600 dark:text-emerald-400">
              {t("tax.attrBatchDone", { n: String(batch.data.confirmed) })}
            </span>
          ) : null}
          {batch.error ? (
            <span className="w-full text-[10.5px] text-down">
              {batch.error instanceof Error ? batch.error.message : String(batch.error)}
            </span>
          ) : null}
        </Card>
      ) : null}

      {rows.length === 0 ? (
        <Card className="p-[var(--card-pad)]">
          <EmptyState mode="compact" text={t("tax.attrEmpty")} />
        </Card>
      ) : (
        <Card className="divide-y divide-border/70 p-0">
          {rows.map((row) => {
            const pick = picks[row.transaction_id];
            const busy = confirm.isPending && confirm.variables?.transaction_id === row.transaction_id;
            return (
              <div key={row.transaction_id} className="p-[var(--card-pad)]">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="flex min-w-0 items-start gap-2">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={selected.has(row.transaction_id)}
                      onChange={(e) =>
                        setSelected((prev) => {
                          const next = new Set(prev);
                          if (e.target.checked) next.add(row.transaction_id);
                          else next.delete(row.transaction_id);
                          return next;
                        })
                      }
                    />
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-[12.5px] font-medium">{row.item}</span>
                        <span className="text-[10.5px] text-muted-foreground">{row.date}</span>
                      </div>
                      <div className="mt-0.5 flex items-center gap-2 text-[10.5px] text-muted-foreground">
                        <span className={pnlClass(row.amount)}>{fmtMoney(row.amount, true)}</span>
                        <span>·</span>
                        <span>
                          {t("tax.attrCurrent")} {row.current_category}
                        </span>
                      </div>
                    </div>
                  </div>
                  <Badge variant={badgeVariant(row.candidate.source)}>
                    {sourceLabel(row.candidate.source, t)}
                  </Badge>
                </div>

                <div className="mt-2 rounded-md bg-muted/40 p-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-[10.5px] text-muted-foreground">{t("tax.attrSuggestion")}</span>
                    <span className="text-[12px] font-medium">
                      {row.candidate.category || t("tax.attrFallback")}
                    </span>
                   </div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10.5px] text-muted-foreground">
                    <span>{row.candidate.reason}</span>
                        <span>
                      · {t("tax.attrConfidence", {
                        p: String(Math.round(row.candidate.confidence * 100)),
                      })}
                    </span>
                  </div>
                  {row.alternatives.length ? (
                    <div className="mt-1.5 flex flex-wrap items-center gap-1">
                      <span className="text-[10px] text-muted-foreground">{t("tax.attrAlternatives")}</span>
                      {row.alternatives.map((alt) => (
                        <button
                          key={`${row.transaction_id}-${alt.category}-${alt.source}`}
                          type="button"
                          onClick={() =>
                            selectPick(row, alt.category, {
                              source: alt.source,
                              confidence: alt.confidence,
                              rule_id: "",
                              matched: [alt.source],
                            })
                          }
                          className="rounded-full border border-border px-2 py-0.5 text-[10.5px] hover:border-primary/50 hover:text-primary"
                        >
                          {alt.category}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <select
                    value={pick?.category ?? ""}
                    onChange={(e) => {
                      const cat = e.target.value;
                      if (!cat) return;
                      selectPick(row, cat, {
                        source: "manual",
                        confidence: 1,
                        rule_id: "",
                        matched: ["manual"],
                      });
                    }}
                    className="min-w-[9rem] rounded-md border border-border bg-background px-2 py-1 text-[11.5px]"
                  >
                    <option value="">{t("tax.attrFallbackHint")}</option>
                    {categoryOptions.map((cat) => (
                      <option key={cat} value={cat}>
                        {cat}
                      </option>
                    ))}
                  </select>
                  <Button
                    size="sm"
                    disabled={!pick || busy}
                    onClick={() => {
                      if (!pick) return;
                      confirm.mutate({
                        transaction_id: row.transaction_id,
                        category: pick.category,
                        source: pick.source,
                        rule_id: pick.rule_id,
                        confidence: pick.confidence,
                        matched: pick.matched,
                      });
                    }}
                  >
                    {busy ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
                    {t("tax.attrConfirm")}
                  </Button>
                </div>
              </div>
            );
          })}
        </Card>
      )}


      <Card className="p-0">
        <div className="flex flex-wrap items-center justify-between gap-2 p-[var(--card-pad)]">
          <div className="flex items-center gap-1.5 text-[12px] font-medium">
            <Undo2 className="h-3.5 w-3.5 text-muted-foreground" />
            {t("tax.attrConfirmedTitle")}
          </div>
          {confirmedList.data ? (
            <Badge variant="muted">
              {t("tax.attrResolved", { n: String(confirmedList.data.count) })}
            </Badge>
          ) : null}
        </div>
        {confirmedList.isLoading ? (
          <div className="px-[var(--card-pad)] pb-[var(--card-pad)]">
            <Skeleton className="h-16 w-full" />
          </div>
        ) : confirmedList.error ? (
          <div className="px-[var(--card-pad)] pb-[var(--card-pad)] text-[11px] text-down">
            {confirmedList.error instanceof Error
              ? confirmedList.error.message
              : String(confirmedList.error)}
          </div>
        ) : !confirmedList.data?.items.length ? (
          <div className="px-[var(--card-pad)] pb-[var(--card-pad)]">
            <EmptyState mode="compact" text={t("tax.attrNoConfirmed")} />
          </div>
        ) : (
          <div className="divide-y divide-border/70 border-t border-border/70">
            {confirmedList.data.items.map((row) => {
              const busy =
                rollback.isPending && rollback.variables === row.transaction_id;
              return (
                <div
                  key={row.transaction_id}
                  className="flex flex-wrap items-start justify-between gap-2 px-[var(--card-pad)] py-2"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="truncate text-[12px] font-medium">{row.item}</span>
                      <span className="text-[10px] text-muted-foreground">{row.date}</span>
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10.5px] text-muted-foreground">
                      <span className={pnlClass(row.amount)}>{fmtMoney(row.amount, true)}</span>
                      <span>{row.original_category || "—"}</span>
                      <span>→</span>
                      <Badge variant="ok">{row.confirmed_category}</Badge>
                      <span>· {sourceLabel(row.source, t)}</span>
                      <span>· {t("tax.attrConfirmedAt", { t: row.confirmed_at.slice(0, 16) })}</span>
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy}
                    onClick={() => {
                      if (!window.confirm(t("tax.attrRollbackConfirm"))) return;
                      rollback.mutate(row.transaction_id);
                    }}
                  >
                    {busy ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Undo2 className="h-3.5 w-3.5" />
                    )}
                    <span className="ml-1">{t("tax.attrRollback")}</span>
                  </Button>
                </div>
              );
            })}
          </div>
        )}
        {rollback.isSuccess ? (
          <p className="px-[var(--card-pad)] pb-[var(--card-pad)] text-[10.5px] text-emerald-600 dark:text-emerald-400">
            {t("tax.attrRollbackDone")}
          </p>
        ) : null}
        {rollback.error ? (
          <p className="px-[var(--card-pad)] pb-[var(--card-pad)] text-[10.5px] text-down">
            {rollback.error instanceof Error ? rollback.error.message : String(rollback.error)}
          </p>
        ) : null}
      </Card>

      <p className="px-1 text-[10.5px] leading-relaxed text-muted-foreground">{t("tax.attrBoundary")}</p>
    </div>
  );
}

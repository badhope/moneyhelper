/** 多主体管理合并面板（4.18.0）：集团范围、主体折算、抵销与集团三表。 */
import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Building2,
  Download,
  Layers,
  Plus,
  RefreshCw,
  Trash2,
  TrendingUp,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ConfirmDialog } from "@/components/ui/confirm";
import { Segmented } from "@/components/ui/segmented";
import { StatTile } from "@/components/ui/stat";
import { Table } from "@/components/ui/table";
import { useI18n } from "@/lib/i18n";
import { errMsg, cn } from "@/lib/utils";
import { fmtMoney } from "@/lib/format";
import {
  useAddConsolidationEntity,
  useConsolidationAdjustments,
  useConsolidationDetail,
  useConsolidationGroups,
  useConsolidationReport,
  useCreateConsolidationAdjustment,
  useCreateConsolidationEntity,
  useCreateConsolidationGroup,
  useDeleteConsolidationAdjustment,
  useDeleteConsolidationGroup,
  useRemoveConsolidationEntity,
  type AdjustmentVoucher,
  type ConsolidationEntity,
  type StatementSummary,
} from "@/lib/use-consolidation";

const inputCls =
  "h-9 w-full rounded-md border border-border/70 bg-background px-2.5 text-xs outline-none transition-colors focus:border-primary";

function StatusBadge({ status }: { status?: ConsolidationEntity["status"] }) {
  const { t } = useI18n();
  if (status === "ok") return <Badge variant="ok">{t("cons.statusOk")}</Badge>;
  if (status === "missing") return <Badge variant="warn">{t("cons.statusMissing")}</Badge>;
  if (status === "no_posted") return <Badge variant="warn">{t("cons.statusNoPosted")}</Badge>;
  if (status === "no_access") return <Badge variant="danger">{t("cons.statusNoAccess")}</Badge>;
  return <Badge variant="muted">—</Badge>;
}

function methodLabel(method: string, t: (k: string) => string) {
  return method === "full" ? t("cons.methodFull") : t("cons.methodProp");
}

function SummaryCol({ label, value }: { label: string; value: StatementSummary }) {
  const { t } = useI18n();
  return (
    <div className="grid gap-1.5">
      <div className="text-[11px] font-medium text-muted-foreground">{label}</div>
      {[
        [t("cons.totalAssets"), value.total_assets],
        [t("cons.totalLiab"), value.total_liabilities],
        [t("cons.totalEquity"), value.total_equity],
        [t("cons.revenue"), value.revenue],
        [t("cons.netProfit"), value.net_profit],
      ].map(([name, amount]) => (
        <div key={String(name)} className="flex items-baseline justify-between gap-2 rounded-md bg-muted/25 px-2 py-1">
          <span className="text-[11px] text-muted-foreground">{name}</span>
          <span className="whitespace-nowrap font-semibold tabular-nums text-[12px]">
            {fmtMoney(Number(amount))}
          </span>
        </div>
      ))}
    </div>
  );
}

function EntityCard({ entity, onRemove }: { entity: ConsolidationEntity; onRemove: () => void }) {
  const { t } = useI18n();
  const entityStatement = entity.statement ?? entity.included;
  return (
    <div className="rounded-xl border border-border/60 bg-card p-3 shadow-xs">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-sm font-semibold">
            <Building2 className="h-3.5 w-3.5 shrink-0 text-primary" />
            <span className="truncate">{entity.tenant_name}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
            <Badge variant="outline">#{entity.tenant_id}</Badge>
            <span className="tabular-nums">{t("cons.stake")} {entity.ownership_pct}%</span>
            <span>·</span>
            <span>{methodLabel(entity.method, t)}</span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <StatusBadge status={entity.status} />
          <Button variant="ghost" size="sm" className="h-7 px-1.5" onClick={onRemove} title={t("cons.remove")}>
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
      {entityStatement ? (
        <div className="mt-2 grid grid-cols-3 gap-1.5">
          {[
            [t("cons.assets"), entityStatement.total_assets],
            [t("cons.revenue"), entityStatement.revenue],
            [t("cons.netProfit"), entityStatement.net_profit],
          ].map(([name, amount]) => (
            <div key={String(name)} className="rounded-md bg-muted/25 px-2 py-1">
              <div className="text-[10px] text-muted-foreground">{name}</div>
              <div className="truncate text-[12px] font-semibold tabular-nums">
                {fmtMoney(Number(amount))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="mt-2 rounded-md bg-amber-500/10 px-2 py-1.5 text-[11px] text-amber-700 dark:text-amber-400">
          {entity.warning || t("cons.noStatement")}
        </div>
      )}
      {entity.warning && entityStatement ? (
        <div className="mt-1.5 text-[11px] text-amber-700 dark:text-amber-400">{entity.warning}</div>
      ) : null}
    </div>
  );
}

function AdjustmentCard({ voucher, onDelete }: { voucher: AdjustmentVoucher; onDelete: () => void }) {
  const { t } = useI18n();
  return (
    <div className="rounded-xl border border-border/60 bg-card p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm font-semibold">{voucher.description}</div>
          <div className="mt-0.5 text-[11px] text-muted-foreground">
            {voucher.voucher_id} · {voucher.period} · {t("cons.eliminations")} {fmtMoney(voucher.debit_cents / 100)}
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={onDelete} className="h-7 px-1.5" title={t("cons.delete")}>
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
      <div className="mt-2 grid gap-1">
        {voucher.lines.map((line, idx) => {
          const debit = Number(line.debit_cents) > 0;
          return (
            <div key={line.id ?? idx} className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-muted/20 px-2 py-1 text-[11px]">
              <span className="min-w-0">
                {line.account_code} {line.account_name}
              </span>
              <span className={cn("tabular-nums font-medium", debit ? "text-up" : "text-down")}>
                {debit ? `${t("cons.debit")} ${fmtMoney(line.debit_cents / 100)}` : `${t("cons.credit")} ${fmtMoney(line.credit_cents / 100)}`}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function ConsolidationPanel() {
  const { t } = useI18n();
  const groups = useConsolidationGroups();
  const [selected, setSelected] = useState<string | null>(null);
  const [period, setPeriod] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [groupName, setGroupName] = useState("");
  const [confirmDeleteGroup, setConfirmDeleteGroup] = useState(false);
  const [showEntityForm, setShowEntityForm] = useState(false);
  const [entityMode, setEntityMode] = useState<"new" | "existing">("new");
  const [entityName, setEntityName] = useState("");
  const [entityTenant, setEntityTenant] = useState<string>("");
  const [ownership, setOwnership] = useState("100");
  const [method, setMethod] = useState<"full" | "proportional">("full");
  const [showAdjForm, setShowAdjForm] = useState(false);
  const [adjDesc, setAdjDesc] = useState("");
  const [adjAmount, setAdjAmount] = useState("");
  const [debitCode, setDebitCode] = useState("");
  const [creditCode, setCreditCode] = useState("");
  const [pendingVoucher, setPendingVoucher] = useState<AdjustmentVoucher | null>(null);

  const detail = useConsolidationDetail(selected);
  const report = useConsolidationReport(selected, period);
  const adjustments = useConsolidationAdjustments(selected, period);
  const createGroup = useCreateConsolidationGroup();
  const deleteGroup = useDeleteConsolidationGroup();
  const addEntity = useAddConsolidationEntity();
  const createEntity = useCreateConsolidationEntity();
  const removeEntity = useRemoveConsolidationEntity();
  const createAdjustment = useCreateConsolidationAdjustment();
  const deleteAdjustment = useDeleteConsolidationAdjustment();

  const groupList = groups.data?.groups ?? [];
  const currentGroup = groupList.find((g) => g.id === selected) ?? detail.data?.group;
  const periods = detail.data?.periods ?? report.data?.periods ?? [];
  const entities = report.data?.entities ?? detail.data?.entities ?? [];
  const accounts = report.data?.accounts ?? detail.data?.accounts ?? [];
  const candidates = detail.data?.candidates ?? [];
  const alertList = report.data?.analysis?.alerts ?? [];

  useEffect(() => {
    if (!selected && groupList.length) setSelected(groupList[0].id);
  }, [groupList, selected]);

  useEffect(() => {
    setPeriod(null);
  }, [selected]);

  useEffect(() => {
    if (!periods.length) {
      if (period) setPeriod(null);
      return;
    }
    if (!period || !periods.some((p) => p.period === period)) setPeriod(periods[0].period);
  }, [periods, period]);

  useEffect(() => {
    if (!accounts.length) return;
    const income = accounts.find((a) => a.type === "income") ?? accounts[0];
    const expense = accounts.find((a) => a.type === "expense") ?? accounts[1] ?? accounts[0];
    if (!debitCode) setDebitCode(income.code);
    if (!creditCode) setCreditCode(expense.code);
  }, [accounts, debitCode, creditCode]);

  useEffect(() => {
    if (entityMode === "existing" && !entityTenant && candidates.length) {
      setEntityTenant(String(candidates[0].id));
    }
  }, [entityMode, entityTenant, candidates]);

  const pctValue = useMemo(() => {
    const n = Number(ownership);
    return Number.isFinite(n) ? n : 100;
  }, [ownership]);

  const doCreateGroup = () => {
    const name = groupName.trim();
    if (!name) return;
    createGroup.mutate(name, {
      onSuccess: (data) => {
        setShowCreate(false);
        setGroupName("");
        setSelected(data.group.id);
      },
    });
  };

  const doDeleteGroup = async () => {
    if (!selected) return;
    await deleteGroup.mutateAsync(selected);
    setSelected(null);
    setPeriod(null);
  };

  const doAddEntity = () => {
    if (!selected) return;
    const pct = method === "full" ? 100 : Math.min(100, Math.max(0.01, pctValue));
    if (entityMode === "new") {
      if (!entityName.trim()) return;
      createEntity.mutate(
        { groupId: selected, name: entityName.trim(), ownershipPct: pct, method },
        { onSuccess: () => { setShowEntityForm(false); setEntityName(""); } },
      );
    } else {
      if (!entityTenant) return;
      addEntity.mutate(
        { groupId: selected, tenantId: Number(entityTenant), ownershipPct: pct, method },
        { onSuccess: () => { setShowEntityForm(false); setEntityTenant(""); } },
      );
    }
  };

  const doAddAdjustment = () => {
    if (!selected || !period) return;
    const amount = Number(adjAmount);
    if (!adjDesc.trim() || !debitCode || !creditCode || !Number.isFinite(amount) || amount <= 0) return;
    createAdjustment.mutate(
      {
        groupId: selected, period, description: adjDesc.trim(),
        debitCode, creditCode, amount,
      },
      { onSuccess: () => { setShowAdjForm(false); setAdjDesc(""); setAdjAmount(""); } },
    );
  };

  const exportCsv = () => {
    const data = report.data;
    if (!data) return;
    const rows = [
      [t("cons.itemCode"), t("cons.itemName"), "type", t("cons.debit"), t("cons.credit"), t("cons.balance")],
      ...data.items.map((x) => [
        x.code, x.name, x.type, (x.debit_cents / 100).toFixed(2),
        (x.credit_cents / 100).toFixed(2), Number(x.balance).toFixed(2),
      ]),
    ];
    const csv = rows
      .map((r) => r.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(","))
      .join("\n");
    const url = URL.createObjectURL(new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${data.group.name}-${data.period}-合并底稿.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const busyEntity = addEntity.isPending || createEntity.isPending;

  return (
    <Card className="overflow-hidden">
      <div className="border-b border-border/60 bg-gradient-to-br from-primary/[0.07] via-card to-card p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Layers className="h-4 w-4 text-primary" />
              <span className="text-sm font-semibold">{t("cons.title")}</span>
              <Badge variant="default">{t("cons.badge")}</Badge>
            </div>
            <p className="mt-1 max-w-2xl text-[11.5px] leading-relaxed text-muted-foreground">{t("cons.hint")}</p>
          </div>
          <Button size="sm" variant={showCreate ? "outline" : "default"} onClick={() => setShowCreate((v) => !v)}>
            <Plus className="h-3.5 w-3.5" />
            {t("cons.newGroup")}
          </Button>
        </div>

        {showCreate || !groupList.length ? (
          <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-dashed border-border/70 bg-background/70 p-2">
            <input
              value={groupName}
              onChange={(e) => setGroupName(e.target.value)}
              placeholder={t("cons.groupNamePlaceholder")}
              maxLength={60}
              className={cn(inputCls, "max-w-xs flex-1")}
            />
            <Button size="sm" onClick={doCreateGroup} disabled={!groupName.trim() || createGroup.isPending}>
              {createGroup.isPending ? "…" : t("cons.create")}
            </Button>
            {groupList.length ? (
              <Button size="sm" variant="ghost" onClick={() => setShowCreate(false)}>{t("cons.cancel")}</Button>
            ) : null}
            {createGroup.isError ? (
              <span className="text-[11px] text-red-600 dark:text-red-400">{errMsg(createGroup.error)}</span>
            ) : null}
          </div>
        ) : null}

        {groupList.length ? (
          <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_1fr_auto_auto] sm:items-end">
            <label className="grid gap-1 text-[11px] text-muted-foreground">
              {t("cons.group")}
              <select
                value={selected ?? ""}
                onChange={(e) => setSelected(e.target.value || null)}
                className={inputCls}
              >
                {groupList.map((g) => (
                  <option key={g.id} value={g.id}>{g.name} · {g.entity_count} 个主体</option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-[11px] text-muted-foreground">
              {t("cons.period")}
              <select
                value={period ?? ""}
                onChange={(e) => setPeriod(e.target.value || null)}
                className={inputCls}
                disabled={!periods.length}
              >
                {periods.length ? (
                  periods.map((p) => (
                    <option key={p.period} value={p.period}>{p.period} · {p.entities} 个主体有账</option>
                  ))
                ) : (
                  <option value="">{t("cons.periodEmpty")}</option>
                )}
              </select>
            </label>
            <Button
              size="sm"
              variant="outline"
              onClick={() => report.refetch()}
              disabled={!period || report.isFetching}
            >
              <RefreshCw className={cn("h-3.5 w-3.5", report.isFetching && "animate-spin")} />
              {t("cons.run")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirmDeleteGroup(true)} title={t("cons.deleteGroup")}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        ) : null}

        {deleteGroup.isError ? (
          <div className="mt-2 text-[11px] text-red-600 dark:text-red-400">{errMsg(deleteGroup.error)}</div>
        ) : null}
      </div>

      {!groupList.length ? (
        <EmptyState
          illustration="data"
          title={t("cons.emptyTitle")}
          desc={t("cons.emptyDesc")}
          actions={
            <Button size="sm" onClick={() => setShowCreate(true)}>
              <Plus className="h-3.5 w-3.5" />
              {t("cons.newGroup")}
            </Button>
          }
        />
      ) : !selected ? null : (
        <div className="grid gap-4 p-4">
          {detail.isError ? (
            <div className="rounded-lg bg-amber-500/10 px-3 py-2 text-[11.5px] text-amber-700 dark:text-amber-400">
              {errMsg(detail.error)}
            </div>
          ) : null}

          <section>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <div className="text-[12px] font-semibold">
                {t("cons.entities")} <span className="text-muted-foreground">({entities.length})</span>
              </div>
              <Button size="sm" variant="outline" onClick={() => setShowEntityForm((v) => !v)}>
                <Plus className="h-3.5 w-3.5" />
                {t("cons.addEntity")}
              </Button>
            </div>

            {showEntityForm ? (
              <div className="mb-2 grid gap-2 rounded-lg border border-border/60 bg-muted/20 p-2.5">
                <Segmented
                  value={entityMode}
                  onChange={(v) => setEntityMode(v)}
                  size="sm"
                  options={[
                    { value: "new", label: t("cons.newEntity") },
                    { value: "existing", label: t("cons.existingEntity") },
                  ]}
                />
                <div className="grid gap-2 sm:grid-cols-3">
                  {entityMode === "new" ? (
                    <input
                      value={entityName}
                      onChange={(e) => setEntityName(e.target.value)}
                      placeholder={t("cons.entityNamePlaceholder")}
                      maxLength={60}
                      className={inputCls}
                    />
                  ) : (
                    <select
                      value={entityTenant}
                      onChange={(e) => setEntityTenant(e.target.value)}
                      className={inputCls}
                      disabled={!candidates.length}
                    >
                      {candidates.length ? (
                        candidates.map((c) => (
                          <option key={c.id} value={c.id}>{c.name} · #{c.id} · {c.role}</option>
                        ))
                      ) : (
                        <option value="">{t("cons.noCandidate")}</option>
                      )}
                    </select>
                  )}
                  <div className="grid grid-cols-2 gap-1.5">
                    <input
                      type="number"
                      min={0.01}
                      max={100}
                      step={0.01}
                      value={method === "full" ? "100" : ownership}
                      onChange={(e) => setOwnership(e.target.value)}
                      disabled={method === "full"}
                      className={inputCls}
                      aria-label={t("cons.ownership")}
                    />
                    <select
                      value={method}
                      onChange={(e) => {
                        const next = e.target.value as "full" | "proportional";
                        setMethod(next);
                        if (next === "full") setOwnership("100");
                        else if (ownership === "100") setOwnership("80");
                      }}
                      className={inputCls}
                      aria-label={t("cons.method")}
                    >
                      <option value="full">{t("cons.methodFull")}</option>
                      <option value="proportional">{t("cons.methodProp")}</option>
                    </select>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Button size="sm" onClick={doAddEntity} disabled={busyEntity}>
                      {busyEntity ? "…" : t("cons.add")}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setShowEntityForm(false)}>{t("cons.cancel")}</Button>
                  </div>
                </div>
                {addEntity.isError || createEntity.isError ? (
                  <div className="text-[11px] text-red-600 dark:text-red-400">
                    {errMsg((addEntity.error || createEntity.error) as Error)}
                  </div>
                ) : null}
              </div>
            ) : null}

            {entities.length ? (
              <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                {entities.map((entity) => (
                  <EntityCard
                    key={entity.tenant_id}
                    entity={entity}
                    onRemove={() => selected && removeEntity.mutate({ groupId: selected, tenantId: entity.tenant_id })}
                  />
                ))}
              </div>
            ) : (
              <EmptyState
                mode="compact"
                illustration="data"
                text={t("cons.noStatement")}
              />
            )}
          </section>

          {report.isError ? (
            <div className="flex flex-wrap items-center gap-2 rounded-lg bg-amber-500/10 px-3 py-2 text-[11.5px] text-amber-700 dark:text-amber-400">
              <AlertTriangle className="h-3.5 w-3.5" />
              <span className="min-w-0 flex-1">{errMsg(report.error)}</span>
              <Button size="sm" variant="outline" onClick={() => report.refetch()}>{t("cons.run")}</Button>
            </div>
          ) : report.data ? (
            <>
              <section className="grid gap-2 sm:grid-cols-3 xl:grid-cols-5">
                <SummaryCol label={t("cons.reported")} value={report.data.summary.reported} />
                <SummaryCol label={t("cons.included")} value={report.data.summary.included} />
                <SummaryCol label={t("cons.consolidated")} value={report.data.summary.consolidated} />
                <div className="grid content-start gap-1.5">
                  <div className="text-[11px] font-medium text-muted-foreground">{t("cons.adjustments")}</div>
                  <StatTile label={t("cons.eliminations")} value={fmtMoney(report.data.summary.eliminations.debit_cents / 100, false, true)} hint={`${report.data.summary.eliminations.vouchers} 张凭证`} size="sm" />
                  <StatTile
                    label={t("cons.balanced")}
                    value={report.data.balanced ? "✓" : "!"}
                    tone={report.data.balanced ? "positive" : "negative"}
                    hint={`${fmtMoney(report.data.totals.debit_cents / 100)} / ${fmtMoney(report.data.totals.credit_cents / 100)}`}
                    size="sm"
                  />
                </div>
                <div className="grid content-start gap-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-[11px] font-medium text-muted-foreground">{t("cons.alerts")}</div>
                    <Button size="sm" variant="ghost" onClick={exportCsv} className="h-7 px-1.5">
                      <Download className="h-3.5 w-3.5" />
                      {t("cons.exportCsv")}
                    </Button>
                  </div>
                  {alertList.length ? alertList.slice(0, 3).map((a) => (
                    <div key={a.code} className={cn("rounded-md px-2 py-1 text-[11px]", a.level === "bad" ? "bg-red-500/10 text-red-700 dark:text-red-400" : "bg-amber-500/10 text-amber-700 dark:text-amber-400")}>
                      {a.text}
                    </div>
                  )) : (
                    <div className="rounded-md bg-muted/25 px-2 py-1 text-[11px] text-muted-foreground">{t("cons.noAlerts")}</div>
                  )}
                </div>
              </section>

              <section>
                <div className="mb-1.5 flex items-center justify-between gap-2">
                  <div className="text-[12px] font-semibold">{t("cons.items")}</div>
                  <div className="text-[10.5px] text-muted-foreground">{report.data.scope_note}</div>
                </div>
                <div className="overflow-x-auto rounded-lg border border-border/60">
                  <Table size="2xs" minWidth={520}>
                    <thead className="bg-muted/30 text-muted-foreground">
                      <tr>
                        <th className="px-2 py-1.5 text-left font-medium">{t("cons.itemCode")}</th>
                        <th className="px-2 py-1.5 text-left font-medium">{t("cons.itemName")}</th>
                        <th className="px-2 py-1.5 text-right font-medium">{t("cons.debit")}</th>
                        <th className="px-2 py-1.5 text-right font-medium">{t("cons.credit")}</th>
                        <th className="px-2 py-1.5 text-right font-medium">{t("cons.balance")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.data.items.map((item) => (
                        <tr key={item.code} className="border-t border-border/40">
                          <td className="px-2 py-1.5 tabular-nums">{item.code}</td>
                          <td className="px-2 py-1.5">{item.name}</td>
                          <td className="px-2 py-1.5 text-right tabular-nums">{fmtMoney(item.debit_cents / 100)}</td>
                          <td className="px-2 py-1.5 text-right tabular-nums">{fmtMoney(item.credit_cents / 100)}</td>
                          <td className={cn("px-2 py-1.5 text-right font-medium tabular-nums", item.balance >= 0 ? "text-foreground" : "text-down")}>
                            {fmtMoney(item.balance)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </div>
              </section>

             {report.data.warnings.length ? (
                <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                  {report.data.warnings.map((w, i) => (
                    <div key={i} className="rounded-lg bg-amber-500/10 px-2.5 py-2 text-[11.5px] text-amber-700 dark:text-amber-400">
                      {w}
                    </div>
                  ))}
                </div>
              ) : null}
            </>
          ) : null}

          <section>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <div className="text-[12px] font-semibold">
                {t("cons.adjustments")} <span className="text-muted-foreground">({adjustments.data?.count ?? 0})</span>
              </div>
              <Button size="sm" variant="outline" onClick={() => setShowAdjForm((v) => !v)}>
                <Plus className="h-3.5 w-3.5" />
                {t("cons.addAdjustment")}
              </Button>
            </div>

            {showAdjForm ? (
              <div className="mb-2 grid gap-2 rounded-lg border border-border/60 bg-muted/20 p-2.5">
                <div className="grid gap-2 sm:grid-cols-2">
                  <input
                    value={adjDesc}
                    onChange={(e) => setAdjDesc(e.target.value)}
                    placeholder={t("cons.adjustmentDescPlaceholder")}
                    maxLength={120}
                    className={inputCls}
                  />
                  <input
                    type="number"
                    min={0.01}
                    step={0.01}
                    value={adjAmount}
                    onChange={(e) => setAdjAmount(e.target.value)}
                    placeholder={t("cons.amount")}
                    className={inputCls}
                  />
                </div>
                <div className="grid gap-2 sm:grid-cols-3">
                  <select value={debitCode} onChange={(e) => setDebitCode(e.target.value)} className={inputCls} aria-label={t("cons.debitAccount")}>
                    {accounts.map((a) => <option key={a.code} value={a.code}>{a.code} {a.name}</option>)}
                  </select>
                  <select value={creditCode} onChange={(e) => setCreditCode(e.target.value)} className={inputCls} aria-label={t("cons.creditAccount")}>
                    {accounts.map((a) => <option key={a.code} value={a.code}>{a.code} {a.name}</option>)}
                  </select>
                  <div className="flex items-center gap-1.5">
                    <Button size="sm" onClick={doAddAdjustment} disabled={createAdjustment.isPending}>
                      {createAdjustment.isPending ? "…" : t("cons.save")}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setShowAdjForm(false)}>{t("cons.cancel")}</Button>
                  </div>
                </div>
                <div className="text-[10.5px] text-muted-foreground">
                  {t("cons.debitAccount")} / {t("cons.creditAccount")} · 借贷自动平衡，不回写主体账本
                </div>
                {createAdjustment.isError ? (
                  <div className="text-[11px] text-red-600 dark:text-red-400">{errMsg(createAdjustment.error)}</div>
                ) : null}
              </div>
            ) : null}

            {adjustments.data?.adjustments?.length ? (
              <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                {adjustments.data.adjustments.map((v) => (
                  <AdjustmentCard key={v.voucher_id} voucher={v} onDelete={() => setPendingVoucher(v)} />
                ))}
              </div>
            ) : (
              <div className="rounded-lg bg-muted/25 px-3 py-2 text-[11.5px] text-muted-foreground">
                {t("cons.noAdjustments")}
              </div>
            )}
          </section>

          <div className="flex items-start gap-2 rounded-lg border border-border/60 bg-muted/15 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
            <TrendingUp className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
            <span>{report.data?.boundary ?? detail.data?.boundary ?? t("cons.boundary")}</span>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={confirmDeleteGroup}
        onOpenChange={setConfirmDeleteGroup}
        title={t("cons.deleteGroupTitle", { name: currentGroup?.name ?? "" })}
        description={t("cons.deleteGroupDesc")}
        confirmText={t("cons.deleteGroup")}
        danger
        onConfirm={doDeleteGroup}
      />

      <ConfirmDialog
        open={Boolean(pendingVoucher)}
        onOpenChange={(open) => { if (!open) setPendingVoucher(null); }}
        title={`${t("cons.delete")} ${pendingVoucher?.description ?? ""}?`}
        description={pendingVoucher ? `${pendingVoucher.voucher_id} · ${pendingVoucher.period}` : ""}
        confirmText={t("cons.delete")}
        danger
        onConfirm={async () => {
          if (!selected || !pendingVoucher) return;
          await deleteAdjustment.mutateAsync({ groupId: selected, voucherId: pendingVoucher.voucher_id });
          setPendingVoucher(null);
        }}
      />
    </Card>
  );
}

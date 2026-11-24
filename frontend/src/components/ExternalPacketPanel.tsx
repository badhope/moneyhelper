/** 外部协同前置包（4.20.0）：税务核对、付款草稿、合并审计。只导出，不代执行。 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Building2,
  Download,
  FileCheck2,
  Landmark,
  ShieldAlert,
  ShieldCheck,
  Wallet,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { StatTile } from "@/components/ui/stat";
import { Table } from "@/components/ui/table";
import { useI18n } from "@/lib/i18n";
import { fmtMoney } from "@/lib/format";
import { useConsolidationGroups } from "@/lib/use-consolidation";
import {
  useConsolidationPacket,
  usePaymentPacket,
  useTaxPacket,
  type ConsolidationPacket,
  type ExternalCheck,
  type PaymentPacket,
  type TaxPacket,
} from "@/lib/use-external-packets";
import { usePlanPeriods } from "@/lib/use-enterprise-plan";

function downloadBlob(content: string, filename: string, mime: string) {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function downloadJson(packet: unknown, filename: string) {
  downloadBlob(JSON.stringify(packet, null, 2), filename, "application/json;charset=utf-8");
}

function csvCell(value: unknown): string {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function downloadPaymentCsv(packet: PaymentPacket) {
  const header = ["seq", "expected_date", "account_code", "counterparty", "amount", "certainty", "note"];
  const lines = packet.instructions.map((row) =>
    [row.seq, row.expected_date, row.account_code, row.counterparty, row.amount, row.certainty, row.note]
      .map(csvCell)
      .join(","),
  );
  downloadBlob(`\ufeff${[header.join(","), ...lines].join("\n")}`, `${packet.packet_id}.csv`, "text/csv;charset=utf-8");
}

function statusTone(status: string): "ok" | "warn" | "danger" | "muted" {
  if (status === "ready" || status === "ok") return "ok";
  if (status === "error" || status === "blocked") return "danger";
  if (status === "review" || status === "manual") return "warn";
  return "muted";
}

function StatusBadge({ status, t }: { status: string; t: (key: string) => string }) {
  return <Badge variant={statusTone(status)}>{t(`external.status.${status}`)}</Badge>;
}

function BoundaryNote() {
  const { t } = useI18n();
  return (
    <div className="flex items-start gap-2 rounded-xl border border-amber-500/20 bg-amber-500/5 px-3 py-2.5 text-[11px] leading-relaxed text-amber-800 dark:text-amber-300">
      <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
      <div>
        <div className="font-medium">{t("external.boundaryTitle")}</div>
        <div className="mt-0.5 text-amber-700/80 dark:text-amber-300/80">{t("external.boundaryText")}</div>
      </div>
    </div>
  );
}

function CheckGrid({ checks }: { checks: ExternalCheck[] }) {
  const { t } = useI18n();
  return (
    <div className="grid gap-1.5 sm:grid-cols-2">
      {checks.map((check) => (
        <div key={check.id} className="flex items-start gap-2 rounded-lg bg-muted/25 px-2.5 py-2 text-[11px]">
          <span
            className={
              "mt-1 h-1.5 w-1.5 shrink-0 rounded-full " +
              (check.status === "ok"
                ? "bg-emerald-500"
                : check.status === "error" || check.status === "blocked"
                  ? "bg-red-500"
                  : "bg-amber-500")
            }
          />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-[10px] text-muted-foreground">{check.id}</span>
              <StatusBadge status={check.status} t={t} />
            </div>
            <div className="mt-0.5 text-muted-foreground">{check.detail}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

function SectionHead({
  icon,
  title,
  hint,
  status,
  action,
}: {
  icon: ReactNode;
  title: string;
  hint: string;
  status?: string;
  action?: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div className="flex min-w-0 items-start gap-2">
        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          {icon}
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold">
            {title}
            {status ? <StatusBadge status={status} t={t} /> : null}
          </div>
          <div className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">{hint}</div>
        </div>
      </div>
      {action}
    </div>
  );
}

function TaxCard({ packet, loading, error }: { packet?: TaxPacket; loading: boolean; error: unknown }) {
  const { t } = useI18n();
  return (
    <Card className="p-[var(--card-pad)]">
      <SectionHead
        icon={<FileCheck2 className="h-4 w-4" />}
        title={t("external.taxTitle")}
        hint={t("external.taxHint")}
        status={packet?.status}
        action={
          <Button
            size="sm"
            variant="outline"
            onClick={() => packet && downloadJson(packet, `${packet.packet_id}.json`)}
            disabled={!packet}
          >
            <Download className="h-3.5 w-3.5" />
            {t("external.downloadJson")}
          </Button>
        }
      />
      {loading ? (
        <div className="mt-3 h-24 animate-pulse rounded-lg bg-muted/30" />
      ) : error || !packet ? (
        <div className="mt-3 text-xs text-down">{t("external.loadFailed")}</div>
      ) : (
        <div className="mt-3 space-y-3">
          <Badge variant="warn">{t("external.taxNotSubmitted")}</Badge>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <StatTile label={t("external.taxIncome")} value={fmtMoney(packet.summary.income)} />
            <StatTile label={t("external.taxExpense")} value={fmtMoney(packet.summary.expense)} />
            <StatTile label={t("external.taxNet")} value={fmtMoney(packet.summary.tax_net)} />
            <StatTile
              label={t("external.taxEntries")}
              value={`${packet.posted_entries} / ${packet.draft_entries}`}
              hint={`${packet.packet_id} · ${packet.submission_status}`}
            />
          </div>
          <div>
            <div className="mb-1.5 text-[11px] font-medium text-muted-foreground">{t("external.taxChecks")}</div>
            <CheckGrid checks={packet.checks} />
          </div>
          {packet.account_summary.length ? (
            <div>
              <div className="mb-1.5 text-[11px] font-medium text-muted-foreground">{t("external.taxAccounts")}</div>
              <div className="overflow-x-auto rounded-lg border border-border/60">
                <Table size="2xs" minWidth={520}>
                  <thead className="bg-muted/30 text-muted-foreground">
                    <tr>
                      <th className="px-2 py-1.5 text-left">科目</th>
                      <th className="px-2 py-1.5 text-right">借方</th>
                      <th className="px-2 py-1.5 text-right">贷方</th>
                      <th className="px-2 py-1.5 text-right">余额</th>
                    </tr>
                  </thead>
                  <tbody>
                    {packet.account_summary.map((row) => (
                      <tr key={row.account_code} className="border-t border-border/50">
                        <td className="px-2 py-1.5">
                          <span className="font-mono">{row.account_code}</span>{" "}
                          <span className="text-muted-foreground">{row.account_name}</span>
                        </td>
                        <td className="px-2 py-1.5 text-right tabular-nums">{fmtMoney(row.debit)}</td>
                        <td className="px-2 py-1.5 text-right tabular-nums">{fmtMoney(row.credit)}</td>
                        <td className="px-2 py-1.5 text-right tabular-nums">{fmtMoney(row.balance)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </div>
            </div>
          ) : null}
          <div className="text-[10.5px] leading-relaxed text-muted-foreground">{packet.boundary}</div>
        </div>
      )}
    </Card>
  );
}

function PaymentCard({ packet, loading, error }: { packet?: PaymentPacket; loading: boolean; error: unknown }) {
  const { t } = useI18n();
  return (
    <Card className="p-[var(--card-pad)]">
      <SectionHead
        icon={<Wallet className="h-4 w-4" />}
        title={t("external.paymentTitle")}
        hint={t("external.paymentHint")}
        status={packet?.status}
        action={
          <Button
            size="sm"
            variant="outline"
            onClick={() => packet && downloadPaymentCsv(packet)}
            disabled={!packet || packet.count === 0}
          >
            <Download className="h-3.5 w-3.5" />
            {t("external.downloadCsv")}
          </Button>
        }
      />
      {loading ? (
        <div className="mt-3 h-24 animate-pulse rounded-lg bg-muted/30" />
      ) : error || !packet ? (
        <div className="mt-3 text-xs text-down">{t("external.loadFailed")}</div>
      ) : (
        <div className="mt-3 space-y-3">
          <Badge variant="warn">{t("external.paymentDraftBadge")}</Badge>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <StatTile label={t("external.paymentCount")} value={String(packet.count)} />
            <StatTile label={t("external.paymentTotal")} value={fmtMoney(packet.total)} />
            <StatTile label={t("external.paymentOpening")} value={fmtMoney(packet.opening)} />
            <StatTile label={t("external.paymentGuard")} value={fmtMoney(packet.target_min)} />
          </div>
          {packet.count === 0 ? (
            <EmptyState mode="compact" text={t("external.paymentEmpty")} />
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border/60">
              <Table size="2xs" minWidth={720}>
                <thead className="bg-muted/30 text-muted-foreground">
                  <tr>
                    <th className="px-2 py-1.5 text-left">{t("external.paymentDate")}</th>
                    <th className="px-2 py-1.5 text-left">{t("external.paymentPayee")}</th>
                    <th className="px-2 py-1.5 text-left">账户</th>
                    <th className="px-2 py-1.5 text-right">{t("external.paymentAmount")}</th>
                    <th className="px-2 py-1.5 text-left">{t("external.paymentCertainty")}</th>
                    <th className="px-2 py-1.5 text-left">{t("external.paymentReview")}</th>
                  </tr>
                </thead>
                <tbody>
                  {packet.instructions.map((row) => (
                    <tr key={row.seq} className="border-t border-border/50">
                      <td className="px-2 py-1.5 tabular-nums">{row.expected_date}</td>
                      <td className="px-2 py-1.5">{row.counterparty || "—"}</td>
                      <td className="px-2 py-1.5 font-mono">{row.account_code}</td>
                      <td className="px-2 py-1.5 text-right tabular-nums">{fmtMoney(row.amount)}</td>
                      <td className="px-2 py-1.5">
                        <Badge variant={row.certainty === "high" ? "ok" : row.certainty === "low" ? "warn" : "muted"}>
                          {row.certainty}
                        </Badge>
                      </td>
                      <td className="px-2 py-1.5 text-muted-foreground">{row.review || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
          )}
          <CheckGrid checks={packet.checks} />
          <div className="rounded-lg border border-border/60 bg-muted/10 px-2.5 py-2 text-[10.5px] leading-relaxed text-muted-foreground">
            {t("external.paymentNever")}
          </div>
          <div className="text-[10.5px] leading-relaxed text-muted-foreground">{packet.boundary}</div>
        </div>
      )}
    </Card>
  );
}

function ConsolidationCard({
  packet,
  loading,
  error,
  groups,
  groupId,
  onGroup,
}: {
  packet?: ConsolidationPacket;
  loading: boolean;
  error: unknown;
  groups: { id: string; name: string }[];
  groupId: string;
  onGroup: (value: string) => void;
}) {
  const { t } = useI18n();
  return (
    <Card className="p-[var(--card-pad)]">
      <SectionHead
        icon={<Building2 className="h-4 w-4" />}
        title={t("external.consolidationTitle")}
        hint={t("external.consolidationHint")}
        status={packet?.status}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <select
              className="h-8 rounded-md border border-border/70 bg-background px-2 text-xs outline-none focus:border-primary"
              value={groupId}
              onChange={(event) => onGroup(event.target.value)}
            >
              {groups.map((group) => (
                <option key={group.id} value={group.id}>
                  {group.name}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              variant="outline"
              onClick={() => packet && downloadJson(packet, `${packet.packet_id}.json`)}
              disabled={!packet}
            >
              <Download className="h-3.5 w-3.5" />
              {t("external.downloadAudit")}
            </Button>
          </div>
        }
      />
      {groups.length === 0 ? (
        <div className="mt-3">
          <EmptyState mode="compact" text={t("external.groupEmpty")} />
        </div>
      ) : loading ? (
        <div className="mt-3 h-24 animate-pulse rounded-lg bg-muted/30" />
      ) : error || !packet ? (
        <div className="mt-3 text-xs text-down">{t("external.loadFailed")}</div>
      ) : (
        <div className="mt-3 space-y-3">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <StatTile
              label={t("external.consolidationRevenue")}
              value={fmtMoney(packet.summary.consolidated?.revenue ?? 0)}
            />
            <StatTile
              label={t("external.consolidationProfit")}
              value={fmtMoney(packet.summary.consolidated?.net_profit ?? 0)}
            />
            <StatTile
              label={t("external.consolidationAssets")}
              value={fmtMoney(packet.summary.consolidated?.total_assets ?? 0)}
            />
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
            <Badge variant="muted">
              <ShieldCheck className="h-3 w-3" />
              {t("external.auditNotLegal")}
            </Badge>
            <span className="font-mono">
              {t("external.consolidationHash")} {packet.source_hash}
            </span>
          </div>
          <div className="overflow-x-auto rounded-lg border border-border/60">
            <Table size="2xs" minWidth={520}>
              <thead className="bg-muted/30 text-muted-foreground">
                <tr>
                  <th className="px-2 py-1.5 text-left">{t("external.consolidationEntities")}</th>
                  <th className="px-2 py-1.5 text-left">method</th>
                  <th className="px-2 py-1.5 text-right">持股</th>
                  <th className="px-2 py-1.5 text-left">status</th>
                </tr>
              </thead>
              <tbody>
                {packet.entities.map((entity) => (
                  <tr key={entity.tenant_id} className="border-t border-border/50">
                    <td className="px-2 py-1.5">{entity.name || `#${entity.tenant_id}`}</td>
                    <td className="px-2 py-1.5 font-mono">{entity.method}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{entity.ownership_pct}%</td>
                    <td className="px-2 py-1.5">
                      <StatusBadge status={entity.status === "ok" ? "ok" : "review"} t={t} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
          <CheckGrid checks={packet.checks} />
          {(packet.warnings ?? []).map((warning) => (
            <div key={warning} className="rounded-lg bg-amber-500/10 px-2.5 py-2 text-[10.5px] text-amber-700 dark:text-amber-400">
              {warning}
            </div>
          ))}
          <div className="text-[10.5px] leading-relaxed text-muted-foreground">{packet.boundary}</div>
        </div>
      )}
    </Card>
  );
}

export function ExternalPacketPanel() {
  const { t } = useI18n();
  const periods = usePlanPeriods();
  const groupsQuery = useConsolidationGroups();
  const [period, setPeriod] = useState("");
  const [groupId, setGroupId] = useState("");

  const groupOptions = useMemo(
    () => (groupsQuery.data?.groups ?? []).map((group) => ({ id: String(group.id), name: String(group.name) })),
    [groupsQuery.data],
  );

  useEffect(() => {
    if (period) return;
    const latest = periods.data?.periods?.[0];
    if (latest) setPeriod(latest);
  }, [period, periods.data]);

  useEffect(() => {
    if (!groupId && groupOptions.length) setGroupId(groupOptions[0].id);
  }, [groupId, groupOptions]);

  const tax = useTaxPacket(period);
  const payment = usePaymentPacket(period);
  const consolidation = useConsolidationPacket(groupId || null, period);

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-base font-bold">
            <Landmark className="h-4 w-4 text-primary" />
            {t("external.title")}
          </div>
          <div className="mt-1 max-w-3xl text-[11px] leading-relaxed text-muted-foreground">{t("external.subtitle")}</div>
        </div>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          {t("external.period")}
          <select
            className="h-8 rounded-md border border-border/70 bg-background px-2 text-xs text-foreground outline-none focus:border-primary"
            value={period}
            onChange={(event) => setPeriod(event.target.value)}
          >
            {(periods.data?.periods ?? []).map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
      </div>
      <BoundaryNote />
      <TaxCard packet={tax.data} loading={tax.isLoading} error={tax.error} />
      <PaymentCard packet={payment.data} loading={payment.isLoading} error={payment.error} />
      <ConsolidationCard
        packet={consolidation.data}
        loading={consolidation.isLoading}
        error={consolidation.error}
        groups={groupOptions}
        groupId={groupId}
        onGroup={setGroupId}
      />
    </div>
  );
}

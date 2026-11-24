/** 外部协同前置包（4.21.0）：税务核对、付款草稿、合并审计，附交接留档台账。只导出，不代执行。 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Archive,
  Building2,
  CheckCircle2,
  ClipboardList,
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
  type HandoffLedger,
  type HandoffRecord,
  type PaymentPacket,
  type TaxPacket,
  useAckHandoff,
  useArchiveHandoff,
  useHandoffLedger,
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
  if (status === "ready" || status === "ok" || status === "handed_over") return "ok";
  if (status === "archived") return "warn";
  if (status === "error" || status === "blocked") return "danger";
  if (status === "review" || status === "manual") return "warn";
  return "muted";
}

function StatusBadge({ status, t }: { status: string; t: (key: string) => string }) {
  return <Badge variant={statusTone(status)}>{t(`external.status.${status}`)}</Badge>;
}

function ArchiveButton({
  record,
  pending,
  onArchive,
}: {
  record?: HandoffRecord;
  pending: boolean;
  onArchive: () => void;
}) {
  const { t } = useI18n();
  if (record) {
    return <StatusBadge status={record.state} t={t} />;
  }
  return (
    <Button size="sm" variant="secondary" onClick={onArchive} disabled={pending}>
      <Archive className="h-3.5 w-3.5" />
      {pending ? t("external.archiving") : t("external.archive")}
    </Button>
  );
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

function TaxCard({
  packet,
  loading,
  error,
  handoff,
  archivePending,
  onArchive,
}: {
  packet?: TaxPacket;
  loading: boolean;
  error: unknown;
  handoff?: HandoffRecord;
  archivePending: boolean;
  onArchive: () => void;
}) {
  const { t } = useI18n();
  return (
    <Card className="p-[var(--card-pad)]">
      <SectionHead
        icon={<FileCheck2 className="h-4 w-4" />}
        title={t("external.taxTitle")}
        hint={t("external.taxHint")}
        status={packet?.status}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <ArchiveButton record={handoff} pending={archivePending} onArchive={onArchive} />
            <Button
              size="sm"
              variant="outline"
              onClick={() => packet && downloadJson(packet, `${packet.packet_id}.json`)}
              disabled={!packet}
            >
              <Download className="h-3.5 w-3.5" />
              {t("external.downloadJson")}
            </Button>
          </div>
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
                      <th className="px-2 py-1.5 text-left">{t("external.taxAccount")}</th>
                      <th className="px-2 py-1.5 text-right">{t("external.taxDebit")}</th>
                      <th className="px-2 py-1.5 text-right">{t("external.taxCredit")}</th>
                      <th className="px-2 py-1.5 text-right">{t("external.taxBalance")}</th>
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

function PaymentCard({
  packet,
  loading,
  error,
  handoff,
  archivePending,
  onArchive,
}: {
  packet?: PaymentPacket;
  loading: boolean;
  error: unknown;
  handoff?: HandoffRecord;
  archivePending: boolean;
  onArchive: () => void;
}) {
  const { t } = useI18n();
  return (
    <Card className="p-[var(--card-pad)]">
      <SectionHead
        icon={<Wallet className="h-4 w-4" />}
        title={t("external.paymentTitle")}
        hint={t("external.paymentHint")}
        status={packet?.status}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <ArchiveButton record={handoff} pending={archivePending} onArchive={onArchive} />
            <Button
              size="sm"
              variant="outline"
              onClick={() => packet && downloadPaymentCsv(packet)}
              disabled={!packet || packet.count === 0}
            >
              <Download className="h-3.5 w-3.5" />
              {t("external.downloadCsv")}
            </Button>
          </div>
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
                    <th className="px-2 py-1.5 text-left">{t("external.paymentAccount")}</th>
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
  handoff,
  archivePending,
  onArchive,
}: {
  packet?: ConsolidationPacket;
  loading: boolean;
  error: unknown;
  groups: { id: string; name: string }[];
  groupId: string;
  onGroup: (value: string) => void;
  handoff?: HandoffRecord;
  archivePending: boolean;
  onArchive: () => void;
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
            <ArchiveButton record={handoff} pending={archivePending} onArchive={onArchive} />
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
                  <th className="px-2 py-1.5 text-right">{t("external.consolidationOwnership")}</th>
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

function handoffKindLabel(kind: string, t: (key: string) => string): string {
  if (kind === "tax") return t("external.handoffKindTax");
  if (kind === "payment") return t("external.handoffKindPayment");
  if (kind === "consolidation") return t("external.handoffKindConsolidation");
  return kind;
}

function formatTs(value: string): string {
  return value ? value.replace("T", " ").slice(0, 16) : "—";
}

function HandoffLedger({
  data,
  loading,
  error,
  note,
  onNote,
  onAck,
  ackPendingId,
  flash,
  hashes,
}: {
  data?: HandoffLedger;
  loading: boolean;
  error: unknown;
  note: string;
  onNote: (value: string) => void;
  onAck: (packetId: string) => void;
  ackPendingId?: string;
  flash: { tone: "ok" | "danger"; text: string } | null;
  hashes: Record<string, string>;
}) {
  const { t } = useI18n();
  const records = data?.records ?? [];
  return (
    <Card className="p-[var(--card-pad)]">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2">
          <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <ClipboardList className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2 text-sm font-semibold">
              {t("external.ledgerTitle")}
              {data ? (
                <>
                  <Badge variant="muted">
                    {t("external.handoffTotal")} {data.total}
                  </Badge>
                  <Badge variant="warn">
                    {t("external.handoffArchived")} {data.archived_count}
                  </Badge>
                  <Badge variant="ok">
                    {t("external.handoffHanded")} {data.handed_count}
                  </Badge>
                </>
              ) : null}
            </div>
            <div className="mt-0.5 max-w-3xl text-[11px] leading-relaxed text-muted-foreground">
              {t("external.ledgerHint")}
            </div>
          </div>
        </div>
        <label className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          {t("external.handoffNote")}
          <input
            className="h-8 w-52 rounded-md border border-border/70 bg-background px-2 text-xs text-foreground outline-none focus:border-primary"
            value={note}
            maxLength={120}
            placeholder={t("external.handoffNotePlaceholder")}
            onChange={(event) => onNote(event.target.value)}
          />
        </label>
      </div>

      {flash ? (
        <div
          className={
            "mt-3 rounded-lg px-2.5 py-2 text-[11px] " +
            (flash.tone === "ok"
              ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
              : "bg-red-500/10 text-red-700 dark:text-red-400")
          }
        >
          {flash.text}
        </div>
      ) : null}

      {loading ? (
        <div className="mt-3 h-20 animate-pulse rounded-lg bg-muted/30" />
      ) : error ? (
        <div className="mt-3 text-xs text-down">{t("external.loadFailed")}</div>
      ) : records.length === 0 ? (
        <div className="mt-3">
          <EmptyState mode="compact" text={t("external.ledgerEmpty")} />
        </div>
      ) : (
        <div className="mt-3 overflow-x-auto rounded-lg border border-border/60">
          <Table size="2xs" minWidth={1080}>
            <thead className="bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-2 py-1.5 text-left">{t("external.handoffKind")}</th>
                <th className="px-2 py-1.5 text-left">{t("external.handoffPeriod")}</th>
                <th className="px-2 py-1.5 text-left">{t("external.handoffPacket")}</th>
                <th className="px-2 py-1.5 text-left">{t("external.handoffHash")}</th>
                <th className="px-2 py-1.5 text-left">{t("external.handoffArchivedAt")}</th>
                <th className="px-2 py-1.5 text-left">{t("external.handoffState")}</th>
                <th className="px-2 py-1.5 text-left">{t("external.handoffAction")}</th>
              </tr>
            </thead>
            <tbody>
              {records.map((record) => {
                const currentHash = hashes[record.packet_id];
                const matches = currentHash ? currentHash === record.source_hash : null;
                const acking = ackPendingId === record.packet_id;
                return (
                  <tr key={record.packet_id} className="border-t border-border/50 align-top">
                    <td className="whitespace-nowrap px-2 py-2">{handoffKindLabel(record.kind, t)}</td>
                    <td className="whitespace-nowrap px-2 py-2 tabular-nums">{record.period}</td>
                    <td className="px-2 py-2">
                      <div className="font-mono text-[10px]">{record.packet_id}</div>
                      {record.note ? (
                        <div className="mt-0.5 max-w-[180px] truncate text-muted-foreground" title={record.note}>
                          {record.note}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-2 py-2">
                      <div className="flex items-start gap-1.5">
                        <span className="max-w-[230px] break-all font-mono text-[10px]" title={record.source_hash}>
                          {record.source_hash || "—"}
                        </span>
                        {matches === null ? null : (
                          <Badge variant={matches ? "ok" : "danger"}>
                            {matches ? t("external.hashMatched") : t("external.hashMismatch")}
                          </Badge>
                        )}
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-2 py-2 tabular-nums">{formatTs(record.archived_at)}</td>
                    <td className="whitespace-nowrap px-2 py-2">
                      <StatusBadge status={record.state} t={t} />
                    </td>
                    <td className="px-2 py-2">
                      {record.state === "handed_over" ? (
                        <div className="text-[10.5px] text-muted-foreground">
                          <div className="flex items-center gap-1 text-emerald-700 dark:text-emerald-400">
                            <CheckCircle2 className="h-3 w-3" />
                            {formatTs(record.handed_at)}
                          </div>
                          {record.handed_note ? (
                            <div className="mt-0.5 max-w-[160px] truncate" title={record.handed_note}>
                              {record.handed_note}
                            </div>
                          ) : null}
                        </div>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => onAck(record.packet_id)}
                          disabled={acking}
                        >
                          {acking ? t("external.handoffAcking") : t("external.handoffAck")}
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </div>
      )}

      <div className="mt-3 text-[10.5px] leading-relaxed text-muted-foreground">
        {data?.boundary ?? t("external.boundaryText")}
      </div>
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
  const ledger = useHandoffLedger(50);
  const archive = useArchiveHandoff();
  const ack = useAckHandoff();
  const [note, setNote] = useState("");
  const [flash, setFlash] = useState<{ tone: "ok" | "danger"; text: string } | null>(null);

  const recordsByPacket = useMemo(() => {
    const map = new Map<string, HandoffRecord>();
    for (const record of ledger.data?.records ?? []) map.set(record.packet_id, record);
    return map;
  }, [ledger.data]);

  const currentHashes: Record<string, string> = {};
  if (tax.data?.source_hash) currentHashes[tax.data.packet_id] = tax.data.source_hash;
  if (payment.data?.source_hash) currentHashes[payment.data.packet_id] = payment.data.source_hash;
  if (consolidation.data?.source_hash) currentHashes[consolidation.data.packet_id] = consolidation.data.source_hash;

  function archivePacket(kind: HandoffRecord["kind"], packetId?: string, group?: string) {
    if (!packetId) return;
    setFlash(null);
    archive.mutate(
      { kind, period, group_id: group, note },
      {
        onSuccess: (result) =>
          setFlash({
            tone: "ok",
            text: result.created ? t("external.archiveDone") : t("external.archivedBadge"),
          }),
        onError: (error: Error) =>
          setFlash({ tone: "danger", text: `${t("external.handoffFailed")}：${error.message}` }),
      },
    );
  }

  function acknowledge(packetId: string) {
    setFlash(null);
    ack.mutate(
      { packet_id: packetId, note },
      {
        onSuccess: () => setFlash({ tone: "ok", text: t("external.handoffAckDone") }),
        onError: (error: Error) =>
          setFlash({ tone: "danger", text: `${t("external.handoffFailed")}：${error.message}` }),
      },
    );
  }

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
      <TaxCard
        packet={tax.data}
        loading={tax.isLoading}
        error={tax.error}
        handoff={tax.data ? recordsByPacket.get(tax.data.packet_id) : undefined}
        archivePending={archive.isPending && archive.variables?.kind === "tax"}
        onArchive={() => archivePacket("tax", tax.data?.packet_id)}
      />
      <PaymentCard
        packet={payment.data}
        loading={payment.isLoading}
        error={payment.error}
        handoff={payment.data ? recordsByPacket.get(payment.data.packet_id) : undefined}
        archivePending={archive.isPending && archive.variables?.kind === "payment"}
        onArchive={() => archivePacket("payment", payment.data?.packet_id)}
      />
      <ConsolidationCard
        packet={consolidation.data}
        loading={consolidation.isLoading}
        error={consolidation.error}
        groups={groupOptions}
        groupId={groupId}
        onGroup={setGroupId}
        handoff={consolidation.data ? recordsByPacket.get(consolidation.data.packet_id) : undefined}
        archivePending={archive.isPending && archive.variables?.kind === "consolidation"}
        onArchive={() => archivePacket("consolidation", consolidation.data?.packet_id, groupId)}
      />
      <HandoffLedger
        data={ledger.data}
        loading={ledger.isLoading}
        error={ledger.error}
        note={note}
        onNote={setNote}
        onAck={acknowledge}
        ackPendingId={ack.isPending ? ack.variables?.packet_id : undefined}
        flash={flash}
        hashes={currentHashes}
      />
    </div>
  );
}

/** 外部协同前置包（4.21.1）：税务核对、付款草稿、合并审计，附交接留档台账。
 *  这一版把原来的密排表格改成可读的检查项、科目卡、付款时间线与交接路径；
 *  只导出，不代执行。 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Archive,
  ArrowRight,
  BadgeCheck,
  BookOpen,
  Building2,
  CalendarDays,
  CheckCircle2,
  ClipboardList,
  Clock3,
  Download,
  FileCheck2,
  Files,
  Handshake,
  Landmark,
  Link2,
  ListChecks,
  ShieldAlert,
  ShieldCheck,
  UserCheck,
  Wallet,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import {
  BlockHeading,
  CashFlowChart,
  DonutRing,
  FigureBlock,
  OverviewMetric,
  ProgressLine,
  ScaleRow,
} from "@/components/external/ExternalVisuals";
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

function StatusBadge({ status, t }: { status: string; t: (key: string, vars?: Record<string, string | number>) => string }) {
  return (
    <Badge variant={statusTone(status)} className="px-2.5 py-1 text-[11.5px]">
      {t(`external.status.${status}`)}
    </Badge>
  );
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
    return (
      <Badge variant={record.state === "handed_over" ? "ok" : "warn"} className="h-9 gap-1.5 px-3 text-[12.5px]">
        {record.state === "handed_over" ? <CheckCircle2 className="h-4 w-4" /> : <Archive className="h-4 w-4" />}
        {t(`external.status.${record.state}`)}
      </Badge>
    );
  }
  return (
    <Button
      size="sm"
      variant="secondary"
      onClick={onArchive}
      disabled={pending}
      className="h-9 rounded-xl px-3.5 text-[13px] shadow-sm"
    >
      <Archive className="h-4 w-4" />
      {pending ? t("external.archiving") : t("external.archive")}
    </Button>
  );
}

function BoundaryNote() {
  const { t } = useI18n();
  return (
    <div className="flex items-start gap-3 rounded-2xl border border-amber-500/20 bg-gradient-to-r from-amber-500/8 to-transparent px-4 py-3.5 text-[12.5px] leading-relaxed text-amber-800 dark:text-amber-200">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-amber-500/15">
        <ShieldAlert className="h-4 w-4" />
      </div>
      <div>
        <div className="font-semibold">{t("external.boundaryTitle")}</div>
        <div className="mt-1 text-amber-700/85 dark:text-amber-300/80">{t("external.boundaryText")}</div>
      </div>
    </div>
  );
}

function CheckIcon({ status }: { status: ExternalCheck["status"] }) {
  if (status === "ok") return <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />;
  if (status === "error" || status === "blocked") return <XCircle className="h-4 w-4 text-red-600 dark:text-red-400" />;
  return <Clock3 className="h-4 w-4 text-amber-600 dark:text-amber-400" />;
}

function CheckPanel({ checks }: { checks: ExternalCheck[] }) {
  const { t } = useI18n();
  const passed = checks.filter((check) => check.status === "ok").length;
  return (
    <div className="mt-6">
      <BlockHeading
        icon={<ListChecks className="h-4 w-4" />}
        title={t("external.taxChecks")}
        hint={t("external.checkHint")}
        aside={
          <div className="text-[12px] font-semibold text-muted-foreground">
            {t("external.checkPassed", { ok: passed, total: checks.length })}
          </div>
        }
      />
      <ProgressLine
        value={checks.length ? (passed / checks.length) * 100 : 0}
        tone={passed === checks.length ? "emerald" : "amber"}
        className="mt-2.5"
      />
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {checks.map((check) => (
          <div
            key={check.id}
            className="flex items-start gap-2.5 rounded-xl border border-border/45 bg-background/45 px-3 py-2.5 transition-colors hover:border-border"
          >
            <span className="mt-0.5 shrink-0">
              <CheckIcon status={check.status} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-[11px] font-medium text-muted-foreground">{check.id}</span>
                <StatusBadge status={check.status} t={t} />
              </div>
              <div className="mt-1 text-[12px] leading-relaxed text-muted-foreground">{check.detail}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function PacketCard({
  icon,
  title,
  hint,
  status,
  action,
  accent,
  iconClass,
  children,
}: {
  icon: ReactNode;
  title: string;
  hint: string;
  status?: string;
  action: ReactNode;
  accent: string;
  iconClass: string;
  children: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <Card className="relative overflow-hidden rounded-[24px] border-border/60 bg-card p-0 shadow-[var(--shadow-soft)] transition-shadow duration-300 hover:shadow-[var(--shadow-lift)]">
      <div className="h-[5px] w-full" style={{ background: `linear-gradient(90deg, ${accent}, ${accent}22 45%, transparent)` }} />
      <div className="p-4 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl ${iconClass}`}>{icon}</div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-[18px] font-bold tracking-tight sm:text-[19px]">{title}</h2>
                {status ? <StatusBadge status={status} t={t} /> : null}
              </div>
              <p className="mt-1 max-w-2xl text-[12.5px] leading-relaxed text-muted-foreground">{hint}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">{action}</div>
        </div>
        {children}
      </div>
    </Card>
  );
}

function AccountList({ rows }: { rows: TaxPacket["account_summary"] }) {
  const { t } = useI18n();
  return (
    <div className="mt-6">
      <BlockHeading
        icon={<BookOpen className="h-4 w-4" />}
        title={t("external.taxAccounts")}
        hint={t("external.taxAccountsHint")}
      />
      <div className="mt-3 grid gap-2 md:grid-cols-2">
        {rows.map((row) => (
          <div
            key={row.account_code}
            className="group rounded-xl border border-border/45 bg-background/40 px-3 py-3 transition-colors hover:border-border hover:bg-background/65"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-md bg-muted/55 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
                    {row.account_code}
                  </span>
                  <span className="truncate text-[12.5px] font-medium">{row.account_name}</span>
                </div>
                <div className="mt-1 text-[11px] text-muted-foreground">
                  {t("external.taxDebit")} {fmtMoney(row.debit)} · {t("external.taxCredit")} {fmtMoney(row.credit)}
                </div>
              </div>
              <div className="shrink-0 text-right">
                <div
                  className={`text-[16px] font-semibold leading-tight tabular-nums ${
                    row.balance < 0 ? "text-red-700 dark:text-red-400" : ""
                  }`}
                >
                  {fmtMoney(row.balance)}
                </div>
                <div className="mt-1 text-[10.5px] text-muted-foreground">{t("external.taxBalance")}</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function LegendRow({
  color,
  label,
  value,
  percent,
}: {
  color: string;
  label: string;
  value: string;
  percent: number;
}) {
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-1.5 text-[11.5px] text-muted-foreground">
          <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: color }} />
          <span className="truncate">{label}</span>
        </span>
        <span className="shrink-0 text-[12px] font-semibold tabular-nums">{value}</span>
      </div>
      <div className="mt-1 h-1 overflow-hidden rounded-full bg-border/55">
        <div className="h-full rounded-full" style={{ width: `${percent}%`, background: color }} />
      </div>
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
  const income = Number(packet?.summary.income ?? 0);
  const expense = Number(packet?.summary.expense ?? 0);
  const profit = Number(packet?.summary.profit ?? 0);
  const base = income > 0 ? income : Math.max(expense + profit, 1);
  const expenseShare = Math.max(0, Math.min((expense / base) * 100, 100));
  const profitShare = Math.max(0, Math.min((profit / base) * 100, 100));
  return (
    <PacketCard
      icon={<FileCheck2 className="h-5 w-5" />}
      iconClass="bg-emerald-500/12 text-emerald-700 dark:text-emerald-300"
      accent="#10b981"
      title={t("external.taxTitle")}
      hint={t("external.taxHint")}
      status={packet?.status}
      action={
        <>
          <ArchiveButton record={handoff} pending={archivePending} onArchive={onArchive} />
          <Button
            size="sm"
            variant="outline"
            onClick={() => packet && downloadJson(packet, `${packet.packet_id}.json`)}
            disabled={!packet}
            className="h-9 rounded-xl px-3.5 text-[13px]"
          >
            <Download className="h-4 w-4" />
            {t("external.downloadJson")}
          </Button>
        </>
      }
    >
      {loading ? (
        <div className="mt-5 h-64 animate-pulse rounded-2xl bg-muted/25" />
      ) : error || !packet ? (
        <div className="mt-5 rounded-xl bg-red-500/8 px-3 py-3 text-[12.5px] text-down">{t("external.loadFailed")}</div>
      ) : (
        <>
          <div className="mt-5 grid gap-4 rounded-[22px] border border-border/50 bg-gradient-to-br from-emerald-500/6 via-background/40 to-transparent p-4 sm:p-5 lg:grid-cols-[1.08fr_0.92fr]">
            <div>
              <div className="text-[12px] font-medium tracking-wide text-muted-foreground">{t("external.taxNet")}</div>
              <div className="mt-1.5 text-[32px] font-bold leading-none tracking-tight tabular-nums num-in sm:text-[36px]">
                {fmtMoney(packet.summary.tax_net)}
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Badge variant="warn" className="px-2.5 py-1 text-[11.5px]">
                  {t("external.taxNotSubmitted")}
                </Badge>
                <span className="break-all font-mono text-[11px] text-muted-foreground">{packet.packet_id}</span>
              </div>
              <div className="mt-5 grid grid-cols-2 gap-2">
                <FigureBlock label={t("external.taxIncome")} value={fmtMoney(income)} tone="positive" />
                <FigureBlock
                  label={t("external.taxEntries")}
                  value={`${packet.posted_entries} / ${packet.draft_entries}`}
                  hint={`${t("external.taxPosted")} / ${t("external.taxDraftsShort")}`}
                />
              </div>
            </div>
            <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-border/40 bg-background/45 p-3 sm:flex-row sm:gap-5">
              <DonutRing
                size={136}
                thickness={11}
                ariaLabel={t("external.taxSplit")}
                segments={[
                  { value: expense, color: "#d97706" },
                  { value: profit, color: "hsl(var(--primary))" },
                ]}
                center={
                  <>
                    <span className="text-[22px] font-bold tabular-nums">{Math.round(profitShare)}%</span>
                    <span className="mt-0.5 text-[10.5px] text-muted-foreground">{t("external.taxMargin")}</span>
                  </>
                }
              />
              <div className="w-full min-w-[138px] space-y-3 sm:w-auto">
                <div className="text-[11.5px] font-semibold text-muted-foreground">{t("external.taxSplit")}</div>
                <LegendRow color="#d97706" label={t("external.taxExpense")} value={fmtMoney(expense)} percent={expenseShare} />
                <LegendRow
                  color="hsl(var(--primary))"
                  label={t("external.taxProfit")}
                  value={fmtMoney(profit)}
                  percent={profitShare}
                />
              </div>
            </div>
          </div>
          <CheckPanel checks={packet.checks} />
          {packet.account_summary.length ? <AccountList rows={packet.account_summary} /> : null}
          <div className="mt-5 border-t border-border/40 pt-3 text-[11.5px] leading-relaxed text-muted-foreground">
            {packet.boundary}
          </div>
        </>
      )}
    </PacketCard>
  );
}

function certaintyLabel(certainty: string, t: (key: string) => string): string {
  if (certainty === "high") return t("external.certainty.high");
  if (certainty === "low") return t("external.certainty.low");
  return t("external.certainty.medium");
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
  const opening = Number(packet?.opening ?? 0);
  const total = Number(packet?.total ?? 0);
  const floor = Number(packet?.target_min ?? 0);
  const closing = opening - total;
  const below = closing < floor;
  return (
    <PacketCard
      icon={<Wallet className="h-5 w-5" />}
      iconClass="bg-amber-500/14 text-amber-700 dark:text-amber-300"
      accent="#f59e0b"
      title={t("external.paymentTitle")}
      hint={t("external.paymentHint")}
      status={packet?.status}
      action={
        <>
          <ArchiveButton record={handoff} pending={archivePending} onArchive={onArchive} />
          <Button
            size="sm"
            variant="outline"
            onClick={() => packet && downloadPaymentCsv(packet)}
            disabled={!packet || packet.count === 0}
            className="h-9 rounded-xl px-3.5 text-[13px]"
          >
            <Download className="h-4 w-4" />
            {t("external.downloadCsv")}
          </Button>
        </>
      }
    >
      {loading ? (
        <div className="mt-5 h-64 animate-pulse rounded-2xl bg-muted/25" />
      ) : error || !packet ? (
        <div className="mt-5 rounded-xl bg-red-500/8 px-3 py-3 text-[12.5px] text-down">{t("external.loadFailed")}</div>
      ) : (
        <>
          <div className="mt-5 grid gap-4 rounded-[22px] border border-border/50 bg-gradient-to-br from-amber-500/6 via-background/40 to-transparent p-4 sm:p-5 lg:grid-cols-[0.78fr_1.22fr]">
            <div>
              <div className="text-[12px] font-medium tracking-wide text-muted-foreground">{t("external.paymentTotal")}</div>
              <div className="mt-1.5 text-[32px] font-bold leading-none tracking-tight tabular-nums num-in sm:text-[36px]">
                {fmtMoney(total)}
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Badge variant="warn" className="px-2.5 py-1 text-[11.5px]">
                  {t("external.paymentDraftBadge")}
                </Badge>
                <span className="rounded-lg bg-muted/45 px-2 py-1 text-[11.5px] text-muted-foreground">
                  {packet.count} {t("external.paymentCount")}
                </span>
              </div>
              <div className="mt-5 grid grid-cols-2 gap-2">
                <FigureBlock label={t("external.paymentOpening")} value={fmtMoney(opening)} />
                <FigureBlock label={t("external.paymentGuard")} value={fmtMoney(floor)} />
              </div>
              <div className="mt-2">
                <FigureBlock
                  label={t("external.paymentLiquidity")}
                  value={fmtMoney(closing)}
                  tone={below ? "negative" : "positive"}
                  hint={below ? t("external.paymentBelowBuffer") : t("external.paymentAboveBuffer")}
                />
              </div>
            </div>
            <div>
              <div className="flex flex-wrap items-end justify-between gap-2">
                <div>
                  <div className="text-[13px] font-semibold">{t("external.paymentFlow")}</div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">{t("external.paymentFlowHint")}</div>
                </div>
                <Badge variant={below ? "danger" : "ok"} className="px-2.5 py-1 text-[11.5px]">
                  {below
                    ? t("external.paymentBelowBufferWithGap", { gap: fmtMoney(floor - closing) })
                    : t("external.paymentAboveBufferWithGap", { gap: fmtMoney(closing - floor) })}
                </Badge>
              </div>
              <div className="mt-2.5">
                <CashFlowChart
                  opening={opening}
                  outflow={total}
                  closing={closing}
                  floor={floor}
                  labels={[
                    t("external.paymentOpening"),
                    t("external.paymentOutflowShort"),
                    t("external.paymentLiquidity"),
                  ]}
                  formatter={(value) => fmtMoney(value)}
                />
              </div>
            </div>
          </div>

          {below ? (
            <div className="mt-3 flex items-start gap-2 rounded-xl border border-red-500/15 bg-red-500/8 px-3 py-2.5 text-[12px] text-red-700 dark:text-red-300">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{t("external.paymentBufferWarning", { gap: fmtMoney(floor - closing) })}</span>
            </div>
          ) : null}

          <div className="mt-6">
            <BlockHeading
              icon={<CalendarDays className="h-4 w-4" />}
              title={t("external.paymentSchedule")}
              hint={t("external.paymentScheduleHint")}
              aside={
                <Badge variant="muted" className="px-2.5 py-1 text-[11.5px]">
                  {packet.count}
                </Badge>
              }
            />
            {packet.count === 0 ? (
              <div className="mt-3">
                <EmptyState mode="compact" text={t("external.paymentEmpty")} />
              </div>
            ) : (
              <ol className="mt-3 space-y-2">
                {packet.instructions.map((row) => (
                  <li
                    key={row.seq}
                    className="flex items-start gap-3 rounded-xl border border-border/45 bg-background/40 px-3 py-3 transition-all hover:-translate-y-px hover:border-border hover:bg-background/65"
                  >
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-amber-500/12 text-[13px] font-bold text-amber-700 dark:text-amber-300">
                      {row.seq}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                        <div className="flex min-w-0 flex-wrap items-center gap-2">
                          <span className="truncate text-[13.5px] font-semibold">{row.counterparty || "—"}</span>
                          <span className="rounded-md bg-muted/45 px-1.5 py-0.5 font-mono text-[10.5px] text-muted-foreground">
                            {row.account_code}
                          </span>
                        </div>
                        <span className="shrink-0 text-[16px] font-bold tabular-nums">{fmtMoney(row.amount)}</span>
                      </div>
                      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-muted-foreground">
                        <span className="inline-flex items-center gap-1">
                          <CalendarDays className="h-3.5 w-3.5" />
                          {row.expected_date}
                        </span>
                        <span>·</span>
                        <Badge
                          variant={row.certainty === "high" ? "ok" : row.certainty === "low" ? "warn" : "muted"}
                          className="px-2 py-0.5 text-[10.5px]"
                        >
                          {certaintyLabel(row.certainty, t)}
                        </Badge>
                        {row.review ? <span className="text-amber-700 dark:text-amber-300">{row.review}</span> : null}
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>
          <CheckPanel checks={packet.checks} />
          <div className="mt-4 flex items-start gap-2 rounded-xl border border-border/45 bg-muted/15 px-3 py-2.5 text-[12px] leading-relaxed text-muted-foreground">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <span>{t("external.paymentNever")}</span>
          </div>
          <div className="mt-3 text-[11.5px] leading-relaxed text-muted-foreground">{packet.boundary}</div>
        </>
      )}
    </PacketCard>
  );
}

function EntityCard({ entity }: { entity: ConsolidationPacket["entities"][number] }) {
  const { t } = useI18n();
  return (
    <div className="rounded-2xl border border-border/45 bg-background/40 p-3.5 transition-all hover:-translate-y-0.5 hover:border-border hover:shadow-[var(--shadow-soft)]">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 text-[13px] font-semibold">{entity.name || `#${entity.tenant_id}`}</div>
        <Badge variant={entity.status === "ok" ? "ok" : "warn"} className="shrink-0 px-2 py-0.5 text-[10.5px]">
          {t(`external.status.${entity.status === "ok" ? "ok" : "review"}`)}
        </Badge>
      </div>
      <div className="mt-2 flex items-end justify-between gap-2">
        <div>
          <div className="text-[25px] font-bold leading-none tabular-nums">{entity.ownership_pct}%</div>
          <div className="mt-1 text-[10.5px] text-muted-foreground">{t("external.consolidationOwnership")}</div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <Badge variant="muted" className="px-2 py-0.5 font-mono text-[10px]">
            {entity.method}
          </Badge>
          <Badge variant={entity.included ? "ok" : "muted"} className="px-2 py-0.5 text-[10.5px]">
            {entity.included ? t("external.consolidationIncluded") : t("external.consolidationExcluded")}
          </Badge>
        </div>
      </div>
      <ProgressLine value={entity.ownership_pct} tone={entity.included ? "indigo" : "amber"} className="mt-3" />
    </div>
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
  const revenue = Number(packet?.summary.consolidated?.revenue ?? 0);
  const profit = Number(packet?.summary.consolidated?.net_profit ?? 0);
  const assets = Number(packet?.summary.consolidated?.total_assets ?? 0);
  const scale = Math.max(revenue, assets, profit, 1);
  return (
    <PacketCard
      icon={<Building2 className="h-5 w-5" />}
      iconClass="bg-indigo-500/12 text-indigo-700 dark:text-indigo-300"
      accent="#6366f1"
      title={t("external.consolidationTitle")}
      hint={t("external.consolidationHint")}
      status={packet?.status}
      action={
        <>
          <ArchiveButton record={handoff} pending={archivePending} onArchive={onArchive} />
          <select
            className="h-9 rounded-xl border border-border/70 bg-background px-3 text-[13px] font-medium text-foreground outline-none transition-colors focus:border-primary"
            value={groupId}
            onChange={(event) => onGroup(event.target.value)}
            aria-label={t("external.group")}
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
            className="h-9 rounded-xl px-3.5 text-[13px]"
          >
            <Download className="h-4 w-4" />
            {t("external.downloadAudit")}
          </Button>
        </>
      }
    >
      {groups.length === 0 ? (
        <div className="mt-5">
          <EmptyState mode="compact" text={t("external.groupEmpty")} />
        </div>
      ) : loading ? (
        <div className="mt-5 h-64 animate-pulse rounded-2xl bg-muted/25" />
      ) : error || !packet ? (
        <div className="mt-5 rounded-xl bg-red-500/8 px-3 py-3 text-[12.5px] text-down">{t("external.loadFailed")}</div>
      ) : (
        <>
          <div className="mt-5 grid gap-4 rounded-[22px] border border-border/50 bg-gradient-to-br from-indigo-500/7 via-background/40 to-transparent p-4 sm:p-5 lg:grid-cols-[0.92fr_1.08fr]">
            <div className="rounded-2xl border border-border/40 bg-background/45 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-[13px] font-semibold">{packet.group.name || packet.group.id}</div>
                <Badge variant="muted" className="px-2.5 py-1 text-[11px]">
                  <ShieldCheck className="h-3.5 w-3.5" />
                  {t("external.auditNotLegal")}
                </Badge>
              </div>
              <div className="mt-3 space-y-1">
                <ScaleRow label={t("external.consolidationRevenue")} value={fmtMoney(revenue)} ratio={100} color="hsl(var(--primary))" />
                <ScaleRow
                  label={t("external.consolidationProfit")}
                  value={fmtMoney(profit)}
                  ratio={(profit / scale) * 100}
                  color="#6366f1"
                  hint={revenue > 0 ? `${t("external.taxMargin")} ${Math.round((profit / revenue) * 100)}%` : undefined}
                />
                <ScaleRow
                  label={t("external.consolidationAssets")}
                  value={fmtMoney(assets)}
                  ratio={(assets / scale) * 100}
                  color="#f59e0b"
                />
              </div>
            </div>
            <div>
              <div className="flex flex-wrap items-end justify-between gap-2">
                <div>
                  <div className="text-[13px] font-semibold">{t("external.consolidationEntities")}</div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">{t("external.consolidationEntitiesHint")}</div>
                </div>
                <span className="text-[11.5px] text-muted-foreground">
                  {packet.entities.filter((entity) => entity.included).length} / {packet.entities.length}
                </span>
              </div>
              <div className="mt-2.5 grid gap-2 sm:grid-cols-2">
                {packet.entities.map((entity) => (
                  <EntityCard key={entity.tenant_id} entity={entity} />
                ))}
              </div>
            </div>
          </div>

          <div className="mt-3 flex items-start gap-2 rounded-xl border border-border/45 bg-muted/15 px-3 py-2.5 text-[11.5px] text-muted-foreground">
            <Link2 className="mt-0.5 h-4 w-4 shrink-0 text-indigo-600 dark:text-indigo-400" />
            <span className="shrink-0 font-medium text-foreground">{t("external.consolidationHash")}</span>
            <code className="break-all font-mono">{packet.source_hash}</code>
          </div>
          <CheckPanel checks={packet.checks} />
          {(packet.warnings ?? []).map((warning) => (
            <div
              key={warning}
              className="mt-2 flex items-start gap-2 rounded-xl bg-amber-500/10 px-3 py-2.5 text-[12px] text-amber-700 dark:text-amber-300"
            >
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{warning}</span>
            </div>
          ))}
          <div className="mt-4 text-[11.5px] leading-relaxed text-muted-foreground">{packet.boundary}</div>
        </>
      )}
    </PacketCard>
  );
}

function handoffKindLabel(kind: string, t: (key: string) => string): string {
  if (kind === "tax") return t("external.handoffKindTax");
  if (kind === "payment") return t("external.handoffKindPayment");
  if (kind === "consolidation") return t("external.handoffKindConsolidation");
  return kind;
}

function handoffKindVisual(kind: string): { icon: ReactNode; className: string } {
  if (kind === "tax") {
    return { icon: <FileCheck2 className="h-4 w-4" />, className: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300" };
  }
  if (kind === "payment") {
    return { icon: <Wallet className="h-4 w-4" />, className: "bg-amber-500/14 text-amber-700 dark:text-amber-300" };
  }
  return { icon: <Building2 className="h-4 w-4" />, className: "bg-indigo-500/12 text-indigo-700 dark:text-indigo-300" };
}

function formatTs(value: string): string {
  return value ? value.replace("T", " ").slice(0, 16) : "";
}

function LedgerJourney({ record, t }: { record: HandoffRecord; t: (key: string) => string }) {
  const handed = record.state === "handed_over";
  return (
    <div className="grid min-w-0 gap-2 rounded-2xl border border-border/45 bg-background/45 px-3 py-2.5 sm:flex sm:items-center">
      <div className="flex min-w-0 items-center gap-2">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-500/12 text-amber-700 dark:text-amber-300">
          <Archive className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0">
          <div className="text-[11.5px] font-medium text-muted-foreground">{t("external.ledgerStepArchive")}</div>
          <div className="truncate text-[12.5px] font-semibold tabular-nums">{formatTs(record.archived_at) || "—"}</div>
        </div>
      </div>
      <div className="hidden min-w-[34px] flex-1 items-center gap-1 sm:flex">
        <div className={`h-[2px] flex-1 rounded-full ${handed ? "bg-emerald-500/55" : "bg-border"}`} />
        <ArrowRight className={`h-3.5 w-3.5 shrink-0 ${handed ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground/50"}`} />
      </div>
      <div className="flex min-w-0 items-center gap-2">
        <span
          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
            handed ? "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300" : "bg-muted/55 text-muted-foreground"
          }`}
        >
          {handed ? <Handshake className="h-3.5 w-3.5" /> : <Clock3 className="h-3.5 w-3.5" />}
        </span>
        <div className="min-w-0">
          <div className="text-[11.5px] font-medium text-muted-foreground">{t("external.ledgerStepHandoff")}</div>
          <div className={`truncate text-[12.5px] font-semibold tabular-nums ${handed ? "text-emerald-700 dark:text-emerald-400" : "text-muted-foreground"}`}>
            {handed ? formatTs(record.handed_at) : t("external.ledgerPending")}
          </div>
        </div>
      </div>
    </div>
  );
}

function LedgerRecordCard({
  record,
  matches,
  acking,
  onAck,
  index,
}: {
  record: HandoffRecord;
  matches: boolean | null;
  acking: boolean;
  onAck: () => void;
  index: number;
}) {
  const { t } = useI18n();
  const visual = handoffKindVisual(record.kind);
  const handed = record.state === "handed_over";
  return (
    <article
      className="animate-fade-in relative overflow-hidden rounded-2xl border border-border/50 bg-card p-4 shadow-xs transition-all duration-300 hover:-translate-y-0.5 hover:border-border hover:shadow-[var(--shadow-soft)] sm:p-5"
      style={{ animationDelay: `${index * 45}ms` }}
    >
      <div className={`absolute inset-y-0 left-0 w-1 ${handed ? "bg-emerald-500/60" : "bg-amber-500/55"}`} aria-hidden />
      <div className="flex flex-wrap items-start justify-between gap-3 pl-1">
        <div className="flex min-w-0 items-start gap-3">
          <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${visual.className}`}>{visual.icon}</div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[15.5px] font-semibold">{handoffKindLabel(record.kind, t)}</span>
              <StatusBadge status={record.state} t={t} />
              <span className="rounded-lg bg-muted/45 px-2 py-0.5 text-[11px] text-muted-foreground">{record.period}</span>
            </div>
            <div className="mt-1 break-all font-mono text-[12px] text-muted-foreground">{record.packet_id}</div>
          </div>
        </div>
        {handed ? (
          <span className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-emerald-500/10 px-3 text-[12px] font-semibold text-emerald-700 dark:text-emerald-300">
            <CheckCircle2 className="h-4 w-4" />
            {formatTs(record.handed_at)}
          </span>
        ) : (
          <Button size="sm" variant="outline" onClick={onAck} disabled={acking} className="h-9 rounded-xl px-3.5 text-[13px]">
            {acking ? t("external.handoffAcking") : t("external.handoffAck")}
          </Button>
        )}
      </div>

      <div className="mt-4 grid gap-3 pl-1 md:grid-cols-[minmax(0,1fr)_340px] 2xl:grid-cols-1">
        <div className="min-w-0 space-y-3">
          {record.note ? (
            <div>
              <div className="text-[11.5px] font-medium text-muted-foreground">{t("external.ledgerNote")}</div>
              <div className="mt-0.5 text-[13px] leading-relaxed">{record.note}</div>
            </div>
          ) : null}
          <div>
            <div className="text-[11.5px] font-medium text-muted-foreground">{t("external.ledgerHash")}</div>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <code className="break-all font-mono text-[12px] text-muted-foreground">{record.source_hash || "—"}</code>
              {matches === null ? null : (
                <Badge variant={matches ? "ok" : "danger"} className="px-2 py-0.5 text-[10.5px]">
                  {matches ? t("external.hashMatched") : t("external.hashMismatch")}
                </Badge>
              )}
            </div>
          </div>
          {handed && record.handed_note && record.handed_note !== record.note ? (
            <div className="rounded-xl bg-emerald-500/6 px-3 py-2 text-[12px] text-emerald-800 dark:text-emerald-300">
              <span className="font-medium">{t("external.ledgerNote")}</span> · {record.handed_note}
            </div>
          ) : null}
        </div>
        <LedgerJourney record={record} t={t} />
      </div>
    </article>
  );
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
    <Card className="rounded-[24px] border-border/60 p-4 shadow-[var(--shadow-soft)] sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-primary/10 text-primary">
            <ClipboardList className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-[18px] font-bold tracking-tight sm:text-[19px]">{t("external.ledgerTitle")}</h2>
              {data ? (
                <>
                  <Badge variant="muted" className="px-2.5 py-1 text-[11.5px]">
                    {t("external.handoffTotal")} {data.total}
                  </Badge>
                  <Badge variant="warn" className="px-2.5 py-1 text-[11.5px]">
                    {t("external.handoffArchived")} {data.archived_count}
                  </Badge>
                  <Badge variant="ok" className="px-2.5 py-1 text-[11.5px]">
                    {t("external.handoffHanded")} {data.handed_count}
                  </Badge>
                </>
              ) : null}
            </div>
            <p className="mt-1 max-w-3xl text-[12.5px] leading-relaxed text-muted-foreground">{t("external.ledgerHint")}</p>
          </div>
        </div>
        <label className="flex w-full flex-wrap items-center gap-2 text-[12px] text-muted-foreground sm:w-auto">
          <span className="font-medium text-foreground">{t("external.handoffNote")}</span>
          <input
            className="h-10 w-full rounded-xl border border-border/70 bg-background px-3 text-[13px] text-foreground outline-none transition-colors placeholder:text-muted-foreground/70 focus:border-primary sm:w-64"
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
            "mt-4 flex items-start gap-2 rounded-xl px-3 py-2.5 text-[12px] " +
            (flash.tone === "ok"
              ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
              : "bg-red-500/10 text-red-700 dark:text-red-300")
          }
        >
          {flash.tone === "ok" ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0" />}
          <span>{flash.text}</span>
        </div>
      ) : null}

      {loading ? (
        <div className="mt-5 grid gap-3">
          <div className="h-28 animate-pulse rounded-2xl bg-muted/25" />
          <div className="h-28 animate-pulse rounded-2xl bg-muted/25" />
        </div>
      ) : error ? (
        <div className="mt-5 rounded-xl bg-red-500/8 px-3 py-3 text-[12.5px] text-down">{t("external.loadFailed")}</div>
      ) : records.length === 0 ? (
        <div className="mt-5">
          <EmptyState mode="compact" text={t("external.ledgerEmpty")} />
        </div>
      ) : (
        <div className="mt-5 grid gap-3 2xl:grid-cols-2">
          {records.map((record, index) => {
            const currentHash = hashes[record.packet_id];
            const matches = currentHash ? currentHash === record.source_hash : null;
            return (
              <LedgerRecordCard
                key={record.packet_id}
                record={record}
                matches={matches}
                acking={ackPendingId === record.packet_id}
                onAck={() => onAck(record.packet_id)}
                index={index}
              />
            );
          })}
        </div>
      )}

      <div className="mt-4 border-t border-border/40 pt-3 text-[11.5px] leading-relaxed text-muted-foreground">
        {data?.boundary ?? t("external.boundaryText")}
      </div>
    </Card>
  );
}

function HeroProgress({ handed, total }: { handed: number; total: number }) {
  const { t } = useI18n();
  const percent = total > 0 ? Math.round((handed / total) * 100) : 0;
  return (
    <div className="flex items-center gap-3">
      <DonutRing
        size={92}
        thickness={8}
        ariaLabel={t("external.heroProgress")}
        segments={[
          { value: handed, color: "hsl(var(--primary))" },
          { value: Math.max(total - handed, 0), color: "hsl(var(--border))" },
        ]}
        center={
          <>
            <span className="text-[19px] font-bold tabular-nums">{percent}%</span>
            <span className="mt-0.5 text-[9.5px] text-muted-foreground">{t("external.heroHandedShort")}</span>
          </>
        }
      />
      <div className="max-w-[130px]">
        <div className="text-[12px] font-semibold">{t("external.heroProgress")}</div>
        <div className="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">
          {t("external.heroProgressHint", { done: handed, total })}
        </div>
      </div>
    </div>
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

  const currentPackets = [tax.data, payment.data, consolidation.data].filter(Boolean);
  const allChecks = [tax.data?.checks ?? [], payment.data?.checks ?? [], consolidation.data?.checks ?? []].flat();
  const checksPassed = allChecks.filter((check) => check.status === "ok").length;
  const currentRecords = currentPackets
    .map((packet) => (packet ? recordsByPacket.get(packet.packet_id) : undefined))
    .filter((record): record is HandoffRecord => Boolean(record));
  const archivedCount = currentRecords.length;
  const handedCount = currentRecords.filter((record) => record.state === "handed_over").length;
  const packetCount = currentPackets.length;
  const attention = allChecks.length - checksPassed;

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
    <div className="view-enter grid gap-4">
      <Card className="relative overflow-hidden rounded-[28px] border-border/60 p-5 shadow-[var(--shadow-soft)] sm:p-7">
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            backgroundImage:
              "radial-gradient(110% 130% at 100% -10%, hsl(var(--primary) / 0.14), transparent 46%), radial-gradient(90% 100% at 0% 0%, hsl(var(--brand-gold) / 0.10), transparent 52%)",
          }}
        />
        <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full border border-primary/10 bg-primary/5 blur-2xl" />
        <div className="relative flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-primary/85">
              <Landmark className="h-4 w-4" />
              {t("external.heroKicker")}
            </div>
            <h1 className="mt-2 text-[25px] font-bold leading-tight tracking-tight sm:text-[30px]">{t("external.title")}</h1>
            <p className="mt-2 max-w-3xl text-[13px] leading-relaxed text-muted-foreground sm:text-[13.5px]">
              {t("external.subtitle")}
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/18 bg-primary/8 px-2.5 py-1 text-[11.5px] font-medium text-primary">
                <ShieldCheck className="h-3.5 w-3.5" />
                {t("external.heroReadOnly")}
              </span>
              <span className="inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-background/55 px-2.5 py-1 text-[11.5px] text-muted-foreground">
                <UserCheck className="h-3.5 w-3.5" />
                {t("external.heroHuman")}
              </span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex h-11 items-center gap-2 rounded-2xl border border-border/70 bg-background/65 px-3 backdrop-blur-sm">
              <span className="text-[11.5px] font-medium text-muted-foreground">{t("external.currentPeriod")}</span>
              <select
                className="min-w-[96px] bg-transparent text-[14px] font-semibold text-foreground outline-none"
                value={period}
                onChange={(event) => setPeriod(event.target.value)}
                aria-label={t("external.period")}
              >
                {(periods.data?.periods ?? []).map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
            <div className="hidden sm:block">
              <HeroProgress handed={handedCount} total={packetCount} />
            </div>
          </div>
        </div>

        <div className="relative mt-5 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
          <OverviewMetric
            icon={<Files className="h-4 w-4" />}
            label={t("external.overviewPacks")}
            value={packetCount ? String(packetCount) : "—"}
            hint={t("external.overviewPacksHint")}
            accent="primary"
            progress={packetCount ? 100 : 0}
          />
          <OverviewMetric
            icon={<BadgeCheck className="h-4 w-4" />}
            label={t("external.overviewChecks")}
            value={allChecks.length ? `${checksPassed}/${allChecks.length}` : "—"}
            hint={attention === 0 ? t("external.overviewChecksAll") : t("external.overviewChecksHint", { n: attention })}
            accent={attention === 0 ? "emerald" : "amber"}
            progress={allChecks.length ? (checksPassed / allChecks.length) * 100 : 0}
          />
          <OverviewMetric
            icon={<Archive className="h-4 w-4" />}
            label={t("external.overviewArchived")}
            value={String(archivedCount)}
            hint={t("external.overviewArchivedHint", { n: handedCount })}
            accent="amber"
            progress={packetCount ? (archivedCount / packetCount) * 100 : 0}
          />
          <OverviewMetric
            icon={<Handshake className="h-4 w-4" />}
            label={t("external.overviewHanded")}
            value={String(handedCount)}
            hint={t("external.overviewHandedHint", { n: ledger.data?.total ?? 0 })}
            accent="emerald"
            progress={packetCount ? (handedCount / packetCount) * 100 : 0}
          />
        </div>
      </Card>

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

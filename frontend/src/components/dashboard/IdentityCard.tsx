/** 财务数字身份证：总览里的可复核卡片 + 完整档案弹层。 */

import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  Database,
  Download,
  Fingerprint,
  ShieldCheck,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { StatTile } from "@/components/ui/stat";
import { copyText } from "@/lib/clipboard";
import { fmtMoney } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { useIdentityCard } from "@/lib/use-review";

function money(v: number) {
  return fmtMoney(v, false, false);
}

export function IdentityCard() {
  const { t, lang } = useI18n();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const q = useIdentityCard(lang);
  const data = q.data;

  const copySummary = () => {
    if (!data) return;
    const f = data.financials;
    const lines = [
      `# ${t("identity.dialogTitle")}`,
      `- ${t("identity.fingerprint")}: ${data.fingerprint}`,
      `- ${t("identity.netWorth")}: ${money(f.net_worth)}`,
      `- ${t("identity.cash")}: ${money(f.cash)}`,
      `- ${t("identity.liabilities")}: ${money(f.liabilities)}`,
      `- ${t("identity.monthlyNet")}: ${money(f.monthly_net)}`,
      `- ${t("identity.transactions")}: ${data.coverage.transactions}`,
      `- ${t("identity.connections")}: ${data.coverage.connections}`,
      `- ${t("identity.boundary")}`,
    ];
    if (copyText(lines.join("\n"))) toast(t("identity.copied"), "ok");
    else toast(t("identity.copyFailed"), "error");
  };

  const exportJson = () => {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `moneyhelper-identity-${data.fingerprint}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (q.isLoading) {
    return (
      <Card className="p-[var(--card-pad)]">
        <div className="h-20 animate-pulse rounded-lg bg-muted/30" />
      </Card>
    );
  }
  if (q.isError || !data) {
    return (
      <Card className="flex items-center justify-between gap-2 p-[var(--card-pad)]">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Fingerprint className="h-4 w-4" />
          {t("identity.failed")}
        </div>
        <Button size="sm" variant="outline" onClick={() => void q.refetch()}>
          {t("identity.retry")}
        </Button>
      </Card>
    );
  }

  const f = data.financials;
  const c = data.coverage;
  const risk = data.risk;

  return (
    <>
      <Card className="overflow-hidden border-primary/25 bg-gradient-to-br from-primary/[0.045] via-card to-card p-[var(--card-pad)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-2.5">
            <div className="rounded-xl border border-primary/25 bg-primary/10 p-2 text-primary">
              <Fingerprint className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[15px] font-semibold">{t("identity.title")}</span>
                <Badge variant="ok" className="text-[10px]">{t("identity.badge")}</Badge>
                <Badge variant={data.profile.mode === "real" ? "muted" : "warn"} className="text-[10px]">
                  {data.profile.mode_label}
                </Badge>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                <span className="font-mono">{data.fingerprint}</span>
                <span>{t("identity.updated")} {data.generated_at.replace("T", " ").slice(0, 16)}</span>
              </div>
            </div>
          </div>
          <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
            {t("identity.open")}
          </Button>
        </div>

        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <StatTile label={t("identity.netWorth")} value={money(f.net_worth)} size="md" tone={f.net_worth < 0 ? "negative" : "default"} />
          <StatTile label={t("identity.cash")} value={money(f.cash)} size="md" />
          <StatTile label={t("identity.coverage")} value={`${c.transactions} / ${c.active_months}`} hint={`${t("identity.transactions")} / ${t("identity.activeMonths")}`} size="md" />
          <StatTile label={t("identity.risk")} value={String(risk.count)} hint={`${t("identity.riskFlags")} · ${t("identity.connections")} ${c.connections}`} size="md" tone={risk.count ? "negative" : "positive"} />
        </div>

        <p className="mt-2.5 flex items-start gap-1.5 border-t border-border/50 pt-2 text-[10.5px] leading-relaxed text-muted-foreground">
          <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {t("identity.boundary")}
        </p>
      </Card>

      <Dialog.Root open={open} onOpenChange={setOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/45 backdrop-blur-sm data-[state=open]:animate-fade-in" />
          <Dialog.Content className="fixed left-1/2 top-1/2 z-50 flex max-h-[88vh] w-[min(94vw,54rem)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-xl border border-border bg-card shadow-lift data-[state=open]:animate-fade-in">
            <div className="flex items-start justify-between gap-3 border-b border-border/60 px-5 py-4">
              <div className="min-w-0">
                <Dialog.Title className="flex items-center gap-1.5 text-[15px] font-semibold">
                  <Fingerprint className="h-4 w-4 text-primary" />
                  {t("identity.dialogTitle")}
                </Dialog.Title>
                <Dialog.Description className="mt-1 max-w-2xl text-[11.5px] leading-relaxed text-muted-foreground">
                  {t("identity.dialogDesc")}
                </Dialog.Description>
                <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[10.5px] text-muted-foreground">
                  <span className="rounded bg-muted px-1.5 py-0.5 font-mono">{data.fingerprint}</span>
                  <span>{data.profile.mode_label}</span>
                  <span>{data.generated_at.replace("T", " ").slice(0, 16)}</span>
                </div>
              </div>
              <Dialog.Close asChild>
                <Button size="icon" variant="ghost" aria-label={t("identity.close")}>
                  <X className="h-4 w-4" />
                </Button>
              </Dialog.Close>
            </div>

            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4 scroll-thin">
              <section>
                <div className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold">
                  <Database className="h-3.5 w-3.5 text-primary" />
                  {t("identity.sectionFinancial")}
                </div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <StatTile label={t("identity.assets")} value={money(f.assets)} />
                  <StatTile label={t("identity.liabilities")} value={money(f.liabilities)} />
                  <StatTile label={t("identity.invested")} value={money(f.invested)} />
                  <StatTile label={t("identity.netWorth")} value={money(f.net_worth)} />
                  <StatTile label={t("identity.monthlyIncome")} value={money(f.monthly_income)} />
                  <StatTile label={t("identity.monthlyExpense")} value={money(f.monthly_expense)} />
                  <StatTile label={t("identity.monthlyNet")} value={money(f.monthly_net)} />
                  <StatTile label={t("identity.savingsRate")} value={`${f.savings_rate}%`} />
                  <StatTile label={t("identity.emergency")} value={`${f.emergency_months} / ${f.emergency_target_months}`} hint={t("identity.targetMonths", { n: f.emergency_target_months })} />
                  <StatTile label={t("identity.dti")} value={`${f.dti_pct}%`} />
                  <StatTile label={t("identity.riskFlags")} value={String(f.risk_flags)} tone={f.risk_flags ? "negative" : "positive"} />
                  <StatTile label={t("identity.cash")} value={money(f.cash)} />
                </div>
              </section>

              <section>
                <div className="mb-2 text-[13px] font-semibold">{t("identity.sectionCoverage")}</div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <StatTile label={t("identity.transactions")} value={String(c.transactions)} />
                  <StatTile label={t("identity.activeMonths")} value={String(c.active_months)} />
                  <StatTile label={t("identity.positions")} value={String(c.positions)} />
                  <StatTile label={t("identity.subscriptions")} value={String(c.subscriptions)} />
                  <StatTile label={t("identity.debts")} value={String(c.debts)} />
                  <StatTile label={t("identity.goals")} value={String(c.goals)} />
                  <StatTile label={t("identity.connections")} value={String(c.connections)} />
                  <StatTile label={c.budget_set ? t("identity.budgetSet") : t("identity.budgetUnset")} value={c.budget_set ? "✓" : "—"} tone={c.budget_set ? "up" : "muted"} />
                </div>
              </section>

              <section>
                <div className="mb-2 text-[13px] font-semibold">{t("identity.sectionRisk")}</div>
                {risk.items.length === 0 ? (
                  <p className="rounded-lg bg-emerald-500/10 px-3 py-2 text-[12px] text-emerald-700 dark:text-emerald-300">
                    {t("identity.noRisk")}
                  </p>
                ) : (
                  <ul className="space-y-1.5">
                    {risk.items.map((item, i) => (
                      <li key={`${item.code}-${i}`} className="flex items-start gap-2 rounded-lg border border-border/60 px-3 py-2 text-[12px]">
                        <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" />
                        <span className="text-foreground/85">{item.text}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section className="grid gap-3 sm:grid-cols-2">
                <div>
                  <div className="mb-2 text-[13px] font-semibold">{t("identity.sectionPermissions")}</div>
                  <div className="rounded-lg border border-border/60 p-3">
                    <div className="text-[11px] font-medium text-emerald-700 dark:text-emerald-300">{t("identity.can")}</div>
                    <ul className="mt-1.5 space-y-1">
                      {data.permissions.ai_can.map((x) => <li key={x} className="text-[11.5px] text-muted-foreground">· {x}</li>)}
                    </ul>
                    <div className="mt-3 text-[11px] font-medium text-red-600 dark:text-red-400">{t("identity.cannot")}</div>
                    <ul className="mt-1.5 space-y-1">
                      {data.permissions.ai_cannot.map((x) => <li key={x} className="text-[11.5px] text-muted-foreground">· {x}</li>)}
                    </ul>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {Object.entries(data.permissions.controls).map(([tier, n]) => (
                      <span key={tier} className="rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[10px] text-muted-foreground">
                        {tierLabel(t, tier)} {n}
                      </span>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="mb-2 text-[13px] font-semibold">{t("identity.sectionProvenance")}</div>
                  <div className="space-y-1.5 rounded-lg border border-border/60 p-3 text-[11.5px]">
                    <Row label={t("identity.ledger")} value={data.provenance.ledger} />
                    <Row label={t("identity.quotes")} value={data.provenance.quotes || t("identity.none")} />
                    <Row label={t("identity.lastTransaction")} value={data.provenance.last_transaction || t("identity.none")} />
                    <Row label={t("identity.lastSync")} value={data.provenance.last_connection_sync || t("identity.none")} />
                    <Row label={t("identity.mode")} value={data.profile.mode_label} />
                  </div>
                </div>
              </section>

              <section>
                <div className="mb-2 text-[13px] font-semibold">{t("identity.sectionBoundaries")}</div>
                <ul className="space-y-1 rounded-lg bg-muted/30 px-3 py-2.5">
                  {data.boundaries.map((x) => (
                    <li key={x} className="flex items-start gap-1.5 text-[11.5px] leading-relaxed text-muted-foreground">
                      <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />
                      {x}
                    </li>
                  ))}
                </ul>
              </section>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/60 px-5 py-3">
              <span className="text-[10.5px] text-muted-foreground">{data.profile.storage}</span>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="outline" onClick={copySummary}>
                  {t("identity.copy")}
                </Button>
                <Button size="sm" variant="outline" onClick={exportJson}>
                  <Download className="mr-1 h-3.5 w-3.5" />
                  {t("identity.export")}
                </Button>
              </div>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="min-w-0 break-all text-right text-foreground/85">{value}</span>
    </div>
  );
}

function tierLabel(t: (k: string) => string, tier: string) {
  const map: Record<string, string> = {
    read: "identity.controlRead",
    import: "identity.controlImport",
    handoff: "identity.controlHandoff",
    manual: "identity.controlManual",
    confirm: "identity.controlConfirm",
  };
  return t(map[tier] ?? "identity.controlManual");
}

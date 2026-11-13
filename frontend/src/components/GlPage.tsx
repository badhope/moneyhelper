import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BookOpenCheck,
  CheckCircle2,
  Plus,
  RefreshCw,
  RotateCcw,
  Scale,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm";
import { PillTabs } from "@/components/ui/pill-tabs";
import {
  closeGlPeriod,
  createGlAccount,
  createGlEntry,
  createGlPeriod,
  deleteGlEntry,
  getGlTrialBalance,
  listGlAccounts,
  listGlEntries,
  listGlPeriods,
  postGlEntry,
  reverseGlEntry,
  type GlAccount,
  type GlEntry,
  type GlPeriod,
  type GlTrialBalance,
} from "@/lib/api";
import { fmtMoney } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { useCapabilities } from "@/lib/use-capabilities";
import { cn } from "@/lib/utils";

const inputCls =
  "w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring";
const labelCls = "block text-xs text-muted-foreground mb-1";
const miniInput =
  "w-full rounded-lg border border-input bg-background px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-ring";

const ACCOUNT_TYPES = [
  { value: "asset", key: "gl.accountTypeAsset" },
  { value: "liability", key: "gl.accountTypeLiability" },
  { value: "equity", key: "gl.accountTypeEquity" },
  { value: "income", key: "gl.accountTypeIncome" },
  { value: "expense", key: "gl.accountTypeExpense" },
];

type Tab = "accounts" | "periods" | "entries" | "trial";
type LineForm = { account_id: string; debit: string; credit: string; memo: string };

function emptyLines(): LineForm[] {
  return [
    { account_id: "", debit: "", credit: "", memo: "" },
    { account_id: "", debit: "", credit: "", memo: "" },
  ];
}

/** 复式总账工作区：科目 / 期间 / 凭证 / 试算表。 */
export function GlPage() {
  const { t } = useI18n();
  const { toast } = useToast();
  const { can } = useCapabilities();
  const [tab, setTab] = useState<Tab>("entries");
  const [accounts, setAccounts] = useState<GlAccount[]>([]);
  const [periods, setPeriods] = useState<GlPeriod[]>([]);
  const [entries, setEntries] = useState<GlEntry[]>([]);
  const [trial, setTrial] = useState<GlTrialBalance | null>(null);
  const [periodId, setPeriodId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);

  const [accountForm, setAccountForm] = useState({
    code: "",
    name: "",
    type: "asset",
  });
  const now = new Date();
  const [periodForm, setPeriodForm] = useState({
    year: String(now.getFullYear()),
    month: String(now.getMonth() + 1),
  });
  const [entryForm, setEntryForm] = useState({
    entry_date: "",
    description: "",
    lines: emptyLines(),
  });
  const [confirm, setConfirm] = useState<
    | { kind: "entry"; id: number; label: string; action: "delete" | "reverse" }
    | { kind: "period"; id: number; label: string }
    | null
  >(null);

  const selectedPeriod = useMemo(
    () => periods.find((p) => p.id === periodId) ?? null,
    [periods, periodId],
  );
  const periodOpen = selectedPeriod?.status === "open";
  const canWrite = periodOpen && can("gl:write");
  const canPost = can("gl:post");
  const canClose = can("gl:close");

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([listGlAccounts(), listGlPeriods()])
      .then(([accs, ps]) => {
        if (!alive) return;
        setAccounts(accs);
        setPeriods(ps);
        setPeriodId((prev) =>
          prev && ps.some((p) => p.id === prev) ? prev : ps[0]?.id ?? null,
        );
      })
      .catch((e) => toast(e instanceof Error ? e.message : String(e), "error"))
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [toast, version]);

  useEffect(() => {
    if (!periodId) {
      setEntries([]);
      setTrial(null);
      return;
    }
    let alive = true;
    Promise.all([listGlEntries(periodId), getGlTrialBalance(periodId)])
      .then(([es, tb]) => {
        if (!alive) return;
        setEntries(es);
        setTrial(tb);
      })
      .catch((e) => toast(e instanceof Error ? e.message : String(e), "error"));
    return () => {
      alive = false;
    };
  }, [periodId, version, toast]);

  useEffect(() => {
    if (selectedPeriod) {
      setEntryForm((f) => ({
        ...f,
        entry_date: f.entry_date || selectedPeriod.start_date,
      }));
    }
  }, [selectedPeriod]);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  const doAccount = async () => {
    if (!accountForm.code.trim() || !accountForm.name.trim()) return;
    try {
      await createGlAccount({
        code: accountForm.code,
        name: accountForm.name,
        type: accountForm.type,
      });
      setAccountForm({ code: "", name: "", type: accountForm.type });
      toast(t("gl.created"), "ok");
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doPeriod = async () => {
    try {
      const r = await createGlPeriod({
        year: Number(periodForm.year),
        month: Number(periodForm.month),
      });
      setPeriodId(r.period.id);
      toast(t("gl.created"), "ok");
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const setLine = (idx: number, patch: Partial<LineForm>) => {
    setEntryForm((f) => ({
      ...f,
      lines: f.lines.map((x, i) => (i === idx ? { ...x, ...patch } : x)),
    }));
  };

  const doEntry = async () => {
    if (!entryForm.entry_date) return;
    const lines = entryForm.lines
      .filter((x) => x.account_id)
      .map((x) => ({
        account_id: Number(x.account_id),
        debit: Number(x.debit || 0),
        credit: Number(x.credit || 0),
        memo: x.memo,
      }));
    try {
      await createGlEntry({
        entry_date: entryForm.entry_date,
        description: entryForm.description,
        lines,
      });
      setEntryForm({
        entry_date: entryForm.entry_date,
        description: "",
        lines: emptyLines(),
      });
      toast(t("gl.created"), "ok");
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doPost = async (id: number) => {
    try {
      await postGlEntry(id);
      toast(t("gl.posted"), "ok");
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doConfirm = async () => {
    const target = confirm;
    setConfirm(null);
    if (!target) return;
    try {
      if (target.kind === "period") {
        await closeGlPeriod(target.id);
        toast(t("gl.closed"), "ok");
      } else if (target.action === "delete") {
        await deleteGlEntry(target.id);
        toast(t("gl.deleted"), "ok");
      } else {
        await reverseGlEntry(target.id);
        toast(t("gl.reversed"), "ok");
      }
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const accountName = (id: number) =>
    accounts.find((a) => a.id === id)?.name ?? `#${id}`;

  // 试算表的“余额”按科目正常方向展示：资产/费用借正，负债/权益/收入贷正。
  const naturalBalance = (x: GlTrialBalance["items"][number]) =>
    x.normal_balance === "credit" ? x.credit - x.debit : x.debit - x.credit;

  return (
    <div className="space-y-3">
      <Card className="p-[var(--card-pad)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-1.5 text-sm font-medium">
              <Scale className="h-4 w-4 text-muted-foreground" />
              {t("gl.title")}
            </div>
            <div className="mt-1 text-xs text-muted-foreground">{t("gl.desc")}</div>
          </div>
          <div className="flex items-end gap-2">
            <div className="w-52">
              <label className={labelCls}>{t("gl.period")}</label>
              <select
                className={inputCls}
                value={periodId ?? ""}
                onChange={(e) =>
                  setPeriodId(e.target.value ? Number(e.target.value) : null)
                }
              >
                {periods.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.year}-{String(p.month).padStart(2, "0")} ·{" "}
                    {p.status === "closed" ? t("gl.closed") : t("gl.open")}
                  </option>
                ))}
              </select>
            </div>
            <Button size="sm" variant="outline" onClick={refresh} disabled={loading}>
              <RefreshCw className={cn("mr-1 h-3.5 w-3.5", loading && "animate-spin")} />
              {t("settings.refresh")}
            </Button>
          </div>
        </div>
        <div className="mt-3">
          <PillTabs
            value={tab}
            onChange={setTab}
            options={[
              { value: "entries", label: t("gl.tabEntries") },
              { value: "accounts", label: t("gl.tabAccounts") },
              { value: "periods", label: t("gl.tabPeriods") },
              { value: "trial", label: t("gl.tabTrial") },
            ]}
          />
        </div>
      </Card>

      {tab === "accounts" && (
        <Card className="p-[var(--card-pad)]">
          <div className="mb-3 flex flex-wrap items-end gap-2">
            <div className="w-24">
              <label className={labelCls}>{t("gl.code")}</label>
              <input
                className={inputCls}
                value={accountForm.code}
                onChange={(e) => setAccountForm({ ...accountForm, code: e.target.value })}
                placeholder="1001"
              />
            </div>
            <div className="w-44">
              <label className={labelCls}>{t("gl.name")}</label>
              <input
                className={inputCls}
                value={accountForm.name}
                onChange={(e) => setAccountForm({ ...accountForm, name: e.target.value })}
              />
            </div>
            <div className="w-36">
              <label className={labelCls}>{t("gl.type")}</label>
              <select
                className={inputCls}
                value={accountForm.type}
                onChange={(e) => setAccountForm({ ...accountForm, type: e.target.value })}
              >
                {ACCOUNT_TYPES.map((x) => (
                  <option key={x.value} value={x.value}>{t(x.key)}</option>
                ))}
              </select>
            </div>
            <Button
              size="sm"
              onClick={() => void doAccount()}
              disabled={!can("gl:write")}
            >
              <Plus className="mr-1 h-3.5 w-3.5" />
              {t("gl.addAccount")}
            </Button>
          </div>
          {accounts.length === 0 ? (
            <div className="py-2 text-xs text-muted-foreground">{t("gl.noAccounts")}</div>
          ) : (
            <div className="space-y-1.5">
              {accounts.map((a) => (
                <div
                  key={a.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/70 px-3 py-2"
                >
                  <div>
                    <span className="font-mono text-xs text-muted-foreground">{a.code}</span>
                    <span className="ml-2 text-sm">{a.name}</span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {t(
                      ACCOUNT_TYPES.find((x) => x.value === a.type)?.key ??
                        "gl.accountTypeAsset",
                    )}
                    {a.parent_id ? ` · ${accountName(a.parent_id)}` : ""}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {tab === "periods" && (
        <Card className="p-[var(--card-pad)]">
          <div className="mb-3 flex flex-wrap items-end gap-2">
            <div className="w-24">
              <label className={labelCls}>{t("gl.year")}</label>
              <input
                className={inputCls}
                inputMode="numeric"
                value={periodForm.year}
                onChange={(e) => setPeriodForm({ ...periodForm, year: e.target.value })}
              />
            </div>
            <div className="w-20">
              <label className={labelCls}>{t("gl.month")}</label>
              <input
                className={inputCls}
                inputMode="numeric"
                value={periodForm.month}
                onChange={(e) => setPeriodForm({ ...periodForm, month: e.target.value })}
              />
            </div>
            <Button
              size="sm"
              onClick={() => void doPeriod()}
              disabled={!can("gl:write")}
            >
              <Plus className="mr-1 h-3.5 w-3.5" />
              {t("gl.addPeriod")}
            </Button>
          </div>
          {periods.length === 0 ? (
            <div className="py-2 text-xs text-muted-foreground">{t("gl.noPeriods")}</div>
          ) : (
            <div className="space-y-1.5">
              {periods.map((p) => (
                <div
                  key={p.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/70 px-3 py-2"
                >
                  <div>
                    <span className="font-medium">{p.year}-{String(p.month).padStart(2, "0")}</span>
                    <span className="ml-2 text-xs text-muted-foreground">
                      {p.status === "closed" ? t("gl.closed") : t("gl.open")} ·{" "}
                      {p.posted_entries ?? 0} / {p.draft_entries ?? 0}
                    </span>
                  </div>
                  {p.status === "open" && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!canClose}
                      onClick={() =>
                        setConfirm({
                          kind: "period",
                          id: p.id,
                          label: `${p.year}-${String(p.month).padStart(2, "0")}`,
                        })
                      }
                    >
                      {t("gl.close")}
                    </Button>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {tab === "entries" && (
        <>
          <Card className="p-[var(--card-pad)]">
            <div className="mb-2 flex items-center gap-1.5 text-sm font-medium">
              <BookOpenCheck className="h-4 w-4 text-muted-foreground" />
              {t("gl.newEntry")}
            </div>
            {!canWrite && (
              <div className="mb-2 rounded-lg border border-border/70 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                {t("gl.periodLocked")}
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              <div className="w-40">
                <label className={labelCls}>{t("gl.date")}</label>
                <input
                  type="date"
                  className={inputCls}
                  value={entryForm.entry_date}
                  onChange={(e) =>
                    setEntryForm({ ...entryForm, entry_date: e.target.value })
                  }
                  disabled={!canWrite}
                />
              </div>
              <div className="min-w-[220px] flex-1">
                <label className={labelCls}>{t("gl.description")}</label>
                <input
                  className={inputCls}
                  value={entryForm.description}
                  onChange={(e) =>
                    setEntryForm({ ...entryForm, description: e.target.value })
                  }
                  disabled={!canWrite}
                />
              </div>
            </div>
            <div className="mt-3 space-y-1.5">
              {entryForm.lines.map((line, idx) => (
                <div key={idx} className="grid grid-cols-2 items-center gap-1.5 sm:flex sm:flex-wrap">
                  <div className="col-span-2 min-w-0 sm:min-w-[180px] sm:flex-1">
                    <select
                      className={miniInput}
                      value={line.account_id}
                      onChange={(e) => setLine(idx, { account_id: e.target.value })}
                      disabled={!canWrite}
                    >
                      <option value="">{t("gl.selectAccount")}</option>
                      {accounts.map((a) => (
                        <option key={a.id} value={a.id}>{a.code} {a.name}</option>
                      ))}
                    </select>
                  </div>
                  <input
                    className={cn(miniInput, "w-full sm:w-24")}
                    inputMode="decimal"
                    placeholder={t("gl.debit")}
                    value={line.debit}
                    onChange={(e) => setLine(idx, { debit: e.target.value, credit: "" })}
                    disabled={!canWrite}
                  />
                  <input
                    className={cn(miniInput, "w-full sm:w-24")}
                    inputMode="decimal"
                    placeholder={t("gl.credit")}
                    value={line.credit}
                    onChange={(e) => setLine(idx, { credit: e.target.value, debit: "" })}
                    disabled={!canWrite}
                  />
                  <input
                    className={cn(miniInput, "col-span-2 w-full sm:min-w-[120px] sm:flex-1")}
                    placeholder={t("gl.memo")}
                    value={line.memo}
                    onChange={(e) => setLine(idx, { memo: e.target.value })}
                    disabled={!canWrite}
                  />
                  {entryForm.lines.length > 2 && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="col-span-2 justify-self-end"
                      onClick={() =>
                        setEntryForm((f) => ({
                          ...f,
                          lines: f.lines.filter((_, i) => i !== idx),
                        }))
                      }
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
              ))}
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  setEntryForm((f) => ({
                    ...f,
                    lines: [...f.lines, { account_id: "", debit: "", credit: "", memo: "" }],
                  }))
                }
                disabled={!canWrite}
              >
                <Plus className="mr-1 h-3.5 w-3.5" />
                {t("gl.addLine")}
              </Button>
              <Button size="sm" onClick={() => void doEntry()} disabled={!canWrite}>
                {t("gl.saveDraft")}
              </Button>
            </div>
          </Card>

          <Card className="p-[var(--card-pad)]">
            <div className="mb-2 text-sm font-medium">{t("gl.entries")}</div>
            {entries.length === 0 ? (
              <div className="py-2 text-xs text-muted-foreground">{t("gl.noEntries")}</div>
            ) : (
              <div className="space-y-1.5">
                {entries.map((e) => (
                  <div
                    key={e.id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/70 px-3 py-2"
                  >
                    <div className="min-w-0">
                      <div className="font-mono text-xs text-muted-foreground">{e.entry_no}</div>
                      <div className="text-sm">
                        {e.entry_date} · {e.description || t("gl.noDescription")}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {t("gl.debit")} {fmtMoney(e.debit ?? 0)} · {t("gl.credit")}{" "}
                        {fmtMoney(e.credit ?? 0)}
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span
                        className={cn(
                          "rounded-full border px-2 py-0.5 text-[11px]",
                          e.status === "posted"
                            ? "border-emerald-500/40 text-emerald-700"
                            : "border-amber-500/40 text-amber-700",
                        )}
                      >
                        {e.status === "posted" ? t("gl.posted") : t("gl.draft")}
                      </span>
                      {e.status === "draft" && (
                        <>
                          <Button size="sm" onClick={() => void doPost(e.id)} disabled={!canPost}>
                            {t("gl.post")}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={!can("gl:write")}
                            onClick={() =>
                              setConfirm({
                                kind: "entry",
                                id: e.id,
                                label: e.entry_no,
                                action: "delete",
                              })
                            }
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </>
                      )}
                      {e.status === "posted" && e.source !== "reversal" && (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={!canPost}
                          onClick={() =>
                            setConfirm({
                              kind: "entry",
                              id: e.id,
                              label: e.entry_no,
                              action: "reverse",
                            })
                          }
                        >
                          <RotateCcw className="mr-1 h-3.5 w-3.5" />
                          {t("gl.reverse")}
                        </Button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </>
      )}

      {tab === "trial" && (
        <Card className="p-[var(--card-pad)]">
          <div className="mb-2 flex items-center justify-between gap-2">
            <div className="flex items-center gap-1.5 text-sm font-medium">
              <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
              {t("gl.trialBalance")}
            </div>
            {trial && (
              <span
                className={cn(
                  "rounded-full border px-2 py-0.5 text-[11px]",
                  trial.balanced
                    ? "border-emerald-500/40 text-emerald-700"
                    : "border-red-500/40 text-red-700",
                )}
              >
                {trial.balanced ? t("gl.balanced") : t("gl.imbalanced")}
              </span>
            )}
          </div>
          {!trial || trial.items.length === 0 ? (
            <div className="py-2 text-xs text-muted-foreground">{t("gl.noTrial")}</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/70 text-left text-xs text-muted-foreground">
                    <th className="py-1.5 pr-2">{t("gl.code")}</th>
                    <th className="py-1.5 pr-2">{t("gl.name")}</th>
                    <th className="py-1.5 pr-2 text-right">{t("gl.debit")}</th>
                    <th className="py-1.5 pr-2 text-right">{t("gl.credit")}</th>
                    <th className="py-1.5 text-right">{t("gl.balance")}</th>
                  </tr>
                </thead>
                <tbody>
                  {trial.items.map((x) => (
                    <tr key={x.account_id} className="border-b border-border/40">
                      <td className="py-1.5 pr-2 font-mono text-xs">{x.code}</td>
                      <td className="py-1.5 pr-2">{x.name}</td>
                      <td className="py-1.5 pr-2 text-right tabular-nums">{fmtMoney(x.debit)}</td>
                      <td className="py-1.5 pr-2 text-right tabular-nums">{fmtMoney(x.credit)}</td>
                      <td className="py-1.5 text-right tabular-nums">{fmtMoney(naturalBalance(x))}</td>
                    </tr>
                  ))}
                  <tr className="font-medium">
                    <td className="py-2" colSpan={2}>{t("gl.total")}</td>
                    <td className="py-2 pr-2 text-right tabular-nums">{fmtMoney(trial.total_debit)}</td>
                    <td className="py-2 pr-2 text-right tabular-nums">{fmtMoney(trial.total_credit)}</td>
                    <td />
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      <ConfirmDialog
        open={!!confirm}
        onOpenChange={(open) => {
          if (!open) setConfirm(null);
        }}
        title={
          confirm?.kind === "period"
            ? t("gl.confirmClose")
            : confirm?.action === "reverse"
              ? t("gl.confirmReverse")
              : t("gl.confirmDelete")
        }
        description={confirm?.label}
        danger={confirm?.kind === "entry" && confirm.action === "delete"}
        onConfirm={() => void doConfirm()}
      />
    </div>
  );
}

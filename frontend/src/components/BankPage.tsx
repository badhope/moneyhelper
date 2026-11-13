import { useCallback, useEffect, useMemo, useState } from "react";
import { Banknote, Landmark, Link2, Plus, RefreshCw, Unlink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { PillTabs } from "@/components/ui/pill-tabs";
import {
  closeBankReconciliation,
  createBankReconciliation,
  createBankTransaction,
  createPayment,
  getBankSummary,
  importBankCsv,
  listBankReconciliations,
  listBankTransactions,
  listExpenseClaims,
  listGlAccounts,
  listGlPeriods,
  listPayments,
  matchBankTransaction,
  unmatchBankTransaction,
  type BankReconciliation,
  type BankSummary,
  type BankTransaction,
  type ExpenseClaim,
  type GlAccount,
  type GlPeriod,
  type Payment,
} from "@/lib/api";
import { fmtDate, fmtMoney } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { useCapabilities } from "@/lib/use-capabilities";
import { cn } from "@/lib/utils";

const inputCls =
  "w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring";
const labelCls = "block text-xs text-muted-foreground mb-1";

/** 付款与银行流水：登记付款、导入流水、匹配/取消匹配、对账汇总。 */
export function BankPage() {
  const { t } = useI18n();
  const { toast } = useToast();
  const { can } = useCapabilities();
  const [tab, setTab] = useState<"payments" | "bank" | "reconcile">("payments");
  const [payments, setPayments] = useState<Payment[]>([]);
  const [transactions, setTransactions] = useState<BankTransaction[]>([]);
  const [claims, setClaims] = useState<ExpenseClaim[]>([]);
  const [accounts, setAccounts] = useState<GlAccount[]>([]);
  const [periods, setPeriods] = useState<GlPeriod[]>([]);
  const [recons, setRecons] = useState<BankReconciliation[]>([]);
  const [summary, setSummary] = useState<BankSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const [payForm, setPayForm] = useState({
    claim_id: "",
    bank_account_id: "",
    note: "",
  });
  const [txnForm, setTxnForm] = useState({
    bank_account_id: "",
    txn_date: "",
    direction: "out",
    amount: "",
    counterparty: "",
    memo: "",
    bank_ref: "",
  });
  const [csvText, setCsvText] = useState("");
  const [matchChoice, setMatchChoice] = useState<Record<number, string>>({});
  const [reconForm, setReconForm] = useState({
    bank_account_id: "",
    period_id: "",
    statement_balance: "",
    note: "",
  });

  const bankAccounts = useMemo(
    () => accounts.filter((a) => a.type === "asset" && a.is_active),
    [accounts],
  );
  const matchedPaymentIds = useMemo(
    () =>
      new Set(
        transactions
          .filter((x) => x.status === "matched" && x.payment_id)
          .map((x) => Number(x.payment_id)),
      ),
    [transactions],
  );
  const paidClaimIds = useMemo(
    () => new Set(payments.map((p) => Number(p.claim_id))),
    [payments],
  );
  const approvedUnpaid = useMemo(
    () =>
      claims.filter(
        (c) => c.status === "approved" && !paidClaimIds.has(Number(c.id)),
      ),
    [claims, paidClaimIds],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ps, ts, cs, as, sum] = await Promise.all([
        listPayments(),
        listBankTransactions(),
        listExpenseClaims(),
        listGlAccounts(),
        getBankSummary(),
      ]);
      setPayments(ps);
      setTransactions(ts);
      setClaims(cs);
      setAccounts(as);
      setSummary(sum);
      const [periodList, reconList] = await Promise.all([
        listGlPeriods(),
        listBankReconciliations(),
      ]);
      setPeriods(periodList);
      setRecons(reconList);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const doPayment = async () => {
    if (!payForm.claim_id || !payForm.bank_account_id) return;
    try {
      await createPayment({
        claim_id: Number(payForm.claim_id),
        bank_account_id: Number(payForm.bank_account_id),
        note: payForm.note,
      });
      setPayForm({ claim_id: "", bank_account_id: payForm.bank_account_id, note: "" });
      toast(t("bank.created"), "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doTxn = async () => {
    if (!txnForm.bank_account_id || !txnForm.amount || !txnForm.txn_date) return;
    try {
      await createBankTransaction({
        bank_account_id: Number(txnForm.bank_account_id),
        txn_date: txnForm.txn_date,
        direction: txnForm.direction,
        amount: Number(txnForm.amount),
        counterparty: txnForm.counterparty,
        memo: txnForm.memo,
        bank_ref: txnForm.bank_ref,
      });
      setTxnForm({ ...txnForm, amount: "", counterparty: "", memo: "", bank_ref: "" });
      toast(t("bank.created"), "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doImport = async () => {
    if (!txnForm.bank_account_id || !csvText.trim()) return;
    try {
      const r = await importBankCsv({
        bank_account_id: Number(txnForm.bank_account_id),
        csv: csvText,
      });
      setCsvText("");
      toast(`${t("bank.imported")} ${r.imported}`, "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doMatch = async (txnId: number) => {
    const paymentId = Number(matchChoice[txnId] || 0);
    if (!paymentId) return;
    try {
      await matchBankTransaction(txnId, paymentId);
      toast(t("bank.matchedMsg"), "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doUnmatch = async (txnId: number) => {
    try {
      await unmatchBankTransaction(txnId);
      toast(t("bank.unmatchedMsg"), "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doCreateRecon = async () => {
    if (
      !reconForm.bank_account_id ||
      !reconForm.period_id ||
      !reconForm.statement_balance
    ) {
      return;
    }
    try {
      await createBankReconciliation({
        bank_account_id: Number(reconForm.bank_account_id),
        period_id: Number(reconForm.period_id),
        statement_balance: Number(reconForm.statement_balance),
        note: reconForm.note,
      });
      setReconForm({ ...reconForm, statement_balance: "", note: "" });
      toast(t("bank.reconCreated"), "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doCloseRecon = async (id: number) => {
    try {
      await closeBankReconciliation(id);
      toast(t("bank.reconClosed"), "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const eligiblePayments = (txn: BankTransaction) =>
    payments.filter(
      (p) =>
        !matchedPaymentIds.has(p.id) &&
        Number(p.bank_account_id) === Number(txn.bank_account_id) &&
        Number(p.amount_cents) === Number(txn.amount_cents),
    );

  return (
    <div className="space-y-3">
      <Card className="p-[var(--card-pad)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-1.5 text-sm font-medium">
              <Landmark className="h-4 w-4 text-muted-foreground" />
              {t("bank.title")}
            </div>
            <div className="mt-1 text-xs text-muted-foreground">{t("bank.desc")}</div>
          </div>
          <Button size="sm" variant="outline" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={cn("mr-1 h-3.5 w-3.5", loading && "animate-spin")} />
            {t("settings.refresh")}
          </Button>
        </div>
        {summary && (
          <div className="mt-3 grid grid-cols-2 gap-2 @sm:grid-cols-4">
            <div className="rounded-lg border border-border/70 px-3 py-2">
              <div className="text-[11px] text-muted-foreground">{t("bank.paymentsTotal")}</div>
              <div className="text-sm font-medium">{fmtMoney(summary.payments_total)}</div>
              <div className="text-[11px] text-muted-foreground">
                {summary.payments_count} {t("bank.paymentsCount")}
              </div>
            </div>
            <div className="rounded-lg border border-border/70 px-3 py-2">
              <div className="text-[11px] text-muted-foreground">{t("bank.bankOut")}</div>
              <div className="text-sm font-medium">{fmtMoney(summary.bank_out_total)}</div>
            </div>
            <div className="rounded-lg border border-border/70 px-3 py-2">
              <div className="text-[11px] text-muted-foreground">{t("bank.bankIn")}</div>
              <div className="text-sm font-medium">{fmtMoney(summary.bank_in_total)}</div>
            </div>
            <div className="rounded-lg border border-border/70 px-3 py-2">
              <div className="text-[11px] text-muted-foreground">{t("bank.unmatched")}</div>
              <div className="text-sm font-medium">
                {summary.unmatched_count} · {fmtMoney(summary.unmatched_out_total)}
              </div>
              <div
                className={cn(
                  "text-[11px]",
                  summary.balanced ? "text-emerald-700" : "text-amber-700",
                )}
              >
                {summary.balanced ? t("bank.balanced") : t("bank.notBalanced")}
              </div>
            </div>
          </div>
        )}
        <div className="mt-3">
          <PillTabs
            value={tab}
            onChange={setTab}
            options={[
              { value: "payments", label: t("bank.tabPayments") },
              { value: "bank", label: t("bank.tabBank") },
              { value: "reconcile", label: t("bank.tabReconcile") },
            ]}
          />
        </div>
      </Card>

      {tab === "payments" && (
        <>
          <Card className="p-[var(--card-pad)]">
            <div className="mb-2 flex items-center gap-1.5 text-sm font-medium">
              <Banknote className="h-4 w-4 text-muted-foreground" />
              {t("bank.newPayment")}
            </div>
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-[240px] flex-1">
                <label className={labelCls}>{t("bank.approvedClaim")}</label>
                <select
                  className={inputCls}
                  value={payForm.claim_id}
                  onChange={(e) => setPayForm({ ...payForm, claim_id: e.target.value })}
                >
                  <option value="">{t("bank.noApprovedClaims")}</option>
                  {approvedUnpaid.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.claim_no} · {c.title} · {fmtMoney(c.amount)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="w-52">
                <label className={labelCls}>{t("bank.paymentAccount")}</label>
                <select
                  className={inputCls}
                  value={payForm.bank_account_id}
                  onChange={(e) =>
                    setPayForm({ ...payForm, bank_account_id: e.target.value })
                  }
                >
                  <option value="">{t("gl.selectAccount")}</option>
                  {bankAccounts.map((a) => (
                    <option key={a.id} value={a.id}>{a.code} {a.name}</option>
                  ))}
                </select>
              </div>
              <div className="min-w-[160px] flex-1">
                <label className={labelCls}>{t("bank.note")}</label>
                <input
                  className={inputCls}
                  value={payForm.note}
                  onChange={(e) => setPayForm({ ...payForm, note: e.target.value })}
                />
              </div>
              <Button
                size="sm"
                onClick={() => void doPayment()}
                disabled={!can("payment:create")}
              >
                <Plus className="mr-1 h-3.5 w-3.5" />
                {t("bank.createPayment")}
              </Button>
            </div>
            {approvedUnpaid.length === 0 && (
              <div className="mt-2 text-xs text-muted-foreground">
                {t("bank.noApprovedClaims")}
              </div>
            )}
          </Card>

          <Card className="p-[var(--card-pad)]">
            <div className="mb-2 text-sm font-medium">{t("bank.payments")}</div>
            {payments.length === 0 ? (
              <div className="py-2 text-xs text-muted-foreground">{t("bank.noPayments")}</div>
            ) : (
              <div className="space-y-1.5">
                {payments.map((p) => (
                  <div
                    key={p.id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/70 px-3 py-2"
                  >
                    <div>
                      <div className="font-mono text-xs text-muted-foreground">{p.payment_no}</div>
                      <div className="text-sm">
                        {p.payable_id
                          ? `${p.payable_no} · ${p.payee}`
                          : `${p.claim_no} · ${p.claim_title || t("org.none")}`}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {p.bank_account_code} {p.bank_account_name} · {p.payee}
                        {p.gl_entry_no
                          ? ` · ${t("expenses.voucher")} ${p.gl_entry_no}`
                          : ""}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-sm font-medium">{fmtMoney(p.amount)}</div>
                      <div className="text-[11px] text-muted-foreground">
                        {t("bank.paidAt")} {fmtDate(p.paid_at)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </>
      )}

      {tab === "bank" && (
        <>
          <Card className="p-[var(--card-pad)]">
            <div className="mb-2 text-sm font-medium">{t("bank.newTxn")}</div>
            <div className="flex flex-wrap items-end gap-2">
              <div className="w-44">
                <label className={labelCls}>{t("bank.bankAccount")}</label>
                <select
                  className={inputCls}
                  value={txnForm.bank_account_id}
                  onChange={(e) =>
                    setTxnForm({ ...txnForm, bank_account_id: e.target.value })
                  }
                >
                  <option value="">{t("gl.selectAccount")}</option>
                  {bankAccounts.map((a) => (
                    <option key={a.id} value={a.id}>{a.code} {a.name}</option>
                  ))}
                </select>
              </div>
              <div className="w-36">
                <label className={labelCls}>{t("gl.date")}</label>
                <input
                  type="date"
                  className={inputCls}
                  value={txnForm.txn_date}
                  onChange={(e) => setTxnForm({ ...txnForm, txn_date: e.target.value })}
                />
              </div>
              <div className="w-24">
                <label className={labelCls}>{t("bank.direction")}</label>
                <select
                  className={inputCls}
                  value={txnForm.direction}
                  onChange={(e) => setTxnForm({ ...txnForm, direction: e.target.value })}
                >
                  <option value="out">{t("bank.out")}</option>
                  <option value="in">{t("bank.in")}</option>
                </select>
              </div>
              <div className="w-28">
                <label className={labelCls}>{t("gl.amount")}</label>
                <input
                  className={inputCls}
                  inputMode="decimal"
                  value={txnForm.amount}
                  onChange={(e) => setTxnForm({ ...txnForm, amount: e.target.value })}
                />
              </div>
              <div className="w-36">
                <label className={labelCls}>{t("bank.counterparty")}</label>
                <input
                  className={inputCls}
                  value={txnForm.counterparty}
                  onChange={(e) =>
                    setTxnForm({ ...txnForm, counterparty: e.target.value })
                  }
                />
              </div>
              <div className="min-w-[140px] flex-1">
                <label className={labelCls}>{t("gl.memo")}</label>
                <input
                  className={inputCls}
                  value={txnForm.memo}
                  onChange={(e) => setTxnForm({ ...txnForm, memo: e.target.value })}
                />
              </div>
              <Button
                size="sm"
                onClick={() => void doTxn()}
                disabled={!can("bank:write")}
              >
                <Plus className="mr-1 h-3.5 w-3.5" />
                {t("bank.addTxn")}
              </Button>
            </div>
            <div className="mt-3">
              <label className={labelCls}>{t("bank.importCsv")}</label>
              <textarea
                className={cn(inputCls, "min-h-20 font-mono text-xs")}
                value={csvText}
                onChange={(e) => setCsvText(e.target.value)}
                placeholder={t("bank.csvHint")}
              />
              <div className="mt-1 flex justify-end">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void doImport()}
                  disabled={!can("bank:write")}
                >
                  {t("bank.import")}
                </Button>
              </div>
            </div>
          </Card>

          <Card className="p-[var(--card-pad)]">
            <div className="mb-2 text-sm font-medium">{t("bank.transactions")}</div>
            {transactions.length === 0 ? (
              <div className="py-2 text-xs text-muted-foreground">
                {t("bank.noTransactions")}
              </div>
            ) : (
              <div className="space-y-1.5">
                {transactions.map((x) => {
                  const eligible = x.status === "unmatched" && x.direction === "out"
                    ? eligiblePayments(x)
                    : [];
                  return (
                    <div
                      key={x.id}
                      className="rounded-lg border border-border/70 px-3 py-2"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <div className="text-sm">
                            {x.txn_date} · {x.direction === "out" ? t("bank.out") : t("bank.in")}{" "}
                            · {fmtMoney(x.amount)}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {x.bank_account_code} {x.bank_account_name} ·{" "}
                            {x.counterparty || t("org.none")} · {x.memo || t("org.none")}
                            {x.payment_no ? ` · ${x.payment_no}` : ""}
                          </div>
                        </div>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span
                            className={cn(
                              "rounded-full border px-2 py-0.5 text-[11px]",
                              x.status === "matched"
                                ? "border-emerald-500/40 text-emerald-700"
                                : "border-amber-500/40 text-amber-700",
                            )}
                          >
                            {x.status === "matched" ? t("bank.matched") : t("bank.unmatched")}
                          </span>
                          {x.status === "unmatched" && x.direction === "out" && (
                            <>
                              <select
                                className="rounded-lg border border-input bg-background px-2 py-1 text-xs"
                                value={matchChoice[x.id] ?? ""}
                                onChange={(e) =>
                                  setMatchChoice({ ...matchChoice, [x.id]: e.target.value })
                                }
                              >
                                <option value="">
                                  {eligible.length ? t("bank.selectPayment") : t("bank.noEligiblePayment")}
                                </option>
                                {eligible.map((p) => (
                                  <option key={p.id} value={p.id}>
                                    {p.payment_no} · {fmtMoney(p.amount)}
                                  </option>
                                ))}
                              </select>
                              <Button
                                size="sm"
                                disabled={!matchChoice[x.id] || !can("bank:match")}
                                onClick={() => void doMatch(x.id)}
                              >
                                <Link2 className="mr-1 h-3.5 w-3.5" />
                                {t("bank.match")}
                              </Button>
                            </>
                          )}
                          {x.status === "matched" && (
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={!can("bank:match")}
                              onClick={() => void doUnmatch(x.id)}
                            >
                              <Unlink className="mr-1 h-3.5 w-3.5" />
                              {t("bank.unmatch")}
                            </Button>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
        </>
      )}

      {tab === "reconcile" && (
        <>
          <Card className="p-[var(--card-pad)]">
            <div className="mb-2 text-sm font-medium">{t("bank.newRecon")}</div>
            <div className="flex flex-wrap items-end gap-2">
              <div className="w-48">
                <label className={labelCls}>{t("bank.bankAccount")}</label>
                <select
                  className={inputCls}
                  value={reconForm.bank_account_id}
                  onChange={(e) =>
                    setReconForm({ ...reconForm, bank_account_id: e.target.value })
                  }
                >
                  <option value="">{t("gl.selectAccount")}</option>
                  {bankAccounts.map((a) => (
                    <option key={a.id} value={a.id}>{a.code} {a.name}</option>
                  ))}
                </select>
              </div>
              <div className="w-44">
                <label className={labelCls}>{t("bank.period")}</label>
                <select
                  className={inputCls}
                  value={reconForm.period_id}
                  onChange={(e) =>
                    setReconForm({ ...reconForm, period_id: e.target.value })
                  }
                >
                  <option value="">{t("bank.selectPeriod")}</option>
                  {periods.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.year}-{String(p.month).padStart(2, "0")} ·{" "}
                      {p.status === "closed" ? t("gl.closed") : t("gl.open")}
                    </option>
                  ))}
                </select>
              </div>
              <div className="w-40">
                <label className={labelCls}>{t("bank.statementBalance")}</label>
                <input
                  className={inputCls}
                  inputMode="decimal"
                  value={reconForm.statement_balance}
                  onChange={(e) =>
                    setReconForm({ ...reconForm, statement_balance: e.target.value })
                  }
                />
              </div>
              <div className="min-w-[180px] flex-1">
                <label className={labelCls}>{t("bank.note")}</label>
                <input
                  className={inputCls}
                  value={reconForm.note}
                  onChange={(e) => setReconForm({ ...reconForm, note: e.target.value })}
                />
              </div>
              <Button
                size="sm"
                onClick={() => void doCreateRecon()}
                disabled={!can("reconciliation:write")}
              >
                <Plus className="mr-1 h-3.5 w-3.5" />
                {t("bank.createRecon")}
              </Button>
            </div>
            <div className="mt-2 text-[11.5px] text-muted-foreground">
              {t("bank.reconHint")}
            </div>
          </Card>

          <Card className="p-[var(--card-pad)]">
            <div className="mb-2 text-sm font-medium">{t("bank.reconciliations")}</div>
            {recons.length === 0 ? (
              <div className="py-2 text-xs text-muted-foreground">{t("bank.noRecon")}</div>
            ) : (
              <div className="space-y-1.5">
                {recons.map((r) => (
                  <div
                    key={r.id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/70 px-3 py-2"
                  >
                    <div>
                      <div className="text-sm">
                        {r.bank_account_code} {r.bank_account_name} · {r.year}-
                        {String(r.month).padStart(2, "0")}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {t("bank.statementBalance")} {fmtMoney(r.statement_balance)} ·{" "}
                        {t("bank.bookBalance")} {fmtMoney(r.book_balance)} ·{" "}
                        {t("bank.difference")} {fmtMoney(r.difference)}
                      </div>
                      {r.note ? (
                        <div className="text-xs text-muted-foreground">{r.note}</div>
                      ) : null}
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "rounded-full border px-2 py-0.5 text-[11px]",
                          r.status === "closed"
                            ? "border-emerald-500/40 text-emerald-700"
                            : "border-amber-500/40 text-amber-700",
                        )}
                      >
                        {r.status === "closed" ? t("bank.closed") : t("bank.open")}
                      </span>
                      {r.status === "open" && (
                        <Button
                          size="sm"
                          disabled={!can("reconciliation:sign")}
                          onClick={() => void doCloseRecon(r.id)}
                        >
                          {t("bank.closeRecon")}
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
    </div>
  );
}

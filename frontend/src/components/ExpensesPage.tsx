import { useCallback, useEffect, useMemo, useState } from "react";
import { ClipboardList, Plus, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  approveExpenseClaim,
  createExpenseClaim,
  getMyCapabilities,
  listExpenseClaims,
  listGlAccounts,
  rejectExpenseClaim,
  submitExpenseClaim,
  type ExpenseClaim,
  type GlAccount,
} from "@/lib/api";
import { fmtMoney } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { cn } from "@/lib/utils";

const inputCls =
  "w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring";
const labelCls = "block text-xs text-muted-foreground mb-1";

const STATUS_KEYS: Record<string, string> = {
  draft: "expenses.statusDraft",
  submitted: "expenses.statusSubmitted",
  approving: "expenses.statusApproving",
  approved: "expenses.statusApproved",
  rejected: "expenses.statusRejected",
};

/** 报销单：草稿 → 提交 → 审核 → 凭证草稿。 */
export function ExpensesPage() {
  const { t } = useI18n();
  const { toast } = useToast();
  const [claims, setClaims] = useState<ExpenseClaim[]>([]);
  const [accounts, setAccounts] = useState<GlAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [perms, setPerms] = useState<string[]>([]);
  const [rejectId, setRejectId] = useState<number | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [form, setForm] = useState({
    title: "",
    amount: "",
    category: "",
    expense_account_id: "",
    credit_account_id: "",
    invoice_ref: "",
    attachment_name: "",
  });

  const expenseAccounts = useMemo(
    () => accounts.filter((a) => a.type === "expense" && a.is_active),
    [accounts],
  );
  const creditAccounts = useMemo(
    () => accounts.filter((a) => ["asset", "liability"].includes(a.type) && a.is_active),
    [accounts],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [cs, as] = await Promise.all([listExpenseClaims(), listGlAccounts()]);
      setClaims(cs);
      setAccounts(as);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  // 权限点来自后端字典（切片 7a）：只读角色不该看到建单入口，
  // 否则就是"按钮能点、点了 403"。
  // 取权限失败时按"没有写权限"处理（fail-closed），但不让整页加载失败。
  useEffect(() => {
    let alive = true;
    getMyCapabilities()
      .then((caps) => {
        if (alive) setPerms(caps.permissions ?? []);
      })
      .catch(() => {
        if (alive) setPerms([]);
      });
    return () => {
      alive = false;
    };
  }, []);

  const canCreate = perms.includes("expense:create");
  const canApprove = perms.includes("expense:approve");

  useEffect(() => {
    void load();
  }, [load]);

  const statusLabel = (s: string) => t(STATUS_KEYS[s] ?? "expenses.statusSubmitted");

  const doCreate = async () => {
    if (
      !form.title.trim() ||
      !form.amount ||
      !form.expense_account_id ||
      !form.credit_account_id
    ) {
      return;
    }
    try {
      await createExpenseClaim({
        title: form.title,
        amount: Number(form.amount),
        category: form.category,
        expense_account_id: Number(form.expense_account_id),
        credit_account_id: Number(form.credit_account_id),
        invoice_ref: form.invoice_ref,
        attachment_name: form.attachment_name,
      });
      setForm({
        title: "",
        amount: "",
        category: "",
        expense_account_id: form.expense_account_id,
        credit_account_id: form.credit_account_id,
        invoice_ref: "",
        attachment_name: "",
      });
      toast(t("expenses.created"), "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doSubmit = async (id: number) => {
    try {
      await submitExpenseClaim(id);
      toast(t("expenses.submitted"), "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doApprove = async (id: number) => {
    try {
      await approveExpenseClaim(id);
      toast(t("expenses.approved"), "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doReject = async (id: number) => {
    if (!rejectReason.trim()) {
      toast(t("expenses.reasonRequired"), "error");
      return;
    }
    try {
      await rejectExpenseClaim(id, rejectReason.trim());
      setRejectId(null);
      setRejectReason("");
      toast(t("expenses.rejected"), "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  return (
    <div className="space-y-3">
      <Card className="p-[var(--card-pad)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-1.5 text-sm font-medium">
              <ClipboardList className="h-4 w-4 text-muted-foreground" />
              {t("expenses.title")}
            </div>
            <div className="mt-1 text-xs text-muted-foreground">{t("expenses.desc")}</div>
            <div className="mt-1 text-[11.5px] text-muted-foreground">
              {t("expenses.selfApprovalHint")}
            </div>
            {!canCreate && (
              <div className="mt-1 text-[11.5px] text-muted-foreground">
                {t("expenses.readonly")}
              </div>
            )}
          </div>
          <Button size="sm" variant="outline" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={cn("mr-1 h-3.5 w-3.5", loading && "animate-spin")} />
            {t("settings.refresh")}
          </Button>
        </div>
      </Card>

      <Card className="p-[var(--card-pad)]">
        <div className="mb-2 text-sm font-medium">{t("expenses.new")}</div>
        {accounts.length === 0 && (
          <div className="mb-2 rounded-lg border border-border/70 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            {t("gl.noAccounts")}
          </div>
        )}
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[220px] flex-1">
            <label className={labelCls}>{t("expenses.titleLabel")}</label>
            <input
              className={inputCls}
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
            />
          </div>
          <div className="w-32">
            <label className={labelCls}>{t("expenses.amount")}</label>
            <input
              className={inputCls}
              inputMode="decimal"
              value={form.amount}
              onChange={(e) => setForm({ ...form, amount: e.target.value })}
            />
          </div>
          <div className="w-32">
            <label className={labelCls}>{t("expenses.category")}</label>
            <input
              className={inputCls}
              value={form.category}
              onChange={(e) => setForm({ ...form, category: e.target.value })}
            />
          </div>
        </div>
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <div className="w-52">
            <label className={labelCls}>{t("expenses.expenseAccount")}</label>
            <select
              className={inputCls}
              value={form.expense_account_id}
              onChange={(e) => setForm({ ...form, expense_account_id: e.target.value })}
            >
              <option value="">{t("gl.selectAccount")}</option>
              {expenseAccounts.map((a) => (
                <option key={a.id} value={a.id}>{a.code} {a.name}</option>
              ))}
            </select>
          </div>
          <div className="w-52">
            <label className={labelCls}>{t("expenses.creditAccount")}</label>
            <select
              className={inputCls}
              value={form.credit_account_id}
              onChange={(e) => setForm({ ...form, credit_account_id: e.target.value })}
            >
              <option value="">{t("gl.selectAccount")}</option>
              {creditAccounts.map((a) => (
                <option key={a.id} value={a.id}>{a.code} {a.name}</option>
              ))}
            </select>
          </div>
          <div className="min-w-[180px] flex-1">
            <label className={labelCls}>{t("expenses.invoiceRef")}</label>
            <input
              className={inputCls}
              value={form.invoice_ref}
              onChange={(e) => setForm({ ...form, invoice_ref: e.target.value })}
            />
          </div>
          <div className="min-w-[160px] flex-1">
            <label className={labelCls}>{t("expenses.attachment")}</label>
            <input
              className={inputCls}
              value={form.attachment_name}
              onChange={(e) => setForm({ ...form, attachment_name: e.target.value })}
              placeholder="invoice.pdf"
            />
          </div>
          <Button size="sm" onClick={() => void doCreate()} disabled={!canCreate}>
            <Plus className="mr-1 h-3.5 w-3.5" />
            {t("expenses.saveDraft")}
          </Button>
        </div>
      </Card>

      <Card className="p-[var(--card-pad)]">
        <div className="mb-2 text-sm font-medium">{t("expenses.list")}</div>
        {claims.length === 0 ? (
          <div className="py-2 text-xs text-muted-foreground">{t("expenses.noClaims")}</div>
        ) : (
          <div className="space-y-2">
            {claims.map((c) => (
              <div key={c.id} className="rounded-lg border border-border/70 px-3 py-2">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="font-mono text-xs text-muted-foreground">{c.claim_no}</div>
                    <div className="text-sm font-medium">{c.title}</div>
                    <div className="text-xs text-muted-foreground">
                      {t("expenses.applicant")}{" "}
                      {c.applicant_name ||
                        (c.applicant_user_id === 0
                          ? t("expenses.localApplicant")
                          : `#${c.applicant_user_id}`)}{" "}
                      · {fmtMoney(c.amount)} · {c.category || t("org.none")}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {c.expense_account_code} {c.expense_account_name} /{" "}
                      {c.credit_account_code} {c.credit_account_name}
                      {c.invoice_ref ? ` · ${c.invoice_ref}` : ""}
                    </div>
                    {c.gl_entry_no && (
                      <div className="mt-1 text-xs text-muted-foreground">
                        {t("expenses.voucher")} {c.gl_entry_no} ·{" "}
                        {c.gl_status === "posted" ? t("gl.posted") : t("gl.draft")}
                      </div>
                    )}
                    {c.status === "rejected" && c.rejected_reason && (
                      <div className="mt-1 text-xs text-red-600">{c.rejected_reason}</div>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span
                      className={cn(
                        "rounded-full border px-2 py-0.5 text-[11px]",
                        c.status === "approved"
                          ? "border-emerald-500/40 text-emerald-700"
                          : c.status === "rejected"
                            ? "border-red-500/40 text-red-700"
                            : "border-amber-500/40 text-amber-700",
                      )}
                    >
                      {statusLabel(c.status)}
                    </span>
                    {c.status === "draft" && canCreate && (
                      <Button size="sm" onClick={() => void doSubmit(c.id)}>
                        {t("expenses.submit")}
                      </Button>
                    )}
                    {c.status === "submitted" && canApprove && (
                      <>
                        <Button size="sm" onClick={() => void doApprove(c.id)}>
                          {t("expenses.approve")}
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => {
                            setRejectId(rejectId === c.id ? null : c.id);
                            setRejectReason("");
                          }}
                        >
                          {t("expenses.reject")}
                        </Button>
                      </>
                    )}
                  </div>
                </div>
                {rejectId === c.id && (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <input
                      className={cn(inputCls, "max-w-sm")}
                      value={rejectReason}
                      onChange={(e) => setRejectReason(e.target.value)}
                      placeholder={t("expenses.rejectReason")}
                    />
                    <Button size="sm" variant="destructive" onClick={() => void doReject(c.id)}>
                      {t("expenses.confirmReject")}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setRejectId(null)}>
                      {t("confirm.cancel")}
                    </Button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

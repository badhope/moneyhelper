import { useCallback, useEffect, useMemo, useState } from "react";
import { Boxes, Plus, RefreshCw, Truck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { PillTabs } from "@/components/ui/pill-tabs";
import {
  approvePayable,
  approvePurchaseOrder,
  createPayable,
  createPurchaseOrder,
  createVendor,
  listGlAccounts,
  listPayables,
  listPurchaseOrders,
  listVendors,
  payPayable,
  submitPayable,
  submitPurchaseOrder,
  type GlAccount,
  type Payable,
  type PurchaseOrder,
  type Vendor,
} from "@/lib/api";
import { fmtDay, fmtMoney } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { useCapabilities } from "@/lib/use-capabilities";
import { cn } from "@/lib/utils";

const inputCls =
  "w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring";
const labelCls = "block text-xs text-muted-foreground mb-1";

const STATUS_KEYS: Record<string, string> = {
  draft: "procurement.statusDraft",
  submitted: "procurement.statusSubmitted",
  approving: "procurement.statusApproving",
  approved: "procurement.statusApproved",
  paid: "procurement.statusPaid",
  cancelled: "procurement.statusCancelled",
};

const today = () => new Date().toISOString().slice(0, 10);

function StatusBadge({ status }: { status: string }) {
  const { t } = useI18n();
  return (
    <span
      className={cn(
        "rounded-full border px-2 py-0.5 text-[11px]",
        status === "paid" || status === "approved"
          ? "border-emerald-500/40 text-emerald-700"
          : status === "cancelled"
            ? "border-border text-muted-foreground"
            : "border-amber-500/40 text-amber-700",
      )}
    >
      {t(STATUS_KEYS[status] ?? "procurement.statusDraft")}
    </span>
  );
}

/** 采购与应付：供应商 → 采购单 → 应付单 → 付款。 */
export function ProcurementPage() {
  const { t } = useI18n();
  const { toast } = useToast();
  const { can } = useCapabilities();
  const [tab, setTab] = useState<"vendors" | "orders" | "payables">("payables");
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const [payables, setPayables] = useState<Payable[]>([]);
  const [accounts, setAccounts] = useState<GlAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [newVendorOpen, setNewVendorOpen] = useState(false);
  const [newOrderOpen, setNewOrderOpen] = useState(false);
  const [newPayableOpen, setNewPayableOpen] = useState(false);
  const [payingId, setPayingId] = useState<number | null>(null);
  const [payBank, setPayBank] = useState("");

  const [vendorForm, setVendorForm] = useState({
    code: "",
    name: "",
    tax_no: "",
    contact: "",
    phone: "",
  });
  const [orderForm, setOrderForm] = useState({
    vendor_id: "",
    order_date: today(),
    expected_date: "",
    amount: "",
    description: "",
  });
  const [payableForm, setPayableForm] = useState({
    vendor_id: "",
    po_id: "",
    invoice_no: "",
    invoice_date: today(),
    due_date: "",
    amount: "",
    tax: "",
    expense_account_id: "",
    payable_account_id: "",
  });

  const canWrite = can("procurement:write");
  const canApprove = can("procurement:approve");
  const canWritePayable = can("payable:write");
  const canApprovePayable = can("payable:approve");
  const canPay = can("payable:pay");

  const expenseAccounts = useMemo(
    () => accounts.filter((a) => ["expense", "asset"].includes(a.type) && a.is_active),
    [accounts],
  );
  const payableAccounts = useMemo(
    () => accounts.filter((a) => a.type === "liability" && a.is_active),
    [accounts],
  );
  const bankAccounts = useMemo(
    () => accounts.filter((a) => a.type === "asset" && a.is_active),
    [accounts],
  );
  const approvedOrders = useMemo(
    () => orders.filter((o) => o.status === "approved"),
    [orders],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [vs, os, ps, as] = await Promise.all([
        listVendors(),
        listPurchaseOrders(),
        listPayables(),
        listGlAccounts(),
      ]);
      setVendors(vs);
      setOrders(os);
      setPayables(ps);
      setAccounts(as);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const doVendor = async () => {
    if (!vendorForm.code.trim() || !vendorForm.name.trim()) return;
    try {
      await createVendor({
        code: vendorForm.code.trim(),
        name: vendorForm.name.trim(),
        tax_no: vendorForm.tax_no,
        contact: vendorForm.contact,
        phone: vendorForm.phone,
      });
      setVendorForm({ code: "", name: "", tax_no: "", contact: "", phone: "" });
      toast(t("procurement.vendorCreated"), "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doOrder = async () => {
    if (!orderForm.vendor_id || !orderForm.order_date || !orderForm.amount) return;
    try {
      await createPurchaseOrder({
        vendor_id: Number(orderForm.vendor_id),
        order_date: orderForm.order_date,
        expected_date: orderForm.expected_date,
        amount: Number(orderForm.amount),
        description: orderForm.description,
      });
      setOrderForm({ ...orderForm, amount: "", description: "" });
      toast(t("procurement.orderCreated"), "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doSubmitOrder = async (id: number) => {
    try {
      await submitPurchaseOrder(id);
      toast(t("procurement.orderSubmitted"), "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doApproveOrder = async (id: number) => {
    try {
      await approvePurchaseOrder(id);
      toast(t("procurement.orderApproved"), "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doPayable = async () => {
    if (
      !payableForm.vendor_id ||
      !payableForm.invoice_date ||
      !payableForm.amount ||
      !payableForm.expense_account_id ||
      !payableForm.payable_account_id
    ) {
      return;
    }
    try {
      await createPayable({
        vendor_id: Number(payableForm.vendor_id),
        po_id: payableForm.po_id ? Number(payableForm.po_id) : null,
        invoice_no: payableForm.invoice_no,
        invoice_date: payableForm.invoice_date,
        due_date: payableForm.due_date,
        amount: Number(payableForm.amount),
        tax: payableForm.tax ? Number(payableForm.tax) : 0,
        expense_account_id: Number(payableForm.expense_account_id),
        payable_account_id: Number(payableForm.payable_account_id),
      });
      setPayableForm({ ...payableForm, invoice_no: "", amount: "", tax: "" });
      toast(t("procurement.payableCreated"), "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doSubmitPayable = async (id: number) => {
    try {
      await submitPayable(id);
      toast(t("procurement.payableSubmitted"), "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doApprovePayable = async (id: number) => {
    try {
      await approvePayable(id);
      toast(t("procurement.payableApproved"), "ok");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const doPay = async (id: number) => {
    if (!payBank) return;
    try {
      await payPayable(id, { bank_account_id: Number(payBank) });
      setPayingId(null);
      setPayBank("");
      toast(t("procurement.paid"), "ok");
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
              <Boxes className="h-4 w-4 text-muted-foreground" />
              {t("procurement.title")}
            </div>
            <div className="mt-1 text-xs text-muted-foreground">{t("procurement.desc")}</div>
            {!canWrite && !canWritePayable && (
              <div className="mt-1 text-[11.5px] text-muted-foreground">
                {t("procurement.readonly")}
              </div>
            )}
          </div>
          <Button size="sm" variant="outline" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={cn("mr-1 h-3.5 w-3.5", loading && "animate-spin")} />
            {t("settings.refresh")}
          </Button>
        </div>
        <div className="mt-3">
          <PillTabs
            value={tab}
            onChange={setTab}
            options={[
              { value: "payables", label: t("procurement.payables") },
              { value: "orders", label: t("procurement.orders") },
              { value: "vendors", label: t("procurement.vendors") },
            ]}
          />
        </div>
      </Card>

      {tab === "vendors" && (
        <>
          <Card className="p-[var(--card-pad)]">
            <button
              type="button"
              onClick={() => setNewVendorOpen((v) => !v)}
              aria-expanded={newVendorOpen}
              className="flex w-full items-center justify-between text-sm font-medium"
            >
              <span>{t("procurement.newVendor")}</span>
              <span className="text-xs text-muted-foreground">
                {newVendorOpen ? t("confirm.cancel") : t("procurement.add")}
              </span>
            </button>
            {newVendorOpen && (
              <div className="mt-2 flex flex-wrap items-end gap-2">
                <div className="w-40">
                  <label className={labelCls} htmlFor="proc-vendorCode-1">{t("procurement.vendorCode")}</label>
                  <input id="proc-vendorCode-1"
                    className={inputCls}
                    value={vendorForm.code}
                    onChange={(e) => setVendorForm({ ...vendorForm, code: e.target.value })}
                  />
                </div>
                <div className="min-w-[200px] flex-1">
                  <label className={labelCls} htmlFor="proc-vendorName-2">{t("procurement.vendorName")}</label>
                  <input id="proc-vendorName-2"
                    className={inputCls}
                    value={vendorForm.name}
                    onChange={(e) => setVendorForm({ ...vendorForm, name: e.target.value })}
                  />
                </div>
                <div className="w-44">
                  <label className={labelCls} htmlFor="proc-taxNo-3">{t("procurement.taxNo")}</label>
                  <input id="proc-taxNo-3"
                    className={inputCls}
                    value={vendorForm.tax_no}
                    onChange={(e) => setVendorForm({ ...vendorForm, tax_no: e.target.value })}
                  />
                </div>
                <div className="w-32">
                  <label className={labelCls} htmlFor="proc-contact-4">{t("procurement.contact")}</label>
                  <input id="proc-contact-4"
                    className={inputCls}
                    value={vendorForm.contact}
                    onChange={(e) => setVendorForm({ ...vendorForm, contact: e.target.value })}
                  />
                </div>
                <div className="w-36">
                  <label className={labelCls} htmlFor="proc-phone-5">{t("procurement.phone")}</label>
                  <input id="proc-phone-5"
                    className={inputCls}
                    value={vendorForm.phone}
                    onChange={(e) => setVendorForm({ ...vendorForm, phone: e.target.value })}
                  />
                </div>
                <Button size="sm" onClick={() => void doVendor()} disabled={!canWrite}>
                  <Plus className="mr-1 h-3.5 w-3.5" />
                  {t("procurement.createVendor")}
                </Button>
              </div>
            )}
          </Card>
          <Card className="p-[var(--card-pad)]">
            <div className="mb-2 text-sm font-medium">{t("procurement.vendors")}</div>
            {vendors.length === 0 ? (
              <div className="py-2 text-xs text-muted-foreground">
                {t("procurement.noVendors")}
              </div>
            ) : (
              <div className="space-y-1.5">
                {vendors.map((v) => (
                  <div
                    key={v.id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/70 px-3 py-2"
                  >
                    <div>
                      <div className="font-mono text-xs text-muted-foreground">{v.code}</div>
                      <div className="text-sm font-medium">{v.name}</div>
                    </div>
                    <div className="text-right text-xs text-muted-foreground">
                      {v.contact || t("org.none")} · {v.phone || t("org.none")}
                      <div>{v.tax_no || t("org.none")}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </>
      )}

      {tab === "orders" && (
        <>
          <Card className="p-[var(--card-pad)]">
            <button
              type="button"
              onClick={() => setNewOrderOpen((v) => !v)}
              aria-expanded={newOrderOpen}
              className="flex w-full items-center justify-between text-sm font-medium"
            >
              <span>{t("procurement.newOrder")}</span>
              <span className="text-xs text-muted-foreground">
                {newOrderOpen ? t("confirm.cancel") : t("procurement.add")}
              </span>
            </button>
            {newOrderOpen && (
            <div className="mt-2 flex flex-wrap items-end gap-2">
              <div className="w-52">
                <label className={labelCls} htmlFor="proc-vendor-6">{t("procurement.vendor")}</label>
                <select id="proc-vendor-6"
                  className={inputCls}
                  value={orderForm.vendor_id}
                  onChange={(e) => setOrderForm({ ...orderForm, vendor_id: e.target.value })}
                >
                  <option value="">{t("procurement.selectVendor")}</option>
                  {vendors.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.code} {v.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="w-40">
                <label className={labelCls} htmlFor="proc-orderDate-7">{t("procurement.orderDate")}</label>
                <input id="proc-orderDate-7"
                  type="date"
                  className={inputCls}
                  value={orderForm.order_date}
                  onChange={(e) => setOrderForm({ ...orderForm, order_date: e.target.value })}
                />
              </div>
              <div className="w-40">
                <label className={labelCls} htmlFor="proc-expectedDate-8">{t("procurement.expectedDate")}</label>
                <input id="proc-expectedDate-8"
                  type="date"
                  className={inputCls}
                  value={orderForm.expected_date}
                  onChange={(e) =>
                    setOrderForm({ ...orderForm, expected_date: e.target.value })
                  }
                />
              </div>
              <div className="w-32">
                <label className={labelCls} htmlFor="proc-amount-9">{t("expenses.amount")}</label>
                <input id="proc-amount-9"
                  className={inputCls}
                  inputMode="decimal"
                  value={orderForm.amount}
                  onChange={(e) => setOrderForm({ ...orderForm, amount: e.target.value })}
                />
              </div>
              <div className="min-w-[200px] flex-1">
                <label className={labelCls} htmlFor="proc-description-10">{t("procurement.description")}</label>
                <input id="proc-description-10"
                  className={inputCls}
                  value={orderForm.description}
                  onChange={(e) =>
                    setOrderForm({ ...orderForm, description: e.target.value })
                  }
                />
              </div>
              <Button size="sm" onClick={() => void doOrder()} disabled={!canWrite}>
                <Plus className="mr-1 h-3.5 w-3.5" />
                {t("procurement.createOrder")}
              </Button>
            </div>
            )}
          </Card>
          <Card className="p-[var(--card-pad)]">
            <div className="mb-2 text-sm font-medium">{t("procurement.orders")}</div>
            {orders.length === 0 ? (
              <div className="py-2 text-xs text-muted-foreground">
                {t("procurement.noOrders")}
              </div>
            ) : (
              <div className="space-y-1.5">
                {orders.map((o) => (
                  <div
                    key={o.id}
                    className="flex flex-wrap items-start justify-between gap-2 rounded-lg border border-border/70 px-3 py-2"
                  >
                    <div className="min-w-0">
                      <div className="font-mono text-xs text-muted-foreground">{o.po_no}</div>
                      <div className="text-sm font-medium">
                        {o.vendor_name || t("org.none")} · {fmtMoney(o.amount)}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {fmtDay(o.order_date)}
                        {o.expected_date ? ` → ${fmtDay(o.expected_date)}` : ""}
                        {o.description ? ` · ${o.description}` : ""}
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <StatusBadge status={o.status} />
                      {o.status === "draft" && canWrite && (
                        <Button size="sm" onClick={() => void doSubmitOrder(o.id)}>
                          {t("expenses.submit")}
                        </Button>
                      )}
                      {o.status === "submitted" && canApprove && (
                        <Button size="sm" onClick={() => void doApproveOrder(o.id)}>
                          {t("expenses.approve")}
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

      {tab === "payables" && (
        <>
          <Card className="p-[var(--card-pad)]">
            <button
              type="button"
              onClick={() => setNewPayableOpen((v) => !v)}
              aria-expanded={newPayableOpen}
              className="flex w-full items-center justify-between text-sm font-medium"
            >
              <span className="flex items-center gap-1.5">
                <Truck className="h-4 w-4 text-muted-foreground" />
                {t("procurement.newPayable")}
              </span>
              <span className="text-xs text-muted-foreground">
                {newPayableOpen ? t("confirm.cancel") : t("procurement.add")}
              </span>
            </button>
            {newPayableOpen && (
            <>
            <div className="mt-2 flex flex-wrap items-end gap-2">
              <div className="w-48">
                <label className={labelCls} htmlFor="proc-vendor-11">{t("procurement.vendor")}</label>
                <select id="proc-vendor-11"
                  className={inputCls}
                  value={payableForm.vendor_id}
                  onChange={(e) =>
                    setPayableForm({ ...payableForm, vendor_id: e.target.value, po_id: "" })
                  }
                >
                  <option value="">{t("procurement.selectVendor")}</option>
                  {vendors.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.code} {v.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="w-48">
                <label className={labelCls} htmlFor="proc-po-12">{t("procurement.po")}</label>
                <select id="proc-po-12"
                  className={inputCls}
                  value={payableForm.po_id}
                  onChange={(e) => setPayableForm({ ...payableForm, po_id: e.target.value })}
                >
                  <option value="">{t("procurement.noPo")}</option>
                  {approvedOrders
                    .filter(
                      (o) =>
                        !payableForm.vendor_id ||
                        Number(o.vendor_id) === Number(payableForm.vendor_id),
                    )
                    .map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.po_no} · {fmtMoney(o.amount)}
                      </option>
                    ))}
                </select>
              </div>
              <div className="w-36">
                <label className={labelCls} htmlFor="proc-invoiceNo-13">{t("procurement.invoiceNo")}</label>
                <input id="proc-invoiceNo-13"
                  className={inputCls}
                  value={payableForm.invoice_no}
                  onChange={(e) =>
                    setPayableForm({ ...payableForm, invoice_no: e.target.value })
                  }
                />
              </div>
              <div className="w-40">
                <label className={labelCls} htmlFor="proc-invoiceDate-14">{t("procurement.invoiceDate")}</label>
                <input id="proc-invoiceDate-14"
                  type="date"
                  className={inputCls}
                  value={payableForm.invoice_date}
                  onChange={(e) =>
                    setPayableForm({ ...payableForm, invoice_date: e.target.value })
                  }
                />
              </div>
              <div className="w-40">
                <label className={labelCls} htmlFor="proc-dueDate-15">{t("procurement.dueDate")}</label>
                <input id="proc-dueDate-15"
                  type="date"
                  className={inputCls}
                  value={payableForm.due_date}
                  onChange={(e) =>
                    setPayableForm({ ...payableForm, due_date: e.target.value })
                  }
                />
              </div>
            </div>
            <div className="mt-2 flex flex-wrap items-end gap-2">
              <div className="w-32">
                <label className={labelCls} htmlFor="proc-amount-16">{t("expenses.amount")}</label>
                <input id="proc-amount-16"
                  className={inputCls}
                  inputMode="decimal"
                  value={payableForm.amount}
                  onChange={(e) =>
                    setPayableForm({ ...payableForm, amount: e.target.value })
                  }
                />
              </div>
              <div className="w-32">
                <label className={labelCls} htmlFor="proc-tax-17">{t("procurement.tax")}</label>
                <input id="proc-tax-17"
                  className={inputCls}
                  inputMode="decimal"
                  value={payableForm.tax}
                  onChange={(e) => setPayableForm({ ...payableForm, tax: e.target.value })}
                />
              </div>
              <div className="w-52">
                <label className={labelCls} htmlFor="proc-expenseAccount-18">{t("procurement.expenseAccount")}</label>
                <select id="proc-expenseAccount-18"
                  className={inputCls}
                  value={payableForm.expense_account_id}
                  onChange={(e) =>
                    setPayableForm({ ...payableForm, expense_account_id: e.target.value })
                  }
                >
                  <option value="">{t("gl.selectAccount")}</option>
                  {expenseAccounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.code} {a.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="w-52">
                <label className={labelCls} htmlFor="proc-payableAccount-19">{t("procurement.payableAccount")}</label>
                <select id="proc-payableAccount-19"
                  className={inputCls}
                  value={payableForm.payable_account_id}
                  onChange={(e) =>
                    setPayableForm({ ...payableForm, payable_account_id: e.target.value })
                  }
                >
                  <option value="">{t("gl.selectAccount")}</option>
                  {payableAccounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.code} {a.name}
                    </option>
                  ))}
                </select>
              </div>
              <Button size="sm" onClick={() => void doPayable()} disabled={!canWritePayable}>
                <Plus className="mr-1 h-3.5 w-3.5" />
                {t("procurement.createPayable")}
              </Button>
            </div>
            </>
            )}
          </Card>

          <Card className="p-[var(--card-pad)]">
            <div className="mb-2 text-sm font-medium">{t("procurement.payables")}</div>
            {payables.length === 0 ? (
              <div className="py-2 text-xs text-muted-foreground">
                {t("procurement.noPayables")}
              </div>
            ) : (
              <div className="space-y-1.5">
                {payables.map((p) => (
                  <div
                    key={p.id}
                    className="rounded-lg border border-border/70 px-3 py-2"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="font-mono text-xs text-muted-foreground">
                          {p.payable_no}
                          {p.po_no ? ` · ${p.po_no}` : ""}
                        </div>
                        <div className="text-sm font-medium">
                          {p.vendor_name || t("org.none")} · {fmtMoney(p.amount)}
                          {p.tax > 0 ? ` · ${t("procurement.tax")} ${fmtMoney(p.tax)}` : ""}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {t("procurement.invoiceNo")} {p.invoice_no || t("org.none")} ·{" "}
                          {fmtDay(p.invoice_date)}
                          {p.due_date ? ` → ${fmtDay(p.due_date)}` : ""}
                        </div>
                        {p.gl_entry_no && (
                          <div className="mt-1 text-xs text-muted-foreground">
                            {t("expenses.voucher")} {p.gl_entry_no} ·{" "}
                            {p.gl_status === "posted" ? t("gl.posted") : t("gl.draft")}
                          </div>
                        )}
                        {p.payment_no && (
                          <div className="mt-1 text-xs text-muted-foreground">
                            {t("procurement.pay")} {p.payment_no}
                          </div>
                        )}
                      </div>
                      <div className="flex flex-wrap items-center gap-1.5">
                        <StatusBadge status={p.status} />
                        {p.status === "draft" && canWritePayable && (
                          <Button size="sm" onClick={() => void doSubmitPayable(p.id)}>
                            {t("expenses.submit")}
                          </Button>
                        )}
                        {p.status === "submitted" && canApprovePayable && (
                          <Button size="sm" onClick={() => void doApprovePayable(p.id)}>
                            {t("expenses.approve")}
                          </Button>
                        )}
                        {p.status === "approved" && canPay && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => {
                              setPayingId(payingId === p.id ? null : p.id);
                              setPayBank("");
                            }}
                          >
                            {t("procurement.pay")}
                          </Button>
                        )}
                      </div>
                    </div>
                    {payingId === p.id && (
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <select
                          className={cn(inputCls, "max-w-xs")}
                          value={payBank}
                          onChange={(e) => setPayBank(e.target.value)}
                        >
                          <option value="">{t("procurement.paymentAccount")}</option>
                          {bankAccounts.map((a) => (
                            <option key={a.id} value={a.id}>
                              {a.code} {a.name}
                            </option>
                          ))}
                        </select>
                        <Button
                          size="sm"
                          onClick={() => void doPay(p.id)}
                          disabled={!payBank}
                        >
                          {t("procurement.payConfirm")}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setPayingId(null)}>
                          {t("confirm.cancel")}
                        </Button>
                      </div>
                    )}
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

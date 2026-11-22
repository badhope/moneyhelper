import { useState } from "react";
import { Plus, Trash2, Sparkles, FileUp, Landmark, Repeat, Search, Target, Pencil, Combine } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { FieldError } from "@/components/ui/field-error";
import { ConfirmDialog } from "@/components/ui/confirm";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { Table } from "@/components/ui/table";
import { api, deleteGoal } from "@/lib/api";
import { useMutate } from "@/lib/use-mutate";
import { cn, errMsg } from "@/lib/utils";
import { store as appStore, useDashboard } from "@/lib/store";
import { fmtMoney } from "@/lib/format";
import { GoalsPanel, GoalsList } from "@/components/GoalsPanel";
import { KIND_OPTIONS, CATEGORY_OPTIONS, KIND_LABEL_KEYS, CAT_LABEL_KEYS } from "@/lib/kinds";
import { inputCls, labelCls } from "@/components/ui/field";

// 选项与显示名与「改持仓」对话框共用一份，见 lib/kinds.ts

function Section({
  title,
  badge,
  children,
}: {
  title: string;
  badge?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card className="p-[var(--card-pad)]">
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm font-medium">{title}</div>
        {badge}
      </div>
      {children}
    </Card>
  );
}


function PositionForm({ onDone }: { onDone: () => void }) {
  const { t: tt } = useI18n();
  const [f, setF] = useState({
    symbol: "",
    name: "",
    kind: "股票",
    industry: "其他",
    shares: "",
    cost: "",
    last: "",
  });
  const [err, setErr] = useState("");

  const pos = useMutate<undefined, undefined>({
    fn: () =>
      api("/api/positions", {
        method: "POST",
        body: JSON.stringify({
          symbol: f.symbol.trim(),
          name: f.name.trim(),
          kind: f.kind,
          industry: f.industry.trim() || "其他",
          shares: Number(f.shares),
          cost: Number(f.cost),
          last: Number(f.last),
        }),
      }).then(() => undefined),
    key: undefined,
    silentError: true,
    onSettled: (_res, e) => {
      if (e) setErr(errMsg(e));
      else onDone();
    },
  });

  const submit = () => {
    setErr("");
    const shares = Number(f.shares);
    const cost = Number(f.cost);
    const last = Number(f.last);
    if (!f.symbol.trim()) {
      setErr(tt("entry.posCodeReq"));
      return;
    }
    if (!(shares > 0) || !(cost >= 0) || !(last >= 0)) {
      setErr(tt("entry.posNumErr"));
      return;
    }
    void pos.mutateAsync();
  };

  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-2 gap-2.5">
        <div>
          <label className={labelCls}>{tt("entry.posCode")}</label>
          <input className={inputCls} maxLength={6} value={f.symbol} onChange={(e) => setF({ ...f, symbol: e.target.value })} placeholder="600519" />
        </div>
        <div>
          <label className={labelCls}>{tt("entry.name")}</label>
          <input className={inputCls} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder={tt("entry.posNamePh")} />
        </div>
        <div>
          <label className={labelCls}>{tt("entry.kind")}</label>
          <select className={inputCls} value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
            {KIND_OPTIONS.map((k) => (
              <option key={k} value={k}>{tt(KIND_LABEL_KEYS[k] ?? "entry.kindOther")}</option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelCls}>{tt("entry.industry")}</label>
          <input className={inputCls} value={f.industry} onChange={(e) => setF({ ...f, industry: e.target.value })} placeholder={tt("entry.industryPh")} />
        </div>
        <div>
          <label className={labelCls}>{tt("entry.shares")}</label>
          <input className={inputCls} type="number" value={f.shares} min="0.01" step="any" onChange={(e) => setF({ ...f, shares: e.target.value })} placeholder="100" />
        </div>
        <div className="grid grid-cols-2 gap-2.5">
          <div>
            <label className={labelCls}>{tt("entry.costPrice")}</label>
            <input className={inputCls} type="number" value={f.cost} min="0" step="any" onChange={(e) => setF({ ...f, cost: e.target.value })} placeholder="1680" />
          </div>
          <div>
            <label className={labelCls}>{tt("entry.currentPrice")}</label>
            <input className={inputCls} type="number" value={f.last} min="0" step="any" onChange={(e) => setF({ ...f, last: e.target.value })} placeholder="1521" />
          </div>
        </div>
      </div>
      {err ? <FieldError>{err}</FieldError> : null}
      <Button size="sm" onClick={submit} disabled={!f.symbol || !f.shares || !f.cost || !f.last || pos.isPending}>
        <Plus className="w-3.5 h-3.5" /> {tt("entry.addPosition")}
      </Button>
    </div>
  );
}

/** 编辑已有流水：提交 PUT /api/transactions/:id。 */
function EditTransactionForm({
  tx,
  onCancel,
  onDone,
}: {
  tx: { id: number; date: string; item: string; category: string; amount: number };
  onCancel: () => void;
  onDone: () => void;
}) {
  const { t: tt } = useI18n();
  const [f, setF] = useState({
    date: tx.date,
    item: tx.item,
    category: tx.category,
    amount: String(Math.abs(tx.amount)),
    sign: tx.amount > 0 ? "+" : "-",
  });
  const [err, setErr] = useState("");

  const edit = useMutate<undefined, undefined>({
    fn: () => {
      const amt = Number(f.amount);
      const signed = f.sign === "+" ? amt : -amt;
      return api(`/api/transactions/${tx.id}`, {
        method: "PUT",
        body: JSON.stringify({ date: f.date, item: f.item.trim(), category: f.category, amount: signed }),
      }).then(() => undefined);
    },
    key: "entry.editSaved",
    vars: () => ({ name: f.item }),
    silentError: true,
    onSettled: (_res, e) => {
      if (e) setErr(errMsg(e));
      else onDone();
    },
  });

  const submit = () => {
    setErr("");
    const amt = Number(f.amount);
    if (!f.item.trim() || !(amt > 0)) {
      setErr(tt("entry.posNumErr"));
      return;
    }
    void edit.mutateAsync();
  };

  return (
    <div className="space-y-2.5">
      <div className="text-xs font-medium text-muted-foreground">{tt("entry.editTx", { item: tx.item })}</div>
      <div className="grid grid-cols-2 gap-2.5">
        <div>
          <label className={labelCls}>{tt("entry.date")}</label>
          <input className={inputCls} type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} />
        </div>
        <div>
          <label className={labelCls}>{tt("entry.category")}</label>
          <select className={inputCls} value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>
            {CATEGORY_OPTIONS.map((c) => (
              <option key={c} value={c}>{tt(CAT_LABEL_KEYS[c] ?? "entry.catOther")}</option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelCls}>{tt("entry.name")}</label>
          <input className={inputCls} value={f.item} onChange={(e) => setF({ ...f, item: e.target.value })} />
        </div>
        <div>
          <label className={labelCls}>{tt("entry.amount")}</label>
          <div className="flex gap-1">
            <select
              className="rounded-lg border border-input bg-background px-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              value={f.sign}
              onChange={(e) => setF({ ...f, sign: e.target.value })}
            >
              <option value="-">-</option>
              <option value="+">+</option>
            </select>
            <input
              className={inputCls}
              type="number"
              value={f.amount}
              onChange={(e) => setF({ ...f, amount: e.target.value })}
            />
          </div>
        </div>
      </div>
      {err ? <FieldError>{err}</FieldError> : null}
      <div className="flex gap-2">
        <Button size="sm" variant="outline" onClick={onCancel}>
          {tt("entry.cancel")}
        </Button>
        <Button size="sm" onClick={submit} disabled={!f.item || !f.amount || edit.isPending}>
          {tt("entry.save")}
        </Button>
      </div>
    </div>
  );
}
/** 一句话记账：规则解析秒回，复杂句自动升级 AI；成功直接入账。 */
function NlForm({ onDone }: { onDone: () => void }) {
  const { toast } = useToast();
  const { t: tt } = useI18n();
  const [text, setText] = useState("");
  const samples = [tt("entry.sample1"), tt("entry.sample2"), tt("entry.sample3")];

  const nl = useMutate<{ text: string }, { source: string; transaction: { item: string; category: string; amount: number; date: string } }>({
    fn: (a) =>
      api<{ source: string; transaction: { item: string; category: string; amount: number; date: string } }>("/api/nl-add", {
        method: "POST",
        body: JSON.stringify({ text: a.text }),
      }),
    key: undefined,
    onSettled: (res, e) => {
      if (e || !res) return;
      const t = res.transaction;
      toast(
        tt("entry.recorded", { cat: t.category, amt: fmtMoney(t.amount, true), item: t.item, date: t.date }) + (res.source === "ai" ? tt("entry.aiSuffix") : ""),
        "ok",
      );
      setText("");
      onDone();
    },
  });

  const submit = (s?: string) => {
    const q = (s ?? text).trim();
    if (!q || nl.isPending) return;
    void nl.mutateAsync({ text: q });
  };

  return (
    <div className="mb-3 rounded-[var(--radius)] border border-primary/20 bg-primary/5 p-3">
      <div className="flex items-center gap-1.5 text-xs font-medium mb-1.5">
        <Sparkles className="w-3.5 h-3.5 text-primary" />
        {tt("entry.nlLedger")}
      </div>
      <div className="flex gap-2">
        <input
          className={inputCls}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder={tt("entry.nlPh")}
        />
        <Button size="sm" onClick={() => submit()} disabled={nl.isPending || !text.trim()}>
          {nl.isPending ? tt("entry.parsing") : tt("entry.addOne")}
        </Button>
      </div>
      <div className="mt-1.5 flex gap-1.5 flex-wrap">
        {samples.map((s) => (
          <button
            key={s}
            className="rounded-full bg-background border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:text-primary hover:border-primary/40"
            onClick={() => submit(s)}
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

interface ImportPreview {
  columns: string[];
  mapping: { date: number; amount: number; type: number; desc: number };
  preview: { date: string; item: string; category: string; amount: number }[];
  rows: { date: string; item: string; category: string; amount: number }[];
  total: number;
  skipped: number;
}

/** 账单 CSV 导入：粘贴 → 解析预览（自动识别列/分类）→ 确认批量入账。 */
function ImportPanel({ onDone }: { onDone: () => void }) {
  const { toast } = useToast();
  const { t: tt } = useI18n();
  const [content, setContent] = useState("");
  const [parsed, setParsed] = useState<ImportPreview | null>(null);
  const [busy, setBusy] = useState(false);

  const doCommit = useMutate<ImportPreview, { imported: number; failed: string[] }>({
    fn: (rows) =>
      api<{ imported: number; failed: string[] }>("/api/import/commit", {
        method: "POST",
        body: JSON.stringify({ rows: rows.rows }),
      }),
    key: undefined,
    onSettled: (res, e) => {
      if (e || !res) return;
      const failed = res.failed.length > 0;
      toast(failed ? tt("entry.importPartial", { n: res.imported, m: res.failed.length }) : tt("entry.importOk", { n: res.imported }), failed ? "error" : "ok");
      setContent("");
      setParsed(null);
      onDone();
    },
  });

  const parse = async () => {
    if (!content.trim()) return;
    setBusy(true);
    try {
      const r = await api<ImportPreview>("/api/import/generic", {
        method: "POST",
        body: JSON.stringify({ content }),
      });
      setParsed(r);
    } catch (e) {
      setParsed(null);
      toast(errMsg(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const commit = () => {
    if (!parsed) return;
    void doCommit.mutateAsync(parsed);
  };

  const readFile = (file: File) => {
    // 支付宝/部分银行导出的 CSV 是 GBK：先按 UTF-8 读，出现替换符再按 GBK 重读
    file
      .text()
      .then((text) => {
        if (!text.includes("\uFFFD")) return text;
        return file.arrayBuffer().then((buf) => new TextDecoder("gbk").decode(buf));
      })
      .then((text) => setContent(text))
      .catch(() => toast(tt("entry.fileReadFail"), "error"));
  };

  return (
    <div className="mb-3 rounded-[var(--radius)] border border-border/70 p-3">
      <div className="text-xs font-medium mb-1.5">{tt("entry.importCsv")}</div>
      <div className="text-[11px] text-muted-foreground mb-2">
        {tt("entry.importDesc")}
      </div>
      <textarea
        className={`${inputCls} min-h-16`}
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder={tt("entry.csvPh")}
      />
      <div className="mt-2 flex gap-2">
        <Button size="sm" variant="outline" onClick={() => void parse()} disabled={busy || !content.trim()}>
          {busy ? tt("entry.parsing") : tt("entry.preview")}
        </Button>
        <label className="inline-flex items-center text-xs text-muted-foreground cursor-pointer hover:text-primary">
          {tt("entry.upload")}
          <input
            type="file"
            accept=".csv,.txt,text/csv,text/plain"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) readFile(f);
              e.target.value = "";
            }}
          />
        </label>
      </div>

      {parsed && (
        <div className="mt-3 border-t border-border/60 pt-3">
          <div className="text-xs mb-2">
            {tt("entry.recognized", { n: parsed.total })}
            {parsed.skipped > 0 && <span className="text-muted-foreground">{tt("entry.skipped", { n: parsed.skipped })}</span>}
          </div>
          <div className="overflow-x-auto scroll-thin">
            <Table size="xs">
              <thead>
                <tr className="text-muted-foreground text-left">
                  <th className="py-1 pr-3">{tt("entry.date")}</th>
                  <th className="py-1 pr-3">{tt("entry.name")}</th>
                  <th className="py-1 pr-3">{tt("entry.category")}</th>
                  <th className="py-1 text-right">{tt("entry.amount")}</th>
                </tr>
              </thead>
              <tbody>
                {parsed.preview.map((p, i) => (
                  <tr key={i} className="border-t border-border/40">
                    <td className="py-1 pr-3 tabular-nums">{p.date}</td>
                    <td className="py-1 pr-3 truncate max-w-32">{p.item}</td>
                    <td className="py-1 pr-3">{p.category}</td>
                    <td className={`py-1 text-right tabular-nums ${p.amount > 0 ? "text-up" : "text-down"}`}>{fmtMoney(p.amount, true)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
          <div className="mt-2 flex gap-2">
            <Button size="sm" onClick={commit} disabled={doCommit.isPending || parsed.total === 0}>
              {doCommit.isPending ? tt("entry.importing") : tt("entry.confirmImport", { n: parsed.total })}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setParsed(null)}>
              {tt("entry.cancel")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function DebtForm({ onDone }: { onDone: () => void }) {
  const { t: tt } = useI18n();
  const [f, setF] = useState({ name: "", monthly: "", balance: "", rate: "", dueDay: "" });
  const [err, setErr] = useState("");

  const debt = useMutate<undefined, undefined>({
    fn: () =>
      api("/api/debts", {
        method: "POST",
        body: JSON.stringify({
          name: f.name.trim(),
          monthly: Number(f.monthly),
          balance: Number(f.balance),
          rate: Number(f.rate) / 100,
          due_day: f.dueDay.trim(),
        }),
      }).then(() => undefined),
    key: undefined,
    onSettled: (_res, e) => {
      if (e) setErr(errMsg(e));
      else {
        setF({ name: "", monthly: "", balance: "", rate: "", dueDay: "" });
        onDone();
      }
    },
  });

  const submit = () => {
    setErr("");
    if (!f.name.trim()) { setErr(tt("entry.debtNameReq")); return; }
    if (!(Number(f.monthly) > 0)) { setErr(tt("entry.debtMonthlyReq")); return; }
    void debt.mutateAsync();
  };

  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-2 gap-2.5">
        <div>
          <label className={labelCls}>{tt("entry.name")}</label>
          <input className={cn(inputCls, !f.name.trim() && err && "border-red-400")} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder={tt("entry.debtNamePh")} />
        </div>
        <div>
          <label className={labelCls}>{tt("entry.monthlyPay")}</label>
          <input className={cn(inputCls, Number(f.monthly) <= 0 && err && "border-red-400")} type="number" value={f.monthly} onChange={(e) => setF({ ...f, monthly: e.target.value })} placeholder="6800" min="0.01" step="any" />
        </div>
        <div>
          <label className={labelCls}>{tt("entry.balance")}</label>
          <input className={inputCls} type="number" value={f.balance} onChange={(e) => setF({ ...f, balance: e.target.value })} placeholder="1280000" />
        </div>
        <div>
          <label className={labelCls}>{tt("entry.rate")}</label>
          <input className={inputCls} type="number" value={f.rate} onChange={(e) => setF({ ...f, rate: e.target.value })} placeholder="3.45" />
        </div>
        <div>
          <label className={labelCls}>{tt("entry.dueDay")}</label>
          <input className={inputCls} type="number" min="1" max="31" value={f.dueDay} onChange={(e) => setF({ ...f, dueDay: e.target.value })} placeholder="15" />
        </div>
      </div>
      {err ? <FieldError>{err}</FieldError> : null}
      <Button size="sm" onClick={submit} disabled={!f.name || debt.isPending}>
        <Plus className="w-3.5 h-3.5" /> {tt("entry.addDebt")}
      </Button>
    </div>
  );
}

function SubscriptionForm({ onDone }: { onDone: () => void }) {
  const { t: tt } = useI18n();
  const [f, setF] = useState({ name: "", monthly: "", dueDay: "", note: "" });
  const [err, setErr] = useState("");

  const sub = useMutate<undefined, undefined>({
    fn: () =>
      api("/api/subscriptions", {
        method: "POST",
        body: JSON.stringify({
          name: f.name.trim(),
          monthly: Number(f.monthly),
          due_day: f.dueDay.trim(),
          note: f.note.trim(),
        }),
      }).then(() => undefined),
    key: undefined,
    silentError: true,
    onSettled: (_res, e) => {
      if (e) setErr(errMsg(e));
      else {
        setF({ name: "", monthly: "", dueDay: "", note: "" });
        onDone();
      }
    },
  });

  const submit = () => {
    setErr("");
    if (!f.name.trim()) { setErr(tt("entry.subNameReq")); return; }
    if (!(Number(f.monthly) > 0)) { setErr(tt("entry.subMonthlyReq")); return; }
    void sub.mutateAsync();
  };

  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-2 gap-2.5">
        <div>
          <label className={labelCls}>{tt("entry.name")}</label>
          <input className={cn(inputCls, !f.name.trim() && err && "border-red-400")} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder={tt("entry.subNamePh")} />
        </div>
        <div>
          <label className={labelCls}>{tt("entry.monthlyCost")}</label>
          <input className={cn(inputCls, Number(f.monthly) <= 0 && err && "border-red-400")} type="number" value={f.monthly} onChange={(e) => setF({ ...f, monthly: e.target.value })} placeholder="68" min="0.01" step="any" />
        </div>
        <div>
          <label className={labelCls}>{tt("entry.dueDay")}</label>
          <input className={inputCls} type="number" min="1" max="31" value={f.dueDay} onChange={(e) => setF({ ...f, dueDay: e.target.value })} placeholder="5" />
        </div>
        <div>
          <label className={labelCls}>{tt("entry.note")}</label>
          <input className={inputCls} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} placeholder={tt("entry.notePh")} />
        </div>
      </div>
      {err ? <FieldError>{err}</FieldError> : null}
      <Button size="sm" onClick={submit} disabled={!f.name || !f.monthly || sub.isPending}>
        <Plus className="w-3.5 h-3.5" /> {tt("entry.addSubscription")}
      </Button>
    </div>
  );
}

type ListTab = "transactions" | "debts" | "subscriptions" | "goals";
type Panel = "import" | "position" | "debt" | "subscription" | "goal" | null;

type TxRow = { id: number; date: string; item: string; category: string; amount: number };

export function EntryView() {
  const { t: tt } = useI18n();
  const { toast } = useToast();
  const { dashboard } = useDashboard();
  const [tab, setTab] = useState<ListTab>("transactions");
  const [panel, setPanel] = useState<Panel>(null);
  const [txQuery, setTxQuery] = useState("");
  const [editingTx, setEditingTx] = useState<TxRow | null>(null);
  const [merging, setMerging] = useState(false);

  // 统一删除确认：待删项 = { type, label, id/name, onConfirm }
  type DeleteTarget =
    | { type: "tx"; id: number; name: string }
    | { type: "debt"; name: string }
    | { type: "sub"; name: string }
    | { type: "goal"; name: string };
  const [pendingDelete, setPendingDelete] = useState<DeleteTarget | null>(null);

  // 三处裸 DELETE 统一收口：成功 bump + 弹 ok toast，失败弹错误 toast（原实现静默吞掉）
  const delTx = useMutate<{ id: number; item: string }, void>({
    fn: ({ id }) => api(`/api/transactions/${id}`, { method: "DELETE" }).then(() => undefined),
    key: "entry.deletedItem",
    vars: (a) => ({ name: a.item }),
    onSettled: (_res, e) => { if (!e) setPendingDelete(null); },
  });
  const delDebt = useMutate<string, void>({
    fn: (name) => api(`/api/debts/${encodeURIComponent(name)}`, { method: "DELETE" }).then(() => undefined),
    key: "entry.deletedDebt",
    vars: (a) => ({ name: a }),
    onSettled: (_res, e) => { if (!e) setPendingDelete(null); },
  });
  const delSub = useMutate<string, void>({
    fn: (name) => api(`/api/subscriptions/${encodeURIComponent(name)}`, { method: "DELETE" }).then(() => undefined),
    key: "entry.deletedSub",
    vars: (a) => ({ name: a }),
    onSettled: (_res, e) => { if (!e) setPendingDelete(null); },
  });
  const goalDel = useMutate<string, void>({
    fn: (name) => deleteGoal(name).then(() => undefined),
    key: "goals.deleted",
    vars: (a) => ({ name: a }),
    onSettled: (_res, e) => { if (!e) setPendingDelete(null); },
  });

  const doMerge = async () => {
    if (!dashboard || merging) return;
    setMerging(true);
    try {
      const m = dashboard.transactions[0]?.date.slice(0, 7) ?? (() => {
        const d = new Date();
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
      })();
      const r = await api<{ merged: number }>("/api/transactions/merge", {
        method: "POST",
        body: JSON.stringify({ month: m }),
      });
      if (r.merged > 0) {
        appStore.bump();
        toast(tt("entry.mergeDone", { n: r.merged }), "ok");
      } else {
        toast(tt("entry.mergeNone"), "ok");
      }
    } catch (e) {
      toast(errMsg(e), "error");
    } finally {
      setMerging(false);
    }
  };

  const actions: { id: Panel; label: string; icon: React.ReactNode }[] = [
    { id: "import", label: tt("entry.actionImport"), icon: <FileUp className="w-3.5 h-3.5" /> },
    { id: "position", label: tt("entry.actionPositions"), icon: <Sparkles className="w-3.5 h-3.5" /> },
    { id: "debt", label: tt("entry.actionDebt"), icon: <Landmark className="w-3.5 h-3.5" /> },
    { id: "subscription", label: tt("entry.actionSubscription"), icon: <Repeat className="w-3.5 h-3.5" /> },
    { id: "goal", label: tt("entry.actionGoal"), icon: <Target className="w-3.5 h-3.5" /> },
  ];

  const tabs: { id: ListTab; label: string; count?: number }[] = [
    { id: "transactions", label: tt("entry.tabTransactions"), count: dashboard?.transactions.length },
    { id: "debts", label: tt("entry.tabDebts"), count: dashboard?.debts.items.length },
    { id: "subscriptions", label: tt("entry.tabSubscriptions"), count: dashboard?.subscriptions.items.length },
    { id: "goals", label: tt("entry.tabGoals"), count: dashboard?.goals.length },
  ];

  // 流水本地搜索：名称/分类/日期 任一命中
  const txQueryL = txQuery.trim().toLowerCase();
  const txRows = (dashboard?.transactions ?? []).filter((t) => {
    if (!txQueryL) return true;
    return (
      t.item.toLowerCase().includes(txQueryL) ||
      t.category.toLowerCase().includes(txQueryL) ||
      t.date.includes(txQueryL)
    );
  });

  const openPanel = (id: Panel) => setPanel((cur) => (cur === id ? null : id));

  return (
    <div className="space-y-3">
      {/* 主入口：{tt("entry.nlLedger")}，永远在最上面 */}
      <NlForm onDone={() => appStore.bump()} />

      {/* 快捷动作：点开哪个显示哪个，不全部铺开 */}
      <div className="flex gap-2 flex-wrap">
        {actions.map((a) => (
          <Button
            key={a.id}
            size="sm"
            variant={panel === a.id ? "default" : "outline"}
            onClick={() => openPanel(a.id)}
          >
            {a.icon} {a.label}
          </Button>
        ))}
      </div>

      {panel === "import" && <ImportPanel onDone={() => appStore.bump()} />}
      {panel === "position" && (
        <Section title={tt("entry.sectionPosition")} badge={<Badge variant="muted">{tt("entry.priceHint")}</Badge>}>
          <PositionForm onDone={() => appStore.bump()} />
        </Section>
      )}
      {panel === "debt" && (
        <Section title={tt("entry.sectionDebt")}>
          <DebtForm onDone={() => appStore.bump()} />
        </Section>
      )}
      {panel === "subscription" && (
        <Section title={tt("entry.sectionSubscription")}>
          <SubscriptionForm onDone={() => appStore.bump()} />
        </Section>
      )}
      {panel === "goal" && (
        <Section title={tt("entry.sectionGoal")}>
          <GoalsPanel onDone={() => appStore.bump()} />
        </Section>
      )}

      {/* 列表管理：流水 + 负债/订阅/目标（5 页签下唯一的账户管理入口；持仓管理在持仓页） */}
      <Section
        title={tt("entry.myLedger")}
        badge={
          <div className="flex gap-1.5">
            {tabs.map((t) => (
              <button
                key={t.id}
                type="button"
                className={`rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors ${
                  tab === t.id
                    ? "bg-primary/15 text-primary"
                    : "bg-muted text-muted-foreground hover:text-foreground"
                }`}
                onClick={() => setTab(t.id)}
              >
                {t.label}
                {t.count != null && <span className="ml-1 tabular-nums">{t.count}</span>}
              </button>
            ))}
          </div>
        }
      >
        {tab === "transactions" && (
          dashboard && dashboard.transactions.length > 0 ? (
            <div>
              <div className="mb-2 flex items-center gap-2">
                <div className="relative flex-1">
                  <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
                  <input
                    className="w-full rounded-lg border border-input bg-background pl-8 pr-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    value={txQuery}
                    onChange={(e) => setTxQuery(e.target.value)}
                    placeholder={tt("entry.searchPh")}
                  />
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void doMerge()}
                  disabled={merging}
                  aria-label={tt("entry.mergeMonth", { m: (dashboard?.transactions[0]?.date ?? "").slice(0, 7) })}
                >
                  <Combine className="w-3.5 h-3.5" /> {tt("entry.mergeSame")}
                </Button>
              </div>
              {editingTx ? (
                <div className="rounded-lg border border-primary/30 bg-primary/5 p-3">
                  <EditTransactionForm
                    tx={editingTx}
                    onCancel={() => setEditingTx(null)}
                    onDone={() => {
                      setEditingTx(null);
                      appStore.bump();
                    }}
                  />
                </div>
              ) : (
                <div className="scroll-thin overflow-x-auto">
                  {/* 表头：日期 / 条目 / 分类 / 金额，操作列悬停出现。
                      股票与记账软件的流水都是单行表格——两行式（日期独占一行）会把
                      11 条流水的页面拉长一倍，扫读成本高。 */}
                  <div className="hidden grid-cols-[6.5rem_minmax(0,1fr)_7rem_7.5rem_4.5rem] gap-3 border-b border-border bg-muted/50 px-2 py-1.5 text-[11px] font-medium text-muted-foreground sm:grid">
                    <span>{tt("entry.date")}</span>
                    <span>{tt("entry.name")}</span>
                    <span>{tt("entry.category")}</span>
                    <span className="text-right">{tt("entry.amount")}</span>
                    <span />
                  </div>
                  {(() => {
                    const shown = [...txRows].sort((a, b) => (a.date < b.date ? 1 : -1)).slice(0, 200);
                    return shown.map((t) => (
                      <div
                        key={t.id}
                        className="group/tx flex items-center gap-2 border-b border-border/40 px-2 py-2 text-[13px] transition-colors last:border-0 hover:bg-accent/40 sm:grid sm:grid-cols-[6.5rem_minmax(0,1fr)_7rem_7.5rem_4.5rem] sm:gap-3"
                      >
                        <span className="hidden shrink-0 tabular-nums text-muted-foreground sm:block">{t.date}</span>
                        <span className="min-w-0 flex-1 truncate">
                          {t.item}
                          <span className="ml-2 text-[11px] text-muted-foreground sm:hidden">
                            {t.date} · {t.category}
                          </span>
                        </span>
                        <span className="hidden truncate text-[11px] text-muted-foreground sm:block">{t.category}</span>
                        <span className={`shrink-0 text-right tabular-nums ${t.amount > 0 ? "text-up" : "text-down"}`}>
                          {fmtMoney(t.amount, true)}
                        </span>
                        <span className="flex shrink-0 items-center justify-end gap-0.5 opacity-60 transition-opacity group-hover/tx:opacity-100">
                          <button
                            className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-primary"
                            onClick={() => setEditingTx({ id: t.id, date: t.date, item: t.item, category: t.category, amount: t.amount })}
                            aria-label={tt("entry.editTx", { item: t.item })}
                            title={tt("entry.editTx", { item: t.item })}
                          >
                            <Pencil className="w-3.5 h-3.5" />
                          </button>
                          <button
                            className="rounded p-1 text-muted-foreground hover:bg-red-500/10 hover:text-red-600"
                            onClick={() => setPendingDelete({ type: "tx", id: t.id, name: t.item })}
                            aria-label={tt("entry.deleteItem", { name: t.item })}
                            title={tt("entry.deleteItem", { name: t.item })}
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </span>
                      </div>
                    ));
                  })()}
                  {txRows.length === 0 && (
                    <div className="py-4 text-center text-xs text-muted-foreground">{tt("entry.noMatchTx", { q: txQuery })}</div>
                  )}
                  {txQueryL === "" && dashboard.transactions.length > 200 && (
                    <div className="py-2 text-center text-xs text-muted-foreground">
                      {tt("entry.txCount", { n: dashboard.transactions.length })}
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : (
            <EmptyState mode="compact" text={tt("entry.noTx")} />
          )
        )}

        {tab === "debts" && (
          dashboard && dashboard.debts.items.length > 0 ? (
            <div>
              {dashboard.debts.items.map((d) => (
                <div key={d.name} className="flex items-center justify-between py-1.5 text-sm">
                  <span>
                    {d.name} <span className="text-muted-foreground text-xs">{(d.rate * 100).toFixed(1)}%</span>
                  </span>
                  <span className="flex items-center gap-2">
                    <span className="tabular-nums text-muted-foreground">{tt("entry.perMonth", { v: fmtMoney(d.monthly) })}</span>
                    <button
                      className="text-muted-foreground hover:text-red-600"
                      onClick={() => setPendingDelete({ type: "debt", name: d.name })}
                      aria-label={tt("entry.deleteItem", { name: d.name })}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState mode="compact" text={tt("entry.noDebts")} />
          )
        )}

        {tab === "subscriptions" && (
          <div>
            {dashboard && dashboard.subscriptions.items.length > 0 ? (
              <ul className="space-y-1.5">
                {dashboard.subscriptions.items.map((s) => (
                  <li key={s.name} className="flex items-center justify-between text-sm">
                    <span>
                      <Repeat className="w-3.5 h-3.5 inline mr-1.5 text-muted-foreground" />
                      {s.name}
                      {s.due_day && <span className="text-xs text-muted-foreground ml-1.5">{tt("entry.dueDaySuffix", { d: s.due_day })}</span>}
                    </span>
                    <span className="flex items-center gap-2">
                      <span className="tabular-nums text-muted-foreground">{tt("entry.perMonth", { v: fmtMoney(s.monthly) })}</span>
                      <button
                        className="text-muted-foreground hover:text-red-600"
                        onClick={() => setPendingDelete({ type: "sub", name: s.name })}
                        aria-label={tt("entry.deleteSub", { name: s.name })}
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState mode="compact" text={tt("entry.noSubs")} />
            )}
            <div className="mt-3 text-[11px] text-muted-foreground">
              {tt("entry.subTotal", { v: fmtMoney(dashboard?.subscriptions.monthly_total ?? 0) })}
            </div>
          </div>
        )}
        {tab === "goals" && (
          <div>
            <GoalsList goals={dashboard?.goals ?? []} onDone={() => appStore.bump()} onRequestDelete={(name) => setPendingDelete({ type: "goal", name })} />
          </div>
        )}
      </Section>

      {/* 统一删除确认：流水 / 负债 / 订阅 / 目标 */}
      {pendingDelete && pendingDelete.type === "tx" && (
        <ConfirmDialog
          open
          onOpenChange={(o) => { if (!o) setPendingDelete(null); }}
          title={tt("entry.deleteTitle", { name: pendingDelete.name })}
          description={tt("entry.deleteTxDesc")}
          danger
          onConfirm={() => {
            const d = pendingDelete;
            setPendingDelete(null);
            void delTx.mutateAsync({ id: d.id, item: d.name });
          }}
        />
      )}
      {pendingDelete && pendingDelete.type === "debt" && (
        <ConfirmDialog
          open
          onOpenChange={(o) => { if (!o) setPendingDelete(null); }}
          title={tt("entry.deleteDebtTitle", { name: pendingDelete.name })}
          description={tt("entry.deleteDebtDesc")}
          danger
          onConfirm={() => {
            const d = pendingDelete;
            setPendingDelete(null);
            void delDebt.mutateAsync(d.name);
          }}
        />
      )}
      {pendingDelete && pendingDelete.type === "sub" && (
        <ConfirmDialog
          open
          onOpenChange={(o) => { if (!o) setPendingDelete(null); }}
          title={tt("entry.deleteSubTitle", { name: pendingDelete.name })}
          description={tt("entry.deleteSubDesc")}
          danger
          onConfirm={() => {
            const d = pendingDelete;
            setPendingDelete(null);
            void delSub.mutateAsync(d.name);
          }}
        />
      )}
      {pendingDelete && pendingDelete.type === "goal" && (
        <ConfirmDialog
          open
          onOpenChange={(o) => { if (!o) setPendingDelete(null); }}
          title={tt("goals.deleteTitle", { name: pendingDelete.name })}
          description={tt("goals.deleteDesc")}
          danger
          onConfirm={() => {
            const d = pendingDelete;
            setPendingDelete(null);
            void goalDel.mutateAsync(d.name);
          }}
        />
      )}
    </div>
  );
}

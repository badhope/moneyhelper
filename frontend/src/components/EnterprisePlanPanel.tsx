/** 企业预算与资金计划（4.19.0）：编制、执行对比与现金流推演。只做管理口径，不生成凭证、不代划转。 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { AlertTriangle, CalendarDays, Plus, RefreshCw, Save, Trash2, Wallet } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Segmented } from "@/components/ui/segmented";
import { StatTile } from "@/components/ui/stat";
import { Table } from "@/components/ui/table";
import { useI18n } from "@/lib/i18n";
import { cn, errMsg } from "@/lib/utils";
import { fmtMoney } from "@/lib/format";
import {
  useBudgetPlan,
  useBudgetReport,
  useCashPlan,
  useCashReport,
  usePlanPeriods,
  useSaveBudget,
  useSaveCash,
  type BudgetLine,
  type CashLine,
} from "@/lib/use-enterprise-plan";

const inputCls =
  "h-8 w-full rounded-md border border-border/70 bg-background px-2 text-xs outline-none transition-colors focus:border-primary";

function shortMoney(v: number) {
  const abs = Math.abs(v);
  if (abs >= 10000) return `${(v / 10000).toFixed(abs >= 100000 ? 0 : 1)}万`;
  return Math.round(v).toLocaleString("zh-CN");
}

function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-1.5 rounded-lg bg-amber-500/10 px-2.5 py-2 text-[11px] leading-relaxed text-amber-700 dark:text-amber-400">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>{children}</span>
    </div>
  );
}

function statusTone(status: string) {
  if (status === "over") return "warn";
  if (status === "unbudgeted") return "muted";
  return "ok";
}

function BudgetBody({ period }: { period: string }) {
  const { t } = useI18n();
  const plan = useBudgetPlan(period);
  const report = useBudgetReport(period);
  const save = useSaveBudget();
  const [rows, setRows] = useState<BudgetLine[]>([]);
  const [note, setNote] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    const accounts = plan.data?.accounts ?? [];
    setRows(
      plan.data?.lines?.length
        ? plan.data.lines.map((x) => ({ ...x }))
        : [{ account_code: accounts[0]?.code ?? "", amount: 0, note: "" }],
    );
    setNote(plan.data?.plan?.note ?? "");
    setErr("");
  }, [plan.data]);

  const accounts = plan.data?.accounts ?? [];
  const totals = report.data?.totals;
  const budgetRows = useMemo(() => report.data?.rows ?? [], [report.data]);

  const setRow = (idx: number, patch: Partial<BudgetLine>) =>
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)));

  const doSave = () => {
    setErr("");
    const lines = rows
      .filter((r) => r.account_code)
      .map((r) => ({ account_code: r.account_code, amount: Number(r.amount) || 0, note: r.note ?? "" }));
    save.mutate(
      { period, lines, note },
      { onError: (e) => setErr(errMsg(e)), onSuccess: () => setRows((x) => [...x]) },
    );
  };

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Wallet className="h-4 w-4 text-primary" />
          {t("plan.budgetTitle")}
          <Badge variant={plan.data?.exists ? "ok" : "muted"}>
            {plan.data?.exists ? t("plan.saved") : t("plan.newPlan")}
          </Badge>
        </div>
        <Button size="sm" onClick={doSave} disabled={save.isPending}>
          <Save className="h-3.5 w-3.5" />
          {save.isPending ? t("plan.saving") : t("plan.save")}
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatTile label={t("plan.budgetIncome")} value={fmtMoney(totals?.budget_income ?? 0)} />
        <StatTile label={t("plan.actualIncome")} value={fmtMoney(totals?.actual_income ?? 0)} tone="up" />
        <StatTile label={t("plan.budgetExpense")} value={fmtMoney(totals?.budget_expense ?? 0)} />
        <StatTile label={t("plan.actualExpense")} value={fmtMoney(totals?.actual_expense ?? 0)} tone="down" />
      </div>

      {(report.data?.warnings ?? []).map((w) => <Notice key={w}>{w}</Notice>)}
      {err ? <div className="text-xs text-red-600 dark:text-red-400">{err}</div> : null}

      <Card className="overflow-hidden p-0">
        <div className="flex items-center justify-between border-b border-border/60 px-3 py-2">
          <span className="text-xs font-medium">{t("plan.editLines")}</span>
          <span className="text-[11px] text-muted-foreground">{t("plan.limit")}</span>
        </div>
        <div className="overflow-x-auto">
          <Table size="xs" minWidth={560}>
            <thead className="bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-2 py-1.5 text-left">{t("plan.account")}</th>
                <th className="px-2 py-1.5 text-right">{t("plan.amount")}</th>
                <th className="px-2 py-1.5 text-left">{t("plan.note")}</th>
                <th className="px-2 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, idx) => (
                <tr key={idx} className="border-t border-border/40">
                  <td className="px-2 py-1">
                    <select
                      className={inputCls}
                      value={r.account_code}
                      onChange={(e) => {
                        const a = accounts.find((x) => x.code === e.target.value);
                        setRow(idx, {
                          account_code: e.target.value,
                          account_name: a?.name,
                          account_type: a?.type,
                        });
                      }}
                    >
                      {accounts.map((a) => (
                        <option key={a.code} value={a.code}>
                          {a.code} {a.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-2 py-1">
                    <input
                      className={cn(inputCls, "text-right tabular-nums")}
                      type="number"
                      min="0"
                      step="0.01"
                      value={Number.isFinite(Number(r.amount)) ? r.amount : ""}
                      onChange={(e) => setRow(idx, { amount: e.target.value === "" ? 0 : Number(e.target.value) })}
                    />
                  </td>
                  <td className="px-2 py-1">
                    <input
                      className={inputCls}
                      value={r.note ?? ""}
                      onChange={(e) => setRow(idx, { note: e.target.value })}
                      placeholder={t("plan.notePlaceholder")}
                    />
                  </td>
                  <td className="px-2 py-1 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 px-1"
                      onClick={() => setRows((x) => x.filter((_, i) => i !== idx))}
                      title={t("plan.delete")}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/50 px-3 py-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              setRows((x) => [...x, { account_code: accounts[0]?.code ?? "", amount: 0, note: "" }])
            }
            disabled={rows.length >= 200}
          >
            <Plus className="h-3.5 w-3.5" />
            {t("plan.addLine")}
          </Button>
          <input
            className={cn(inputCls, "max-w-[320px]")}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t("plan.notePlaceholder")}
          />
        </div>
      </Card>

      <Card className="overflow-hidden p-0">
        <div className="border-b border-border/60 px-3 py-2 text-xs font-medium">{t("plan.execution")}</div>
        {budgetRows.length === 0 ? (
          <EmptyState title={t("plan.noData")} desc={t("plan.noDataHint")} className="py-8" />
        ) : (
          <div className="overflow-x-auto">
            <Table size="xs" minWidth={520}>
              <thead className="bg-muted/30 text-muted-foreground">
                <tr>
                  <th className="px-2 py-1.5 text-left">{t("plan.account")}</th>
                  <th className="px-2 py-1.5 text-right">{t("plan.budget")}</th>
                  <th className="px-2 py-1.5 text-right">{t("plan.actual")}</th>
                  <th className="px-2 py-1.5 text-right">{t("plan.variance")}</th>
                  <th className="px-2 py-1.5 text-right">{t("plan.pct")}</th>
                  <th className="px-2 py-1.5 text-left">{t("plan.status")}</th>
                </tr>
              </thead>
              <tbody>
                {budgetRows.map((r) => (
                  <tr key={r.account_code} className="border-t border-border/40">
                    <td className="px-2 py-1.5">
                      {r.account_code} {r.account_name}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{fmtMoney(r.budget)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{fmtMoney(r.actual)}</td>
                    <td
                      className={cn(
                        "px-2 py-1.5 text-right tabular-nums",
                        r.variance > 0 && r.account_type === "expense" ? "text-down" : "",
                        r.variance > 0 && r.account_type === "income" ? "text-up" : "",
                      )}
                    >
                      {r.variance > 0 ? "+" : ""}
                      {fmtMoney(r.variance)}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">
                      {r.pct == null ? "—" : `${r.pct.toFixed(0)}%`}
                    </td>
                    <td className="px-2 py-1.5">
                      <Badge variant={statusTone(r.status)}>
                        {r.status === "over"
                          ? t("plan.statusOver")
                          : r.status === "unbudgeted"
                            ? t("plan.statusUnbudgeted")
                            : t("plan.statusWithin")}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}
      </Card>

      <div className="text-[11px] text-muted-foreground">{report.data?.boundary ?? plan.data?.boundary}</div>
    </div>
  );
}

function CashBody({ period }: { period: string }) {
  const { t } = useI18n();
  const plan = useCashPlan(period);
  const report = useCashReport(period);
  const save = useSaveCash();
  const [rows, setRows] = useState<CashLine[]>([]);
  const [opening, setOpening] = useState(0);
  const [target, setTarget] = useState(0);
  const [note, setNote] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    const accounts = plan.data?.accounts ?? [];
    setRows(
      plan.data?.lines?.length
        ? plan.data.lines.map((x) => ({ ...x }))
        : [{ expected_date: `${period}-05`, direction: "in", account_code: accounts[0]?.code ?? "1001", amount: 0 }],
    );
    setOpening(plan.data?.plan?.opening ?? 0);
    setTarget(plan.data?.plan?.target_min ?? 0);
    setNote(plan.data?.plan?.note ?? "");
    setErr("");
  }, [plan.data, period]);

  const accounts = plan.data?.accounts ?? [];
  const series = report.data?.series ?? [];
  const openBal = report.data?.opening ?? 0;
  const curve = series.length
    ? [
        { date: `${period}-01`, planned: openBal, actual: openBal },
        ...series.map((x) => ({ date: x.date, planned: x.planned_balance, actual: x.actual_balance })),
      ]
    : [];
  const curveMax = Math.max(1, ...curve.map((x) => Math.max(x.planned, x.actual)), openBal, target);

  const setRow = (idx: number, patch: Partial<CashLine>) =>
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)));

  const doSave = () => {
    setErr("");
    const lines = rows
      .filter((r) => r.expected_date)
      .map((r) => ({
        expected_date: r.expected_date,
        direction: r.direction,
        account_code: r.account_code || "1001",
        counterparty: r.counterparty ?? "",
        amount: Number(r.amount) || 0,
        certainty: r.certainty ?? "medium",
        note: r.note ?? "",
      }));
    save.mutate(
      { period, lines, opening: Number(opening) || 0, target_min: Number(target) || 0, note },
      { onError: (e) => setErr(errMsg(e)) },
    );
  };

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <CalendarDays className="h-4 w-4 text-primary" />
          {t("plan.cashTitle")}
          <Badge variant={plan.data?.exists ? "ok" : "muted"}>
            {plan.data?.exists ? t("plan.saved") : t("plan.newPlan")}
          </Badge>
        </div>
        <Button size="sm" onClick={doSave} disabled={save.isPending}>
          <Save className="h-3.5 w-3.5" />
          {save.isPending ? t("plan.saving") : t("plan.save")}
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div className="rounded-lg bg-muted/25 px-3 py-2">
          <div className="text-[11px] text-muted-foreground">{t("plan.opening")}</div>
          <input
            className={cn(inputCls, "mt-1 text-right tabular-nums")}
            type="number"
            step="0.01"
            value={opening}
            onChange={(e) => setOpening(e.target.value === "" ? 0 : Number(e.target.value))}
          />
        </div>
        <div className="rounded-lg bg-muted/25 px-3 py-2">
          <div className="text-[11px] text-muted-foreground">{t("plan.target")}</div>
          <input
            className={cn(inputCls, "mt-1 text-right tabular-nums")}
            type="number"
            step="0.01"
            value={target}
            onChange={(e) => setTarget(e.target.value === "" ? 0 : Number(e.target.value))}
          />
        </div>
        <StatTile label={t("plan.projectedEnd")} value={fmtMoney(report.data?.projected_end ?? 0)} />
        <StatTile
          label={t("plan.actualToDate")}
          value={fmtMoney(report.data?.actual_to_date ?? 0)}
          hint={report.data?.as_of ? `${t("plan.asOf")} ${report.data.as_of}` : undefined}
        />
      </div>

      {(report.data?.warnings ?? []).map((w) => <Notice key={w}>{w}</Notice>)}
      {err ? <div className="text-xs text-red-600 dark:text-red-400">{err}</div> : null}

      {curve.length > 0 ? (
        <Card className="p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className="font-medium">{t("plan.cashCurve")}</span>
            <span className="flex items-center gap-3 text-[11px] text-muted-foreground">
              <span className="flex items-center gap-1">
                <span className="h-1.5 w-4 rounded-full bg-primary/40" />
                {t("plan.planBalance")}
              </span>
              <span className="flex items-center gap-1">
                <span className="h-1.5 w-4 rounded-full bg-primary" />
                {t("plan.actualBalance")}
              </span>
              <span className="flex items-center gap-1">
                <span className="h-0.5 w-4 border-t border-dashed border-amber-500" />
                {t("plan.target")}
              </span>
            </span>
          </div>
          <svg viewBox="0 0 720 210" className="h-[190px] w-full" role="img">
            {[0, 0.5, 1].map((ratio) => {
              const y = 14 + 160 * (1 - ratio);
              return (
                <g key={ratio}>
                  <line x1="52" x2="708" y1={y} y2={y} className="stroke-border/50" strokeWidth="1" />
                  <text x="0" y={y + 3} style={{ fontSize: 9 }} className="fill-muted-foreground">
                    {shortMoney(curveMax * ratio)}
                  </text>
                </g>
              );
            })}
            {target > 0 ? (
              <g>
                <line
                  x1="52"
                  x2="708"
                  y1={14 + 160 * (1 - Math.min(1, target / curveMax))}
                  y2={14 + 160 * (1 - Math.min(1, target / curveMax))}
                  className="stroke-amber-500/70"
                  strokeWidth="1"
                  strokeDasharray="4 3"
                />
                <text
                  x="708"
                  y={14 + 160 * (1 - Math.min(1, target / curveMax)) - 4}
                  textAnchor="end"
                  style={{ fontSize: 9 }}
                  className="fill-amber-600 dark:fill-amber-400"
                >
                  {t("plan.target")} {shortMoney(target)}
                </text>
              </g>
            ) : null}
            {[
              { key: "planned", cls: "stroke-primary/40", width: 2 },
              { key: "actual", cls: "stroke-primary", width: 2.4 },
            ].map((line) => (
              <g key={line.key}>
                <polyline
                  fill="none"
                  className={line.cls}
                  strokeWidth={line.width}
                  strokeLinejoin="round"
                  points={curve
                    .map((x, i) => `${52 + (i / Math.max(1, curve.length - 1)) * 656},${14 + 160 * (1 - x[line.key as "planned" | "actual"] / curveMax)}`)
                    .join(" ")}
                />
                {curve.map((x, i) => (
                  <circle
                    key={`${line.key}-${x.date}`}
                    cx={52 + (i / Math.max(1, curve.length - 1)) * 656}
                    cy={14 + 160 * (1 - x[line.key as "planned" | "actual"] / curveMax)}
                    r={line.key === "actual" ? 3.2 : 2.4}
                    className={line.key === "actual" ? "fill-primary" : "fill-primary/50"}
                  />
                ))}
              </g>
            ))}
            {curve.map((x, i) => (
              <text
                key={x.date}
                x={52 + (i / Math.max(1, curve.length - 1)) * 656}
                y="196"
                textAnchor={i === 0 ? "start" : i === curve.length - 1 ? "end" : "middle"}
                style={{ fontSize: 9 }}
                className="fill-muted-foreground"
              >
                {x.date.slice(5)}
              </text>
            ))}
          </svg>
        </Card>
      ) : null}

      <Card className="overflow-hidden p-0">
        <div className="flex items-center justify-between border-b border-border/60 px-3 py-2">
          <span className="text-xs font-medium">{t("plan.cashLines")}</span>
          <span className="text-[11px] text-muted-foreground">{t("plan.limit")}</span>
        </div>
        <div className="overflow-x-auto">
          <Table size="xs" minWidth={720}>
            <thead className="bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-2 py-1.5 text-left">{t("plan.date")}</th>
                <th className="px-2 py-1.5 text-left">{t("plan.direction")}</th>
                <th className="px-2 py-1.5 text-left">{t("plan.account")}</th>
                <th className="px-2 py-1.5 text-left">{t("plan.counterparty")}</th>
                <th className="px-2 py-1.5 text-right">{t("plan.amount")}</th>
                <th className="px-2 py-1.5 text-left">{t("plan.certainty")}</th>
                <th className="px-2 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, idx) => (
                <tr key={idx} className="border-t border-border/40">
                  <td className="px-2 py-1">
                    <input
                      className={inputCls}
                      type="date"
                      value={r.expected_date}
                      min={`${period}-01`}
                      max={`${period}-31`}
                      onChange={(e) => setRow(idx, { expected_date: e.target.value })}
                    />
                  </td>
                  <td className="px-2 py-1">
                    <select
                      className={inputCls}
                      value={r.direction}
                      onChange={(e) => setRow(idx, { direction: e.target.value as "in" | "out" })}
                    >
                      <option value="in">{t("plan.cashIn")}</option>
                      <option value="out">{t("plan.cashOut")}</option>
                    </select>
                  </td>
                  <td className="px-2 py-1">
                    <select
                      className={inputCls}
                      value={r.account_code}
                      onChange={(e) => setRow(idx, { account_code: e.target.value })}
                    >
                      {accounts.map((a) => (
                        <option key={a.code} value={a.code}>
                          {a.code} {a.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-2 py-1">
                    <input
                      className={inputCls}
                      value={r.counterparty ?? ""}
                      onChange={(e) => setRow(idx, { counterparty: e.target.value })}
                      placeholder={t("plan.counterpartyPlaceholder")}
                    />
                  </td>
                  <td className="px-2 py-1">
                    <input
                      className={cn(inputCls, "text-right tabular-nums")}
                      type="number"
                      min="0"
                      step="0.01"
                      value={Number.isFinite(Number(r.amount)) ? r.amount : ""}
                      onChange={(e) => setRow(idx, { amount: e.target.value === "" ? 0 : Number(e.target.value) })}
                    />
                  </td>
                  <td className="px-2 py-1">
                    <select
                      className={inputCls}
                      value={r.certainty ?? "medium"}
                      onChange={(e) =>
                        setRow(idx, { certainty: e.target.value as "high" | "medium" | "low" })
                      }
                    >
                      <option value="high">{t("plan.certainHigh")}</option>
                      <option value="medium">{t("plan.certainMedium")}</option>
                      <option value="low">{t("plan.certainLow")}</option>
                    </select>
                  </td>
                  <td className="px-2 py-1 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 px-1"
                      onClick={() => setRows((x) => x.filter((_, i) => i !== idx))}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/50 px-3 py-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              setRows((x) => [
                ...x,
                {
                  expected_date: `${period}-15`,
                  direction: "out",
                  account_code: accounts[0]?.code ?? "1001",
                  amount: 0,
                },
              ])
            }
            disabled={rows.length >= 200}
          >
            <Plus className="h-3.5 w-3.5" />
            {t("plan.addLine")}
          </Button>
          <input
            className={cn(inputCls, "max-w-[320px]")}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t("plan.notePlaceholder")}
          />
        </div>
      </Card>

      <Card className="overflow-hidden p-0">
        <div className="border-b border-border/60 px-3 py-2 text-xs font-medium">{t("plan.dailyCompare")}</div>
        {series.length === 0 ? (
          <EmptyState title={t("plan.noData")} desc={t("plan.noDataHint")} className="py-8" />
        ) : (
          <div className="overflow-x-auto">
            <Table size="xs" minWidth={560}>
              <thead className="bg-muted/30 text-muted-foreground">
                <tr>
                  <th className="px-2 py-1.5 text-left">{t("plan.date")}</th>
                  <th className="px-2 py-1.5 text-right">{t("plan.plannedIn")}</th>
                  <th className="px-2 py-1.5 text-right">{t("plan.plannedOut")}</th>
                  <th className="px-2 py-1.5 text-right">{t("plan.planBalance")}</th>
                  <th className="px-2 py-1.5 text-right">{t("plan.actualNet")}</th>
                  <th className="px-2 py-1.5 text-right">{t("plan.actualBalance")}</th>
                </tr>
              </thead>
              <tbody>
                {series.map((x) => (
                  <tr key={x.date} className="border-t border-border/40">
                    <td className="px-2 py-1.5">{x.date}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{fmtMoney(x.planned_in)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{fmtMoney(x.planned_out)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{fmtMoney(x.planned_balance)}</td>
                    <td
                      className={cn(
                        "px-2 py-1.5 text-right tabular-nums",
                        x.actual_net >= 0 ? "text-up" : "text-down",
                      )}
                    >
                      {x.actual_net > 0 ? "+" : ""}
                      {fmtMoney(x.actual_net)}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums font-medium">{fmtMoney(x.actual_balance)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}
      </Card>

      <div className="text-[11px] text-muted-foreground">{report.data?.boundary ?? plan.data?.boundary}</div>
    </div>
  );
}

export function EnterprisePlanPanel() {
  const { t } = useI18n();
  const periods = usePlanPeriods();
  const [tab, setTab] = useState<"budget" | "cash">("budget");
  const [period, setPeriod] = useState("");

  useEffect(() => {
    const list = periods.data?.periods ?? [];
    if (!period && list.length) setPeriod(list[0]);
    if (period && list.length && !list.includes(period)) setPeriod(list[0]);
  }, [period, periods.data]);

  if (periods.isLoading) {
    return <div className="h-40 animate-pulse rounded-xl bg-muted/30" />;
  }

  const list = periods.data?.periods ?? [];

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-lg font-semibold tracking-tight">{t("plan.title")}</div>
          <div className="mt-0.5 text-[11px] text-muted-foreground">{t("plan.subtitle")}</div>
        </div>
        <div className="flex items-center gap-2">
          <select className={cn(inputCls, "w-auto")} value={period} onChange={(e) => setPeriod(e.target.value)}>
            {list.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          <Button
            variant="ghost"
            size="sm"
            className="h-8 px-2"
            onClick={() => periods.refetch()}
            title={t("plan.refresh")}
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      <Segmented
        value={tab}
        onChange={setTab}
        options={[
          { value: "budget", label: t("plan.tabBudget") },
          { value: "cash", label: t("plan.tabCash") },
        ]}
      />

      {!period ? (
        <EmptyState title={t("plan.noPeriod")} desc={t("plan.noPeriodHint")} className="py-10" />
      ) : tab === "budget" ? (
        <BudgetBody period={period} />
      ) : (
        <CashBody period={period} />
      )}
    </div>
  );
}

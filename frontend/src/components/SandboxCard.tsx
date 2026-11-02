/** 反事实沙盒卡（M5.5）：「如果少花/多存/改定投/一次性支出，会怎样」。
 *
 * 交互：选情景 → 填参数 → 算一次 → 并排看变更前/变更后与差值。
 * 结果全部来自后端确定性引擎，前端不做任何二次推算。
 */

import { useState } from "react";
import { FlaskConical, Loader2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Segmented } from "@/components/ui/segmented";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { fmtMoney, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useSandbox, useSandboxBase, type SandboxResult } from "@/lib/use-strategy";

type Kind = "less_spend" | "save_more" | "dca_change" | "one_off";

const KINDS: Kind[] = ["less_spend", "save_more", "dca_change", "one_off"];

function Row({
  label,
  before,
  after,
  diff,
  fmt,
}: {
  label: string;
  before: string;
  after: string;
  diff: string;
  fmt?: (v: string) => string;
}) {
  const render = fmt ?? ((v: string) => v);
  return (
    <div className="grid grid-cols-4 items-center gap-1 border-b border-border/40 py-1.5 text-[11.5px] last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right tabular-nums">{render(before)}</span>
      <span className="text-right font-medium tabular-nums">{render(after)}</span>
      <span className="text-right tabular-nums">{render(diff)}</span>
    </div>
  );
}

export function SandboxCard() {
  const { t } = useI18n();
  const { toast } = useToast();
  const [kind, setKind] = useState<Kind>("save_more");
  const [category, setCategory] = useState("餐饮");
  const base = useSandboxBase(kind === "less_spend" ? category : "");
  const run = useSandbox();
  const [amount, setAmount] = useState("2000");
  const [percent, setPercent] = useState("10");
  const [result, setResult] = useState<SandboxResult | null>(null);

  const submit = async () => {
    try {
      const res = await run.mutateAsync({
        kind,
        amount: Number(amount) || 0,
        percent: Number(percent) || 0,
        category: kind === "less_spend" ? category : "",
      });
      setResult(res);
      if (!res.available) toast(res.reason || t("sandbox.unavailable"), "info");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const money = (v: string) => (v === "-" ? v : v);
  return (
    <Card className="min-w-0 p-[var(--card-pad)]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-[13px] font-semibold">
          <FlaskConical className="h-4 w-4 text-primary" />
          {t("sandbox.title")}
        </div>
        <span className="text-[10.5px] text-muted-foreground">{t("sandbox.subtitle")}</span>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <Segmented
          size="sm"
          value={kind}
          onChange={(v) => {
            setKind(v);
            setResult(null);
          }}
          options={KINDS.map((k) => ({ value: k, label: t(`sandbox.kind.${k}`) }))}
        />
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        {kind === "less_spend" ? (
          <>
            <input
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder={t("sandbox.categoryPh")}
              className="w-28 rounded-md border border-border bg-background px-2 py-1.5 text-[12px]"
            />
            <div className="flex items-center gap-1 text-[12px]">
              <input
                value={percent}
                onChange={(e) => setPercent(e.target.value)}
                inputMode="decimal"
                className="w-16 rounded-md border border-border bg-background px-2 py-1.5 text-[12px] tabular-nums"
              />
              <span className="text-muted-foreground">%</span>
            </div>
          </>
        ) : (
          <div className="flex items-center gap-1 text-[12px]">
            <span className="text-muted-foreground">
              {kind === "one_off" ? t("sandbox.oneOffAmount") : t("sandbox.monthlyAmount")}
            </span>
            <input
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              inputMode="decimal"
              className="w-24 rounded-md border border-border bg-background px-2 py-1.5 text-[12px] tabular-nums"
            />
          </div>
        )}
        <Button size="sm" disabled={run.isPending} onClick={() => void submit()}>
          {run.isPending ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
          {t("sandbox.run")}
        </Button>
        {base.data ? (
          <span className="text-[10.5px] text-muted-foreground">
            {t("sandbox.baseline", {
              income: fmtMoney(base.data.monthly_income),
              expense: fmtMoney(base.data.monthly_expense),
              cash: fmtMoney(base.data.cash),
            })}
          </span>
        ) : null}
      </div>

      {result && !result.available ? (
        <p className="mt-2 text-[11.5px] text-amber-600 dark:text-amber-400">{result.reason}</p>
      ) : null}

      {result?.available ? (
        <div className="mt-2 border-t border-border/60 pt-2">
          <div className="grid grid-cols-4 gap-1 pb-1 text-[10.5px] text-muted-foreground">
            <span />
            <span className="text-right">{t("sandbox.before")}</span>
            <span className="text-right">{t("sandbox.after")}</span>
            <span className="text-right">{t("sandbox.diff")}</span>
          </div>
          <Row
            label={t("sandbox.rows.net")}
            before={fmtMoney(result.before.monthly_net)}
            after={fmtMoney(result.after.monthly_net)}
            diff={fmtMoney(result.diff.monthly_net ?? null, true)}
            fmt={money}
          />
          <Row
            label={t("sandbox.rows.savings")}
            before={fmtPct(result.before.savings_rate_pct)}
            after={fmtPct(result.after.savings_rate_pct)}
            diff={fmtPct(result.diff.savings_rate_pct ?? null, true)}
            fmt={money}
          />
          <Row
            label={t("sandbox.rows.emergency")}
            before={result.before.emergency_months != null ? `${result.before.emergency_months} 月` : "-"}
            after={result.after.emergency_months != null ? `${result.after.emergency_months} 月` : "-"}
            diff={result.diff.emergency_months != null ? `${result.diff.emergency_months >= 0 ? "+" : ""}${result.diff.emergency_months}` : "-"}
          />
          <Row
            label={t("sandbox.rows.fire")}
            before={result.before.fire_years != null ? `${result.before.fire_years} 年` : "-"}
            after={result.after.fire_years != null ? `${result.after.fire_years} 年` : "-"}
            diff={
              result.diff.fire_years != null
                ? `${result.diff.fire_years >= 0 ? "+" : ""}${result.diff.fire_years}`
                : "-"
            }
          />
          {result.warnings.length ? (
            <div className="mt-1.5 space-y-0.5">
              {result.warnings.map((w) => (
                <div key={w} className="text-[10.5px] text-amber-600 dark:text-amber-400">
                  {w}
                </div>
              ))}
            </div>
          ) : null}
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <Badge variant="muted" className="px-1.5 py-0 text-[10px]">
              {t("sandbox.assumeReturn", { r: (result.assumptions.annual_return * 100).toFixed(1) })}
            </Badge>
            <Badge variant="muted" className="px-1.5 py-0 text-[10px]">
              {t("sandbox.assumeWithdraw", { w: (result.assumptions.withdrawal_rate * 100).toFixed(1) })}
            </Badge>
            <span className={cn("text-[10px] text-muted-foreground")}>{result.disclaimer}</span>
          </div>
        </div>
      ) : null}
    </Card>
  );
}

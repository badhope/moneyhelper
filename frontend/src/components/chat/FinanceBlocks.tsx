import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, BarChart3, ChevronDown, TrendingUp, Wallet } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { fmtMoney, fmtPct, pnlClass } from "@/lib/format";
import { api } from "@/lib/api";
import { MiniSparkline } from "@/components/MiniSparkline";
import type { KlinePoint } from "@/components/KlineDialog";

/**
 * 对话内嵌的富回答块（替代原来的静态四宫格）。
 *
 * 设计取舍：通用助手在回答里放的是纯文本，财务场景真正的价值在数字结构。
 * 这里把后端已经算好的 market / ledger / flags 渲染成可操作块——点持仓展开走势、
 * 点分类或风险项跳到对应页面。数据全部来自后端确定性内核，不在这里重算。
 */

interface Position {
  symbol: string;
  name: string;
  kind: string;
  market_value: number;
  pnl: number;
  pnl_pct: number;
}

interface Breach {
  name?: string;
  industry?: string;
  pct: number;
  /** 相对可投资资产（非现金）的占比；集中度判定与展示用它 */
  investable_pct?: number;
}

export interface FinanceCardData {
  route?: string;
  market?: {
    positions?: Position[];
    total_market_value?: number;
    total_pnl?: number;
    total_pnl_pct?: number;
    concentration?: {
      threshold_pct?: number;
      by_asset?: { name: string; pct: number }[];
      asset_breaches?: Breach[];
      industry_breaches?: Breach[];
    };
  } | null;
  ledger?: {
    month?: string;
    income?: number;
    expense?: number;
    net?: number;
    savings_rate?: number;
    by_category?: { category: string; amount: number }[];
  } | null;
  flags?: { level: string; code: string; text: string }[];
}

/** 持仓块：市值 + 盈亏 + 前三大持仓（可展开看 60 日走势） */
export function HoldingsCard({
  data,
  onNavigate,
}: {
  data: FinanceCardData;
  onNavigate: (tab: string) => void;
}) {
  const { t } = useI18n();
  const m = data.market;
  if (!m) return null;
  const positions = (m.positions ?? []).filter((p) => p.kind !== "现金").slice(0, 3);
  const total = m.total_market_value ?? 0;
  const pnl = m.total_pnl ?? 0;
  const pct = m.total_pnl_pct ?? 0;
  const breaches = [
    ...(m.concentration?.asset_breaches ?? []),
    ...(m.concentration?.industry_breaches ?? []),
  ];
  const threshold = m.concentration?.threshold_pct ?? 40;

  return (
    <div className="rounded-2xl border border-border bg-card">
      <div className="flex items-start justify-between gap-2 border-b border-border/60 px-3.5 py-2.5">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Wallet className="h-3.5 w-3.5" />
            {t("block.holdings")}
          </div>
          <div className="mt-0.5 flex items-baseline gap-2">
            <span className="text-lg font-semibold tabular-nums">{fmtMoney(total, false, true)}</span>
            <span className={cn("text-xs tabular-nums", pnlClass(pnl))}>
              {fmtMoney(pnl, true, true)} · {fmtPct(pct, true)}
            </span>
          </div>
        </div>
        <button
          type="button"
          onClick={() => onNavigate("holdings")}
          className="inline-flex shrink-0 items-center gap-0.5 rounded-md px-1.5 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          {t("block.open")} <ArrowRight className="h-3 w-3" />
        </button>
      </div>

      <ul className="divide-y divide-border/50">
        {positions.map((p) => (
          <HoldingRow key={p.symbol} p={p} />
        ))}
      </ul>

      {breaches.length > 0 && (
        <div className="flex items-start gap-1.5 border-t border-amber-500/20 bg-amber-500/[0.06] px-3.5 py-2 text-[11px] text-amber-700 dark:text-amber-400">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
          <span className="min-w-0">
            {breaches.slice(0, 2).map((b, i) => (
              <span key={i} className="mr-2">
                {/* 集中度必须用 investable_pct（相对可投资资产），
                    用 pct（相对总市值）会与正文里的 63.6% 打架 */}
                {b.name ?? b.industry}{" "}
                <b className="tabular-nums">{b.investable_pct ?? b.pct}%</b>
              </span>
            ))}
            <span className="text-muted-foreground">{t("block.overThreshold", { n: threshold })}</span>
          </span>
        </div>
      )}
    </div>
  );
}

function HoldingRow({ p }: { p: Position }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  // 与后端 quotes._to_secid 对齐：只有 6 位沪深代码有 K 线，场外基金/现金不发请求
  const supported = /^\d{6}$/.test(p.symbol);
  const q = useQuery({
    queryKey: ["/api/kline", p.symbol, "block"],
    queryFn: () =>
      api<{ points: KlinePoint[] }>(
        `/api/kline?symbol=${encodeURIComponent(p.symbol)}&period=daily&limit=60`,
      ),
    staleTime: 5 * 60_000,
    retry: 0,
    enabled: open && supported,
  });

  return (
    <li className="px-3.5 py-2">
      <button
        type="button"
        onClick={() => supported && setOpen((v) => !v)}
        className="flex w-full items-center gap-2 text-left"
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px]">{p.name}</span>
          <span className="block text-[11px] text-muted-foreground">
            {p.symbol} · {p.kind}
          </span>
        </span>
        <span className={cn("shrink-0 text-right text-[13px] tabular-nums", pnlClass(p.pnl))}>
          {fmtMoney(p.pnl, true, true)}
          <span className="ml-1 text-[11px]">{fmtPct(p.pnl_pct, true)}</span>
        </span>
        {supported && (
          <ChevronDown
            className={cn(
              "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
              open && "rotate-180",
            )}
          />
        )}
      </button>
      {open && (
        <div className="mt-2">
          {q.isPending ? (
            <div className="h-12 animate-pulse rounded bg-muted" />
          ) : (q.data?.points?.length ?? 0) > 1 ? (
            <MiniSparkline points={q.data!.points} className="h-12 w-full" />
          ) : (
            <p className="text-[11px] text-muted-foreground">{t("block.noKline")}</p>
          )}
        </div>
      )}
    </li>
  );
}

/** 收支块：四项指标 + 分类条形 */
export function LedgerCard({
  data,
  onNavigate,
}: {
  data: FinanceCardData;
  onNavigate: (tab: string) => void;
}) {
  const { t } = useI18n();
  const l = data.ledger;
  if (!l) return null;
  const cats = (l.by_category ?? []).slice(0, 5);
  const max = Math.max(...cats.map((c) => c.amount), 1);

  return (
    <div className="rounded-2xl border border-border bg-card">
      <div className="flex items-start justify-between gap-2 border-b border-border/60 px-3.5 py-2.5">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <BarChart3 className="h-3.5 w-3.5" />
            {t("block.ledger")} {l.month ? `· ${l.month}` : ""}
          </div>
          <div className="mt-1 grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px] sm:grid-cols-4">
            <span className="text-muted-foreground">
              {t("block.income")}{" "}
              <b className="ml-1 tabular-nums text-up">{fmtMoney(l.income ?? 0, false, true)}</b>
            </span>
            <span className="text-muted-foreground">
              {t("block.expense")}{" "}
              <b className="ml-1 tabular-nums text-down">{fmtMoney(l.expense ?? 0, false, true)}</b>
            </span>
            <span className="text-muted-foreground">
              {t("block.net")} <b className="ml-1 tabular-nums">{fmtMoney(l.net ?? 0, true, true)}</b>
            </span>
            <span className="text-muted-foreground">
              {t("block.savings")} <b className="ml-1 tabular-nums">{l.savings_rate ?? 0}%</b>
            </span>
          </div>
        </div>
        <button
          type="button"
          onClick={() => onNavigate("ledger")}
          className="inline-flex shrink-0 items-center gap-0.5 rounded-md px-1.5 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          {t("block.open")} <ArrowRight className="h-3 w-3" />
        </button>
      </div>

      {cats.length > 0 && (
        <ul className="space-y-1.5 px-3.5 py-2.5">
          {cats.map((c) => (
            <li key={c.category} className="flex items-center gap-2">
              <span className="w-16 shrink-0 truncate text-[11px] text-muted-foreground">
                {c.category}
              </span>
              <span className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-muted">
                <span
                  className="block h-full rounded-full bg-primary/70"
                  style={{ width: `${Math.max(4, (c.amount / max) * 100)}%` }}
                />
              </span>
              <span className="w-16 shrink-0 text-right text-[11px] tabular-nums">
                {fmtMoney(c.amount, false, true)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** 风险块：flag 列表 + 处置入口 */
export function RiskCard({
  data,
  onNavigate,
}: {
  data: FinanceCardData;
  onNavigate: (tab: string) => void;
}) {
  const { t } = useI18n();
  const flags = data.flags ?? [];
  if (flags.length === 0) return null;
  // 集中度超限已在持仓块底部提示过，这里跳过，避免同一句话出现两遍
  const shown = flags.filter((f) => !f.code.includes("CONCENTRATION")).slice(0, 4);
  if (shown.length === 0) return null;
  const target = (code: string) =>
    code.includes("CONCENTRATION") ? "holdings" : code.includes("DEBT") ? "ledger" : "health";
  return (
    <div className="rounded-2xl border border-border bg-card">
      <div className="flex items-center gap-1.5 border-b border-border/60 px-3.5 py-2.5 text-[11px] text-muted-foreground">
        <TrendingUp className="h-3.5 w-3.5" />
        {t("block.risks", { n: shown.length })}
      </div>
      <ul className="divide-y divide-border/50">
        {shown.map((f, i) => (
          <li key={i} className="flex items-start gap-2 px-3.5 py-2">
            <span
              className={cn(
                "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full",
                f.level === "error"
                  ? "bg-red-500"
                  : f.level === "warn"
                    ? "bg-amber-500"
                    : "bg-emerald-500",
              )}
            />
            <span className="min-w-0 flex-1 text-[12px] leading-relaxed text-foreground/80">
              {f.text}
            </span>
            <button
              type="button"
              onClick={() => onNavigate(target(f.code))}
              className="shrink-0 text-[11px] text-primary hover:underline"
            >
              {t("block.fix")}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** 组合入口：一个 card 可能同时带 market/ledger/flags，按实际数据渲染对应块 */
export function FinanceBlocks({
  data,
  onNavigate,
}: {
  data: FinanceCardData;
  onNavigate: (tab: string) => void;
}) {
  const hasMarket = Boolean(data.market);
  const hasLedger = Boolean(data.ledger);
  const hasFlags = (data.flags ?? []).length > 0;
  if (!hasMarket && !hasLedger && !hasFlags) return null;
  return (
    <div className="mt-3 space-y-2">
      {hasMarket && <HoldingsCard data={data} onNavigate={onNavigate} />}
      {hasLedger && <LedgerCard data={data} onNavigate={onNavigate} />}
      {hasFlags && <RiskCard data={data} onNavigate={onNavigate} />}
    </div>
  );
}

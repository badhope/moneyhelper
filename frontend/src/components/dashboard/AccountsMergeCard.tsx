import { useQuery } from "@tanstack/react-query";
import { Layers, Info } from "lucide-react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { fmtMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * 多账户合并卡：把「本地账本 / 模拟盘 / 实盘」汇总成一个可解释的净资产。
 *
 * 为什么需要：用户的钱分散在三处，此前每个模块只报自己那份，加总靠心算。
 * 这里刻意把「计入/不计入」显式标出来——外币账户不做汇率猜测，
 * 宁可显示"未折算"也不编一个数；重叠风险用口头警示而不是替用户做决定。
 */

type AccountSource = {
  key: string;
  name: string;
  net_worth: number;
  counted: boolean;
  detail: string;
  currency?: string;
  market_value?: number;
  cash?: number;
  debt?: number;
  initial_cash?: number;
};

type AccountsOverview = {
  total_net_worth: number;
  local_net: number;
  paper_total: number;
  broker_total: number;
  account_count: number;
  sources: AccountSource[];
  caveats: string[];
};

export function AccountsMergeCard() {
  const { t, lang } = useI18n();
  const l = lang?.startsWith("en") ? "en" : "zh";
  const q = useQuery({
    queryKey: ["accounts-overview", l],
    queryFn: () => api<AccountsOverview>(`/api/paper/bridge/accounts-overview?lang=${l}`),
    retry: false,
    staleTime: 30_000,
  });

  const data = q.data;
  if (!data || !data.sources?.length) return null;
  // 只有一个本地账本时，这张卡与上方净值卡完全重复——不显示，
  // 把版面留给真正有信息量的内容。只有接入模拟盘/实盘后才出现。
  if (data.account_count <= 1) return null;
  const compact = true;

  return (
    <section className="rounded-xl border border-border/70 bg-card">
      <header className="flex items-center justify-between gap-2 border-b border-border/60 px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          <Layers className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-medium">{t("accounts.title")}</h2>
          <span className="rounded-full bg-foreground/[0.06] px-1.5 py-0.5 text-[10.5px] text-muted-foreground">
            {t("accounts.count", { n: data.account_count })}
          </span>
        </div>
      </header>

      <div className="px-4 py-3">
        <div className="mb-3">
          <div className="text-[11.5px] text-muted-foreground">{t("accounts.total")}</div>
          <div className="text-2xl font-semibold tabular-nums">
            {fmtMoney(data.total_net_worth, false, compact)}
          </div>
        </div>

        <ul className="divide-y divide-border/50">
          {data.sources.map((s) => (
            <li key={s.key} className="flex items-center gap-2 py-1.5">
              <span
                className={cn(
                  "h-1.5 w-1.5 shrink-0 rounded-full",
                  s.counted ? "bg-primary" : "bg-muted-foreground/40",
                )}
              />
              <span className={cn("min-w-0 flex-1 truncate text-[13px]", !s.counted && "text-muted-foreground")}>
                {s.name}
              </span>
              <span
                className={cn(
                  "shrink-0 tabular-nums text-[13px]",
                  s.counted ? "text-foreground" : "text-muted-foreground line-through decoration-muted-foreground/30",
                )}
              >
                {fmtMoney(s.net_worth, false, compact)}
                {s.currency && s.currency !== "CNY" && (
                  <span className="ml-1 text-[10.5px]">{s.currency}</span>
                )}
              </span>
            </li>
          ))}
        </ul>

        {data.caveats.length > 0 && (
          <div className="mt-3 flex gap-1.5 rounded-lg bg-amber-500/[0.06] px-2.5 py-2 text-[11.5px] leading-relaxed text-amber-900 dark:text-amber-200">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <div className="space-y-1">
              {data.caveats.map((c, i) => (
                <p key={i}>{c}</p>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

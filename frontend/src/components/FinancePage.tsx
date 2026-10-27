import { lazy, Suspense } from "react";
import { CandlestickChart, FileText, HeartPulse, LayoutGrid, NotebookPen, Target, TrendingUp, Users, Wallet } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const Dashboard = lazy(() =>
  import("@/components/Dashboard").then((m) => ({ default: m.Dashboard })),
);
const HoldingsView = lazy(() =>
  import("@/components/HoldingsView").then((m) => ({ default: m.HoldingsView })),
);
const MarketView = lazy(() =>
  import("@/components/MarketView").then((m) => ({ default: m.MarketView })),
);
const EntryView = lazy(() =>
  import("@/components/EntryView").then((m) => ({ default: m.EntryView })),
);
const HealthBody = lazy(() =>
  import("@/components/HealthPage").then((m) => ({ default: m.HealthPage })),
);
const StrategyBody = lazy(() =>
  import("@/components/StrategyPage").then((m) => ({ default: m.StrategyPage })),
);
const ResearchBody = lazy(() =>
  import("@/components/ResearchPage").then((m) => ({ default: m.ResearchPage })),
);
const StatementsBody = lazy(() =>
  import("@/components/StatementsPage").then((m) => ({ default: m.StatementsPage })),
);
const PaperBody = lazy(() =>
  import("@/components/PaperTradingPage").then((m) => ({ default: m.PaperTradingPage })),
);

export type DataKind = "overview" | "holdings" | "market" | "ledger" | "health" | "strategy" | "research" | "statements" | "paper";

const TABS: { key: DataKind; labelKey: string; icon: typeof LayoutGrid }[] = [
  { key: "overview", labelKey: "nav.dashboard", icon: LayoutGrid },
  { key: "holdings", labelKey: "nav.holdings", icon: Wallet },
  { key: "research", labelKey: "nav.research", icon: CandlestickChart },
  { key: "statements", labelKey: "nav.statements", icon: FileText },
  { key: "paper", labelKey: "nav.paper", icon: Users },
  { key: "strategy", labelKey: "nav.strategy", icon: Target },
  { key: "market", labelKey: "nav.market", icon: TrendingUp },
  { key: "ledger", labelKey: "nav.ledger", icon: NotebookPen },
  { key: "health", labelKey: "hc.title", icon: HeartPulse },
];

/**
 * 财务工作区：整页视图（对标 opencode / codex 的 section 切换）。
 *
 * 为什么不再是右侧抽屉：数据页本身是多列表格 + 图表，塞进 440px 侧栏会出现
 * 数字折行、两列挤压。这里保留左侧导航不动，主区整页切换，内容按 1200px 居中，
 * 桌面可展开多列，窄屏自动收敛为单列。
 */
export function FinancePage({
  kind,
  onKindChange,
}: {
  kind: DataKind;
  onKindChange: (k: DataKind) => void;
}) {
  const { t } = useI18n();

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-border/70">
        <div className="mx-auto flex w-full max-w-6xl items-center gap-1 overflow-x-auto px-4 sm:px-6">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const active = tab.key === kind;
            return (
              <button
                key={tab.key}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => onKindChange(tab.key)}
                className={cn(
                  "relative -mb-px flex shrink-0 items-center gap-1.5 border-b-2 px-2.5 py-3 text-[13px] transition-colors sm:px-3 sm:text-[13.5px]",
                  active
                    ? "border-foreground font-medium text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                <Icon className="hidden h-4 w-4 sm:block" />
                {t(tab.labelKey)}
              </button>
            );
          })}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto scroll-thin">
        <div className="@container mx-auto w-full max-w-6xl px-4 py-5 sm:px-6">
          <Suspense
            fallback={
              <div className="py-16 text-center text-sm text-muted-foreground">
                {t("app.preparing")}
              </div>
            }
          >
            {kind === "overview" && <Dashboard />}
            {kind === "holdings" && <HoldingsView />}
            {kind === "research" && <ResearchBody />}
            {kind === "statements" && <StatementsBody />}
            {kind === "paper" && <PaperBody />}
            {kind === "strategy" && <StrategyBody />}
            {kind === "market" && <MarketView />}
            {kind === "ledger" && <EntryView />}
            {kind === "health" && <HealthBody />}
          </Suspense>
        </div>
      </div>
    </div>
  );
}

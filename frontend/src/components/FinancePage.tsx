import { lazy, Suspense } from "react";
import { CandlestickChart, CreditCard, FileText, HeartPulse, LayoutGrid, NotebookPen, Plug, Receipt, Target, TrendingUp, Users, Wallet } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { GroupedNav, type NavGroup } from "@/components/ui/grouped-nav";

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
const ConnectBody = lazy(() =>
  import("@/components/ConnectPage").then((m) => ({ default: m.ConnectPage })),
);
const TaxBody = lazy(() =>
  import("@/components/TaxPage").then((m) => ({ default: m.TaxPage })),
);
const DebtPayoffBody = lazy(() =>
  import("@/components/DebtPayoffPage").then((m) => ({ default: m.DebtPayoffPage })),
);

export type DataKind = "overview" | "holdings" | "market" | "ledger" | "health" | "strategy" | "research" | "statements" | "paper" | "connect" | "tax" | "debts";

/**
 * 分组：按用户的心智模型收纳，而不是按功能清单平铺。
 *
 *   daily   每天都会看：总览、持仓、记账
 *   analyze 需要判断时看：行情、投研、策略、体检
 *   books   记账算账时才进：财报、税负、模拟盘
 *   connect 一次性配置：连接中心
 *
 * 原来 11 个 tab 同级平铺，用户每次都要线性扫一遍；分组后每屏只看到
 * 3-4 项，且「日常」与「配置」在视觉上分开，不会把一次性动作误当高频动作。
 */
const GROUPS: NavGroup<DataKind>[] = [
  {
    id: "daily",
    labelKey: "nav.groupDaily",
    items: [
      { key: "overview", labelKey: "nav.dashboard", icon: LayoutGrid },
      { key: "holdings", labelKey: "nav.holdings", icon: Wallet },
      { key: "ledger", labelKey: "nav.ledger", icon: NotebookPen },
      { key: "debts", labelKey: "nav.debts", icon: CreditCard },
    ],
  },
  {
    id: "analyze",
    labelKey: "nav.groupAnalyze",
    items: [
      { key: "market", labelKey: "nav.market", icon: TrendingUp },
      { key: "research", labelKey: "nav.research", icon: CandlestickChart },
      { key: "strategy", labelKey: "nav.strategy", icon: Target },
      { key: "health", labelKey: "hc.title", icon: HeartPulse },
    ],
  },
  {
    id: "books",
    labelKey: "nav.groupBooks",
    items: [
      { key: "statements", labelKey: "nav.statements", icon: FileText },
      { key: "tax", labelKey: "nav.tax", icon: Receipt },
      { key: "paper", labelKey: "nav.paper", icon: Users },
    ],
  },
  {
    id: "connect",
    labelKey: "nav.groupConnect",
    items: [{ key: "connect", labelKey: "nav.connect", icon: Plug }],
  },
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
  onGoChat,
  onGoSettings,
}: {
  kind: DataKind;
  onKindChange: (k: DataKind) => void;
  /** 回对话页（空态「问 AI」按钮用） */
  onGoChat?: () => void;
  /** 打开设置（空态/引导用） */
  onGoSettings?: () => void;
}) {
  const { t } = useI18n();

  return (
    <div className="flex h-full min-h-0 flex-col">
      <GroupedNav groups={GROUPS} value={kind} onChange={onKindChange} />

      <div className="min-h-0 flex-1 overflow-y-auto scroll-thin">
        <div className="@container mx-auto w-full max-w-6xl px-4 py-5 sm:px-6">
          <Suspense
            fallback={
              <div className="py-16 text-center text-sm text-muted-foreground">
                {t("app.preparing")}
              </div>
            }
          >
            {kind === "overview" && (
              <Dashboard
                // 空态三个主按钮必须有真实去处：此前 FinancePage 没传这几个
                // 回调，新用户点「去记账 / 添加持仓 / 问 AI」全部无反应，
                // 直接卡死首启转化。
                onGoLedger={() => onKindChange("ledger")}
                onGoMarket={() => onKindChange("market")}
                onGoChat={onGoChat}
                onGoSettings={onGoSettings}
                onNavigateTab={(tab) => {
                  const known: DataKind[] = ["overview", "holdings", "market", "ledger", "health",
                    "strategy", "research", "statements", "paper", "connect", "tax", "debts"];
                  if (known.includes(tab as DataKind)) onKindChange(tab as DataKind);
                }}
              />
            )}
            {kind === "holdings" && <HoldingsView onGoMarket={() => onKindChange("market")} />}
            {kind === "connect" && <ConnectBody />}
            {kind === "tax" && <TaxBody />}
            {kind === "research" && <ResearchBody />}
            {kind === "statements" && <StatementsBody />}
            {kind === "paper" && <PaperBody />}
            {kind === "strategy" && <StrategyBody />}
            {kind === "market" && <MarketView />}
            {kind === "ledger" && <EntryView />}
            {kind === "health" && <HealthBody />}
            {kind === "debts" && <DebtPayoffBody onGoLedger={() => onKindChange("ledger")} />}
          </Suspense>
        </div>
      </div>
    </div>
  );
}

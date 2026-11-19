import { lazy, Suspense } from "react";
import { isDataKind, type DataKind } from "@/lib/views";
import { useI18n } from "@/lib/i18n";
import { GroupedNav } from "@/components/ui/grouped-nav";
import { NAV_GROUPS } from "@/lib/nav";

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
const GlBody = lazy(() =>
  import("@/components/GlPage").then((m) => ({ default: m.GlPage })),
);
const ExpensesBody = lazy(() =>
  import("@/components/ExpensesPage").then((m) => ({ default: m.ExpensesPage })),
);
const BankBody = lazy(() =>
  import("@/components/BankPage").then((m) => ({ default: m.BankPage })),
);
const LongTaskBody = lazy(() =>
  import("@/components/LongTaskPage").then((m) => ({ default: m.LongTaskPage })),
);
const ProcurementBody = lazy(() =>
  import("@/components/ProcurementPage").then((m) => ({
    default: m.ProcurementPage,
  })),
);

export type { DataKind } from "@/lib/views";


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
      <GroupedNav groups={NAV_GROUPS} value={kind} onChange={onKindChange} />

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
                  if (isDataKind(tab)) onKindChange(tab);
                }}
              />
            )}
            {kind === "holdings" && <HoldingsView onGoMarket={() => onKindChange("market")} />}
            {kind === "connect" && <ConnectBody />}
            {kind === "tax" && <TaxBody />}
            {kind === "research" && <ResearchBody />}
            {kind === "statements" && <StatementsBody />}
            {kind === "gl" && <GlBody />}
            {kind === "expenses" && <ExpensesBody />}
            {kind === "procurement" && <ProcurementBody />}
            {kind === "longtask" && <LongTaskBody />}
            {kind === "bank" && <BankBody />}
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

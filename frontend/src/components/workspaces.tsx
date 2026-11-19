import { Suspense, lazy, useState } from "react";
import { PillTabs } from "@/components/ui/pill-tabs";
import { useI18n } from "@/lib/i18n";

/**
 * 工作区：把"同一件事的几个视角"合成一页。
 *
 * 现状问题：左侧导航把「总账 / 财报 / 公司财税」并列成三个入口，用户点进去看到的是
 * 三套独立的页面标题、三份期间说明，但本质是同一条账务链路的三个视角；
 * 「报销 / 采购应付」同理（都是单据），「投研 / 投资策略」同理。
 *
 * 这里的做法**不动 DataKind**：三个入口仍然存在（对话跳转、深链、e2e 都依赖它），
 * 但点进去都落到同一个工作区，只有顶部 tab 的默认选中项不同。于是用户感知是
 * "一个账务页，三个视图"，而不是"三个互不相干的页面"。
 *
 * 为什么不直接删掉两个 DataKind：它们出现在对话路由、MCP 工具约定与既有分享链接里，
 * 删掉等于破坏对外契约；合并的收益是界面心智，不值得用契约去换。
 */

const GlBody = lazy(() => import("@/components/GlPage").then((m) => ({ default: m.GlPage })));
const StatementsBody = lazy(() =>
  import("@/components/StatementsPage").then((m) => ({ default: m.StatementsPage })),
);
const TaxBody = lazy(() => import("@/components/TaxPage").then((m) => ({ default: m.TaxPage })));
const ExpensesBody = lazy(() =>
  import("@/components/ExpensesPage").then((m) => ({ default: m.ExpensesPage })),
);
const ProcurementBody = lazy(() =>
  import("@/components/ProcurementPage").then((m) => ({ default: m.ProcurementPage })),
);
const ResearchBody = lazy(() =>
  import("@/components/ResearchPage").then((m) => ({ default: m.ResearchPage })),
);
const StrategyBody = lazy(() =>
  import("@/components/StrategyPage").then((m) => ({ default: m.StrategyPage })),
);

function Frame({
  initial,
  tabs,
 bodies,
}: {
  initial: string;
  tabs: { value: string; label: string }[];
  bodies: Record<string, React.ReactNode>;
}) {
  const [tab, setTab] = useState(initial);
  return (
    <div className="flex flex-col gap-3">
      {/* 工作区只在"多视角"时才加这行 tab；单视图的页面不受影响 */}
      <PillTabs value={tab} onChange={setTab} options={tabs} />
      <Suspense fallback={<div className="h-40 animate-pulse rounded-xl bg-muted/30" />}>
        {bodies[tab]}
      </Suspense>
    </div>
  );
}

/** 账务：总账 / 财报 / 公司财税 */
export function LedgerWorkspace({ initial }: { initial: "gl" | "statements" | "tax" }) {
  const { t } = useI18n();
  return (
    <Frame
      initial={initial}
      tabs={[
        { value: "gl", label: t("nav.gl") },
        { value: "statements", label: t("nav.statements") },
        { value: "tax", label: t("nav.tax") },
      ]}
      bodies={{ gl: <GlBody />, statements: <StatementsBody />, tax: <TaxBody /> }}
    />
  );
}

/** 单据：报销 / 采购应付 */
export function BillsWorkspace({ initial }: { initial: "expenses" | "procurement" }) {
  const { t } = useI18n();
  return (
    <Frame
      initial={initial}
      tabs={[
        { value: "expenses", label: t("nav.expenses") },
        { value: "procurement", label: t("nav.procurement") },
      ]}
      bodies={{ expenses: <ExpensesBody />, procurement: <ProcurementBody /> }}
    />
  );
}

/** 投研：行情研究 / 投资策略 */
export function DeskWorkspace({ initial }: { initial: "research" | "strategy" }) {
  const { t } = useI18n();
  return (
    <Frame
      initial={initial}
      tabs={[
        { value: "research", label: t("nav.research") },
        { value: "strategy", label: t("nav.strategy") },
      ]}
      bodies={{ research: <ResearchBody />, strategy: <StrategyBody /> }}
    />
  );
}

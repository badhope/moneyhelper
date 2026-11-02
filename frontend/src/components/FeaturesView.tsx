import { useEffect, useRef, useState } from "react";
import { Dashboard } from "@/components/Dashboard";
import { HoldingsView } from "@/components/HoldingsView";
import { MarketView } from "@/components/MarketView";
import { EntryView } from "@/components/EntryView";
import { useI18n } from "@/lib/i18n";
import { PillTabs } from "@/components/ui/pill-tabs";

type FeatureTab = "overview" | "holdings" | "market" | "ledger";

const TABS: { id: FeatureTab; labelKey: string }[] = [
  { id: "overview", labelKey: "nav.dashboard" },
  { id: "holdings", labelKey: "nav.holdings" },
  { id: "market", labelKey: "nav.market" },
  { id: "ledger", labelKey: "nav.ledger" },
];

/** 功能页：总览 / 持仓 / 行情 / 记账 4 个子 tab 合并为一个页面（主导航只暴露「问答」「功能」两项，
 *  要什么功能点进这里再选子 tab）。 */
export function FeaturesView({ initial, onGoChat, onGoSettings, onNavigateTab }: { initial?: FeatureTab; onGoChat?: () => void; onGoSettings?: () => void; onNavigateTab?: (tab: string) => void }) {
  const { t } = useI18n();
  const [sub, setSub] = useState<FeatureTab>(initial ?? "overview");
  // 只在「跳转意图变化」时跟随外部：记录用户是否手动切过，手动切过后不再被 initial 覆盖
  const userTouched = useRef(false);
  const lastInitial = useRef(initial);
  useEffect(() => {
    // initial 引用/值变化且用户尚未手动操作过 → 跟随跳转意图
    if (initial !== lastInitial.current && !userTouched.current && initial) {
      setSub(initial);
      lastInitial.current = initial;
    }
  }, [initial]);
  const pick = (id: FeatureTab) => {
    userTouched.current = true;
    setSub(id);
  };

  return (
    <div>
      {/* 子 tab 切换条 */}
      <div className="mb-3">
        <PillTabs
          value={sub}
          onChange={pick}
          size="md"
          role="tablist"
          label={t("features.title")}
          options={TABS.map((x) => ({ value: x.id, label: t(x.labelKey) }))}
        />
      </div>

      {sub === "overview" && (
        <Dashboard
          onGoLedger={() => pick("ledger")}
          onGoMarket={() => pick("market")}
          onGoChat={onGoChat}
          onGoSettings={onGoSettings}
          onNavigateTab={(tab) => {
            // overview 就是当前页，无需跳转；其余四个子 tab 直接切过去。
            // 非本页管辖的 tab（如 strategy / tax / health）由上层 FinancePage 处理，
            // 这里不吞掉——否则点「去处理」会静默无反应。
            if (tab === "holdings" || tab === "market" || tab === "ledger") {
              pick(tab as FeatureTab);
            } else if (onNavigateTab) {
              onNavigateTab(tab);
            }
          }}
        />
      )}
      {sub === "holdings" && <HoldingsView onGoMarket={() => pick("market")} />}
      {sub === "market" && <MarketView />}
      {sub === "ledger" && <EntryView />}
    </div>
  );
}

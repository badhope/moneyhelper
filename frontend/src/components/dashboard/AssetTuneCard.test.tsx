import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { AssetTuneCard } from "./AssetTuneCard";

vi.mock("@/lib/i18n", () => ({
  useI18n: () => ({ t: (k: string) => k }),
}));

const data = {
  count: 2,
  boundary: "只给候选，不代下单",
  metrics: {
    emergency_months: 1.5,
    emergency_target_months: 3,
    non_cash_value: 60000,
    high_rate_debts: 1,
    rebalance_needed: true,
    rebalance_max_drift_pct: 10,
    rebalance_notes: [],
  },
  candidates: [
    {
      kind: "liquidity" as const,
      priority: 10,
      title: "应急金不足",
      detail: "缺口约 6000",
      impact: "避免被迫卖出",
      risk: "现金收益下降",
      amount: 6000,
      symbol: "",
      action_tab: "holdings",
      confidence: "high",
      requires_confirmation: true,
    },
    {
      kind: "savings" as const,
      priority: 30,
      title: "储蓄率偏低",
      detail: "每月多存 1500",
      impact: "增强韧性",
      risk: "压缩消费",
      amount: 1500,
      symbol: "",
      action_tab: "overview",
      confidence: "medium",
      requires_confirmation: true,
    },
  ],
};

describe("AssetTuneCard", () => {
  it("无候选时不渲染", () => {
    const { container } = render(<AssetTuneCard data={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("展示候选、风险与跳转", () => {
    const onNavigate = vi.fn();
    render(<AssetTuneCard data={data} onNavigate={onNavigate} />);
    expect(screen.getByText("assetTune.title")).toBeInTheDocument();
    expect(screen.getByText("应急金不足")).toBeInTheDocument();
    expect(screen.getByText("现金收益下降")).toBeInTheDocument();
    fireEvent.click(screen.getAllByText("assetTune.go")[0]);
    expect(onNavigate).toHaveBeenCalledWith("holdings");
    expect(screen.getByText("只给候选，不代下单")).toBeInTheDocument();
  });
});

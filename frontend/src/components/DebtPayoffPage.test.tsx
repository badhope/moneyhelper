import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/dom";
import { DebtPayoffPage } from "./DebtPayoffPage";
import type { PayoffPlan } from "@/lib/use-payoff";

const mockUsePayoffPlan = vi.fn();

vi.mock("@/lib/use-payoff", () => ({
  usePayoffPlan: (...args: unknown[]) => mockUsePayoffPlan(...args),
}));

vi.mock("@/lib/i18n", () => ({
  useI18n: () => ({
    t: (k: string, vars?: Record<string, string | number>) =>
      vars ? `${k}:${Object.values(vars).join("/")}` : k,
  }),
}));

/** 与后端 to_dict() 同形状的最小计划 */
function plan(overrides: Partial<PayoffPlan> = {}): PayoffPlan {
  return {
    available: true,
    method: "avalanche",
    order: ["信用卡", "消费贷"],
    monthly_budget: 4500,
    extra_payment: 2000,
    months: 17,
    years: 1.42,
    total_interest: 4114.81,
    total_paid: 77114.81,
    debt_free_date: "2028-04",
    baseline_interest: 8236.29,
    interest_saved: 4121.48,
    baseline_available: true,
    schedule_months: 17,
    milestones: [
      { month: 8, name: "信用卡", date: "2027-07" },
      { month: 17, name: "消费贷", date: "2028-04" },
    ],
    warnings: [],
    notes: ["月复利口径"],
    debts: [
      { name: "信用卡", balance: 20000, rate: 0.18, min_payment: 1000 },
      { name: "消费贷", balance: 50000, rate: 0.06, min_payment: 1500 },
    ],
    ...overrides,
  };
}

function setup(state: {
  data?: unknown;
  isPending?: boolean;
  error?: Error | null;
  compare?: unknown;
}) {
  mockUsePayoffPlan.mockReturnValue({
    data: state.data,
    isPending: state.isPending ?? false,
    error: state.error ?? null,
    compare: { data: state.compare },
  });
}

describe("DebtPayoffPage", () => {
  it("加载中渲染骨架屏而不是空白", () => {
    setup({ isPending: true });
    const { container } = render(<DebtPayoffPage />);
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(0);
  });

  it("无负债时显示空态与去录入入口", () => {
    setup({ data: { available: false, reason: "账本里还没有负债记录", debts: [] } });
    const onGoLedger = vi.fn();
    render(<DebtPayoffPage onGoLedger={onGoLedger} />);
    expect(screen.getByText("debts.emptyTitle")).toBeInTheDocument();
    expect(screen.getByText("账本里还没有负债记录")).toBeInTheDocument();
    fireEvent.click(screen.getByText("debts.goLedger"));
    expect(onGoLedger).toHaveBeenCalledTimes(1);
  });

  it("有负债时展示还清日期、总利息与可省利息", () => {
    setup({ data: plan() });
    render(<DebtPayoffPage />);
    expect(screen.getAllByText("2028-04").length).toBeGreaterThan(0);
    // 总利息在结论卡出现多次（含基线对照文本）时取第一个
    expect(screen.getAllByText("¥4,114.81").length).toBeGreaterThan(0);
    expect(screen.getByText("¥4,121.48")).toBeInTheDocument();
  });

  it("负摊还时显示告警并且不显示虚假还清日期", () => {
    setup({
      data: plan({
        debt_free_date: null,
        warnings: ["月供总额不足以覆盖利息（负摊还），该计划无法还清"],
        milestones: [],
      }),
    });
    render(<DebtPayoffPage />);
    expect(screen.getByText("debts.warningTitle")).toBeInTheDocument();
    expect(screen.getByText("debts.cannotClear")).toBeInTheDocument();
    expect(screen.queryByText("2028-04")).not.toBeInTheDocument();
  });

  it("逐笔负债表列出本金、利率与结清月", () => {
    setup({ data: plan() });
    render(<DebtPayoffPage />);
    // 名称同时出现在明细表与时间线，这里只断言「至少渲染了一次」
    expect(screen.getAllByText("信用卡").length).toBeGreaterThan(0);
    expect(screen.getByText("¥20,000")).toBeInTheDocument();
    expect(screen.getByText("18.00%")).toBeInTheDocument();
    // 里程碑日期出现在表格与时间线两处
    expect(screen.getAllByText("2027-07").length).toBeGreaterThan(0);
  });

  it("对比数据到达后展示两种方法与结论", () => {
    setup({
      data: plan(),
      compare: {
        avalanche: { ...plan(), method: "avalanche" },
        snowball: { ...plan(), method: "snowball", months: 18, total_interest: 4148.65 },
        interest_diff: 33.84,
        verdict: "雪崩法少付 33.84 利息",
      },
    });
    render(<DebtPayoffPage />);
    expect(screen.getByText("debts.compareTitle")).toBeInTheDocument();
    expect(screen.getByText("雪崩法少付 33.84 利息")).toBeInTheDocument();
    expect(screen.getAllByText("debts.current").length).toBeGreaterThan(0);
  });

  it("改额外还款额会防抖后再查询（不逐键请求）", async () => {
    setup({ data: plan() });
    render(<DebtPayoffPage />);
    const input = screen.getByLabelText("debts.extraLabel");
    fireEvent.change(input, { target: { value: "3500" } });
    // 防抖窗口内不应把新值传给 hook
    expect(mockUsePayoffPlan).toHaveBeenLastCalledWith(2000, "avalanche");
    await waitFor(
      () => expect(mockUsePayoffPlan).toHaveBeenLastCalledWith(3500, "avalanche"),
      { timeout: 1500 },
    );
  });

  it("切换到雪球法会带 method 重新查询", async () => {
    setup({ data: plan() });
    render(<DebtPayoffPage />);
    fireEvent.click(screen.getByText("debts.methodSnowball"));
    await waitFor(() =>
      expect(mockUsePayoffPlan).toHaveBeenLastCalledWith(2000, "snowball"),
    );
  });

  it("基线不可算时显示「—」与说明，而不是 ¥0", () => {
    setup({
      data: plan({ baseline_interest: null, interest_saved: null, baseline_available: false }),
    });
    render(<DebtPayoffPage />);
    expect(screen.getByText("debts.baselineUnavailable")).toBeInTheDocument();
    // 不能再出现「只付最低月供 ¥0」这种把不可算说成省 0 元的文案
    expect(screen.queryByText("debts.vsMinimum:{v}")).not.toBeInTheDocument();
  });

  it("compare 返回 available:false 时不崩溃（负债被删空）", () => {
    setup({
      data: plan(),
      compare: { available: false, reason: "没有可规划的负债", debts: [] },
    });
    render(<DebtPayoffPage />);
    // 主计划仍应完整渲染（日期在结论卡与明细表各出现一次）
    expect(screen.getAllByText("2028-04").length).toBeGreaterThan(0);
    expect(screen.queryByText("debts.compareTitle")).not.toBeInTheDocument();
  });

  it("口径脚注必须渲染（不隐藏免责说明）", () => {
    setup({ data: plan() });
    render(<DebtPayoffPage />);
    expect(screen.getByText("月复利口径")).toBeInTheDocument();
    expect(screen.getByText("debts.disclaimer")).toBeInTheDocument();
  });
});

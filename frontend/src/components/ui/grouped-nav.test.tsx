import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LayoutGrid, Wallet, TrendingUp, Plug } from "lucide-react";
import { I18nProvider } from "@/lib/i18n";
import { GroupedNav, Disclosure, type NavGroup } from "@/components/ui/grouped-nav";

/** 组件内部用 useI18n，必须包 Provider（与生产环境一致）。 */
function wrap(ui: React.ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>);
}

/**
 * 分组导航：11 个平铺 tab 收敛成「组 → 子项」两级。
 * 断言重点是导航行为本身：分组可见、当前组自动展开、跨组切换可点、激活项唯一。
 */

const GROUPS: NavGroup<string>[] = [
  {
    id: "daily",
    labelKey: "nav.groupDaily",
    items: [
      { key: "overview", labelKey: "nav.dashboard", icon: LayoutGrid },
      { key: "holdings", labelKey: "nav.holdings", icon: Wallet },
    ],
  },
  {
    id: "analyze",
    labelKey: "nav.groupAnalyze",
    items: [{ key: "market", labelKey: "nav.market", icon: TrendingUp }],
  },
  {
    id: "connect",
    labelKey: "nav.groupConnect",
    items: [{ key: "connect", labelKey: "nav.connect", icon: Plug }],
  },
];

describe("GroupedNav", () => {
  it("renders every group header", () => {
    wrap(<GroupedNav groups={GROUPS} value="overview" onChange={() => {}} />);
    expect(screen.getByRole("button", { name: "Daily" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Analyze" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Connect" })).toBeTruthy();
  });

  it("only shows items of the active group", () => {
    wrap(<GroupedNav groups={GROUPS} value="overview" onChange={() => {}} />);
    expect(screen.getByRole("tab", { name: "Dashboard" })).toBeTruthy();
    // analyze 组的子项不该出现（否则又变回平铺）
    expect(screen.queryByRole("tab", { name: "Market" })).toBeNull();
  });

  it("follows the selected value across groups", () => {
    wrap(<GroupedNav groups={GROUPS} value="market" onChange={() => {}} />);
    expect(screen.getByRole("tab", { name: "Market" })).toBeTruthy();
    expect(screen.queryByRole("tab", { name: "Dashboard" })).toBeNull();
  });

  it("emits onChange when a sub-item is clicked", async () => {
    const onChange = vi.fn();
    wrap(<GroupedNav groups={GROUPS} value="overview" onChange={onChange} />);
    await userEvent.click(screen.getByRole("tab", { name: "Holdings" }));
    expect(onChange).toHaveBeenCalledWith("holdings");
  });

  it("switches group when its header is clicked", async () => {
    wrap(<GroupedNav groups={GROUPS} value="overview" onChange={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Analyze" }));
    expect(screen.getByRole("tab", { name: "Market" })).toBeTruthy();
  });

  it("marks exactly one tab as selected", () => {
    wrap(<GroupedNav groups={GROUPS} value="holdings" onChange={() => {}} />);
    const selected = screen.getAllByRole("tab").filter((el) => el.getAttribute("aria-selected") === "true");
    expect(selected).toHaveLength(1);
    expect(selected[0].textContent).toContain("Holdings");
  });
});

describe("Disclosure", () => {
  it("is collapsed by default and reveals content on click", async () => {
    wrap(
      <Disclosure title="Details" hint="optional">
        <p>hidden body</p>
      </Disclosure>,
    );
    expect(screen.queryByText("hidden body")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Details/ }));
    expect(screen.getByText("hidden body")).toBeTruthy();
  });
});

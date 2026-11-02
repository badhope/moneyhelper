/** 空账本回归：后端 /api/calculations/returns 在没有持仓时只返回 {period_months, transaction_count}，
 *  xirr/twr 键整体缺失。旧实现 `"error" in undefined` 抛 TypeError，导致总览整页白屏。 */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nProvider } from "@/lib/i18n";
import { ReturnsCard } from "./ReturnsCard";

vi.mock("@/lib/use-calculations", () => ({
  useReturns: () => ({
    data: { period_months: 6, transaction_count: 0 },
    isLoading: false,
    isError: false,
  }),
}));

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <I18nProvider>{ui}</I18nProvider>
    </QueryClientProvider>
  );
}

describe("ReturnsCard", () => {
  it("后端缺 xirr/twr 字段时渲染占位而不崩溃", () => {
    render(wrap(<ReturnsCard />));
    expect(screen.queryByText(/页面出错/)).toBeNull();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});

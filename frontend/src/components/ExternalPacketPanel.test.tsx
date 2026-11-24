import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ExternalPacketPanel } from "@/components/ExternalPacketPanel";

vi.mock("@/lib/i18n", () => ({
  useI18n: vi.fn(() => ({ t: (k: string) => k, lang: "zh" })),
}));
vi.mock("@/lib/use-enterprise-plan", () => ({
  usePlanPeriods: vi.fn(() => ({ data: { periods: ["2026-11"] }, isLoading: false })),
}));
vi.mock("@/lib/use-consolidation", () => ({
  useConsolidationGroups: vi.fn(() => ({
    data: { groups: [{ id: "g1", name: "星海集团" }] },
    isLoading: false,
  })),
}));
vi.mock("@/lib/use-external-packets", () => ({
  useTaxPacket: vi.fn(() => ({
    data: {
      packet_id: "TAX-202611-ABCD1234",
      period: "2026-11",
      status: "blocked",
      submission_status: "not_submitted",
      period_status: "open",
      posted_entries: 3,
      draft_entries: 0,
      summary: {
        income: 410000,
        expense: 200000,
        profit: 210000,
        cash_in: 410000,
        cash_out: 200000,
        cash_net: 210000,
        tax_accrued: 12000,
        tax_paid: 0,
        tax_net: 12000,
        debit: 610000,
        credit: 610000,
      },
      account_summary: [
        { account_code: "1001", account_name: "库存现金", debit: 0, credit: 0, balance: 0 },
      ],
      checks: [{ id: "tax_channel", status: "blocked", detail: "无税局直连资质" }],
      boundary: "未提交税局。",
    },
    isLoading: false,
    error: null,
  })),
  usePaymentPacket: vi.fn(() => ({
    data: {
      packet_id: "PAY-202611-EFGH5678",
      period: "2026-11",
      status: "review",
      execution_status: "draft_only",
      can_execute: false,
      total: 30000,
      count: 1,
      opening: 200000,
      target_min: 150000,
      instructions: [
        {
          seq: 1,
          expected_date: "2026-11-25",
          account_code: "1001",
          counterparty: "供应商甲",
          amount: 30000,
          amount_cents: 3000000,
          certainty: "high",
          note: "",
          review: "",
        },
      ],
      checks: [{ id: "payment_channel", status: "blocked", detail: "无支付通道" }],
      boundary: "仅草稿。",
    },
    isLoading: false,
    error: null,
  })),
  useConsolidationPacket: vi.fn(() => ({
    data: {
      packet_id: "CONS-202611-IJKL9012",
      period: "2026-11",
      status: "review",
      audit_status: "not_audited",
      basis: "management",
      group: { id: "g1", name: "星海集团" },
      entities: [
        { tenant_id: 2, name: "星海子公司", ownership_pct: 70, method: "full", status: "ok", included: true },
      ],
      summary: { consolidated: { revenue: 410000, net_profit: 210000, total_assets: 900000 } },
      totals: { debit_cents: 61000000, credit_cents: 61000000 },
      balanced: true,
      warnings: [],
      source_hash: "abc123",
      checks: [{ id: "consolidation_audit", status: "blocked", detail: "非法定审计" }],
      boundary: "管理口径。",
    },
    isLoading: false,
    error: null,
  })),
}));

describe("ExternalPacketPanel", () => {
  it("三类资料包同时显示，且明确未申报、不可执行、未审计", () => {
    render(<ExternalPacketPanel />);
    expect(screen.getByText(/TAX-202611-ABCD1234/)).toBeInTheDocument();
    expect(screen.getByText("external.taxNotSubmitted")).toBeInTheDocument();
    expect(screen.getByText("external.paymentDraftBadge")).toBeInTheDocument();
    expect(screen.getByText("供应商甲")).toBeInTheDocument();
    expect(screen.getByText("external.auditNotLegal")).toBeInTheDocument();
    expect(screen.getByText(/abc123/)).toBeInTheDocument();
    expect(screen.getByText("2026-11")).toBeInTheDocument();
  });
});

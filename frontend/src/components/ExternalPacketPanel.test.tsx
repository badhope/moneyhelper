import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ExternalPacketPanel } from "@/components/ExternalPacketPanel";

const handoffMocks = vi.hoisted(() => ({ archiveMutate: vi.fn(), ackMutate: vi.fn() }));

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
      source_hash: "taxhash-abcdef0123456789",
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
      source_hash: "payhash-abcdef0123456789",
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
  useHandoffLedger: vi.fn(() => ({
    data: {
      records: [
        {
          packet_id: "TAX-202611-ABCD1234",
          kind: "tax",
          period: "2026-11",
          group_id: "",
          source_hash: "taxhash-abcdef0123456789",
          packet_status: "blocked",
          note: "交给代账",
          archived_at: "2026-11-24T17:20:00+08:00",
          archived_by: "user:0",
          handed_at: "",
          handed_note: "",
          state: "archived",
        },
        {
          packet_id: "CONS-202611-IJKL9012",
          kind: "consolidation",
          period: "2026-11",
          group_id: "g1",
          source_hash: "abc123abcdef0123456789abcdef0123",
          packet_status: "review",
          note: "",
          archived_at: "2026-11-24T17:10:00+08:00",
          archived_by: "user:0",
          handed_at: "2026-11-24T17:30:00+08:00",
          handed_note: "已交给审计师",
          state: "handed_over",
        },
      ],
      total: 2,
      archived_count: 1,
      handed_count: 1,
      boundary: "不是税局申报。",
    },
    isLoading: false,
    error: null,
  })),
  useArchiveHandoff: vi.fn(() => ({ isPending: false, variables: undefined, mutate: handoffMocks.archiveMutate })),
  useAckHandoff: vi.fn(() => ({ isPending: false, variables: undefined, mutate: handoffMocks.ackMutate })),
  useExternalChannels: vi.fn(() => ({
    data: {
      channels: [
        {
          channel_id: "smtp",
          label: "邮箱投递",
          transport: "smtp",
          kinds: ["tax", "payment", "consolidation"],
          secret_fields: ["password"],
          config_fields: ["host"],
          config: { host: "smtp.example.com", from_addr: "finance@example.com", to_addrs: ["a@example.com"] },
          enabled: true,
          configured: true,
          ready: true,
          missing: [],
          last_test_at: "2026-11-24T18:00:00+08:00",
          last_test_ok: true,
          last_test_detail: "SMTP 服务器已受理测试邮件",
        },
        {
          channel_id: "tax_gateway",
          label: "税费申报网关",
          transport: "https",
          kinds: ["tax"],
          secret_fields: ["signing_secret"],
          config_fields: ["endpoint"],
          config: {},
          enabled: false,
          configured: false,
          ready: false,
          missing: ["disabled", "endpoint", "signing_secret"],
          last_test_at: "",
          last_test_ok: null,
          last_test_detail: "",
        },
      ],
      deliveries: [
        {
          id: 1,
          channel_id: "smtp",
          kind: "tax",
          packet_id: "TAX-202611-ABCD1234",
          source_hash: "taxhash-abcdef0123456789",
          status: "accepted",
          recipient: "a@example.com",
          request_summary: {},
          receipt: { message_id: "<test@example.com>" },
          error: "",
          created_at: "2026-11-24T18:00:00+08:00",
          updated_at: "2026-11-24T18:00:00+08:00",
        },
      ],
      stats: { accepted: 1, failed: 0, pending: 0 },
      boundary: "通道只证明对端受理。",
    },
    isLoading: false,
    isFetching: false,
    refetch: vi.fn(),
  })),
  useSaveExternalChannel: vi.fn(() => ({ isPending: false, mutate: vi.fn() })),
  useTestExternalChannel: vi.fn(() => ({ isPending: false, mutate: vi.fn() })),
  useDeleteExternalChannel: vi.fn(() => ({ isPending: false, mutate: vi.fn() })),
  useDeliverPacket: vi.fn(() => ({ isPending: false, mutate: vi.fn() })),
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
      source_hash: "abc123abcdef0123456789abcdef0123",
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
    expect(screen.getAllByText(/TAX-202611-ABCD1234/).length).toBeGreaterThan(0);
    expect(screen.getByText("external.taxNotSubmitted")).toBeInTheDocument();
    expect(screen.getByText("external.paymentDraftBadge")).toBeInTheDocument();
    expect(screen.getByText("供应商甲")).toBeInTheDocument();
    expect(screen.getByText("external.auditNotLegal")).toBeInTheDocument();
    expect(screen.getAllByText(/abc123/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("2026-11").length).toBeGreaterThan(0);
    expect(screen.getByText("external.ledgerTitle")).toBeInTheDocument();
    expect(screen.getAllByText("external.hashMatched").length).toBeGreaterThan(0);
    expect(screen.getAllByText("external.status.handed_over").length).toBeGreaterThan(0);
    expect(screen.getByText("external.handoffAck")).toBeInTheDocument();
    // 4.21.1：顶部总览、税务环图、现金安全垫、合并主体卡与交接路径都要真实渲染
    expect(screen.getByText("external.heroKicker")).toBeInTheDocument();
    expect(screen.getByText("external.heroHandedShort")).toBeInTheDocument();
    expect(screen.getByText("external.overviewPacks")).toBeInTheDocument();
    expect(screen.getByText("external.overviewHanded")).toBeInTheDocument();
    expect(screen.getAllByText("external.taxSplit").length).toBeGreaterThan(0);
    expect(screen.getByText("external.paymentFlow")).toBeInTheDocument();
    expect(screen.getByText("external.consolidationEntities")).toBeInTheDocument();
    expect(screen.getAllByText("external.ledgerStepArchive").length).toBeGreaterThan(0);
    expect(screen.getAllByText("external.ledgerStepHandoff").length).toBeGreaterThan(0);
  });

  it("留档按钮把类型、期间与备注一起提交", () => {
    render(<ExternalPacketPanel />);
    fireEvent.change(screen.getByPlaceholderText("external.handoffNotePlaceholder"), {
      target: { value: "已打印盖章" },
    });
    fireEvent.click(screen.getAllByText("external.archive")[0]);
    expect(handoffMocks.archiveMutate).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "payment", period: "2026-11", note: "已打印盖章" }),
      expect.any(Object),
    );
  });
});

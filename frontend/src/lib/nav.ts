import type { LucideIcon } from "lucide-react";
import {
  BookOpenCheck,
  CandlestickChart,
  CalendarCheck,
  ClipboardList,
  CreditCard,
  FileText,
  HeartPulse,
  Landmark,
  LayoutGrid,
  NotebookPen,
  Plug,
  TrendingUp,
  Users,
  Wallet,
} from "lucide-react";
import type { DataKind } from "@/lib/views";

/**
 * 财务工作区导航 —— 分组与顺序的**唯一定义处**。
 *
 * ## 为什么从 `FinancePage.tsx` 搬出来
 *
 * 这份清单原先写在 `FinancePage.tsx` 里，只有渲染代码能读到，于是没有任何
 * 测试能回答「是不是每个视图都出现在导航里」。新增一个 `DataKind` 却忘了
 * 加进导航，页面就成了"只能被对话跳转、用户点不到"的隐形页 —— 只有真实用户
 * 才会发现。搬到 `lib/nav.ts` 后由 `nav.test.ts` 守着：
 * 每个 `DataKind` 必须出现且只出现一次。
 *
 * ## 分组逻辑（按用户心智，不按功能清单）
 *
 *   daily   每天都会看：总览、持仓、记账
 *   analyze 需要判断时看：行情、投研、策略、体检
 *   books   记录和审批时才进：报销、采购应付、长任务
 *   ledger  月底/报税才进：总账、银行对账、财报、公司财税、模拟盘
 *   connect 一次性配置：连接中心
 *
 * 原来 11 个 tab 同级平铺，用户每次都要线性扫一遍；分组后每屏只看到
 * 3-5 项，且「日常」与「一次性配置」在视觉上分开，不会把配置动作误当高频动作。
 */
export type NavGroup<T extends string> = {
  id: string;
  labelKey: string;
  items: { key: T; labelKey: string; icon: LucideIcon }[];
};

export const NAV_GROUPS: NavGroup<DataKind>[] = [
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
      { key: "research", labelKey: "nav.deskWorkspace", icon: CandlestickChart },
      { key: "health", labelKey: "hc.title", icon: HeartPulse },
    ],
  },
  {
    id: "books",
    labelKey: "nav.groupBooks",
    items: [
      { key: "expenses", labelKey: "nav.billsWorkspace", icon: ClipboardList },
      { key: "longtask", labelKey: "nav.longtask", icon: FileText },
    ],
  },
  {
    id: "ledger",
    labelKey: "nav.groupLedger",
    items: [
      // 入口落在「经营报表」而不是总账：刚上手的人先要看懂"我这个月赚没赚"，
      // 凭证列表是会计的视角，放工作区第二个 tab。
      { key: "statements", labelKey: "nav.ledgerWorkspace", icon: BookOpenCheck },
      { key: "review", labelKey: "nav.review", icon: CalendarCheck },
      { key: "bank", labelKey: "nav.bank", icon: Landmark },
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
 * 被"工作区"吸收的视图 -> 入口视图。
 *
 * 同一件事的多个视角（总账/财报/公司财税、报销/采购应付、投研/投资策略）在导航上
 * 只保留一个入口，其余视角仍可通过工作区顶部 tab、对话跳转与深链到达。
 * 这里集中登记，是为了让"导航高亮哪一项""从对话跳转过来该落在哪个分组"都有据可依，
 * 而不是散落在各组件里各判断一次。
 */
export const WORKSPACE_HOME: Partial<Record<DataKind, DataKind>> = {
  gl: "statements",
  tax: "statements",
  procurement: "expenses",
  strategy: "research",
};

/** 把一个"可能是工作区成员"的视图归一成导航入口视图。 */
export function navHomeOf(kind: DataKind): DataKind {
  return WORKSPACE_HOME[kind] ?? kind;
}

/** 视图 -> 所属分组，供"当前在哪一组"、埋点、跳转归一使用。 */
export function groupOfKind(kind: DataKind): NavGroup<DataKind> | undefined {
  const home = navHomeOf(kind);
  return NAV_GROUPS.find((g) => g.items.some((i) => i.key === home));
}

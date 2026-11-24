/**
 * 财务工作区的视图清单 —— **唯一定义处**。
 *
 * ## 为什么抽出来
 *
 * `DataKind` 之前在 `App.tsx` 和 `FinancePage.tsx` 各写了一遍类型字面量，
 * 合法视图名数组又在三处各自手抄（App 的 `openData`、FinancePage 的
 * Dashboard 按钮回调、类型本身）。加一个视图要改三个地方，漏一个就会出现
 * 「对话里说‘看看税负’跳不过去」或「按钮点了没反应」这类静默失败——
 * FinancePage 里那段注释记录的就是这个坑。
 *
 * 现在：数组是唯一真源，类型从数组派生，校验走 `isDataKind()`。
 */

export const DATA_KINDS = [
  "overview",
  "autopilot",
  "holdings",
  "market",
  "ledger",
  "health",
  "strategy",
  "research",
  "statements",
  "review",
  "paper",
  "connect",
  "tax",
  "budget",
  "external",
  "debts",
  "gl",
  "expenses",
  "procurement",
  "longtask",
  "ecommerce",
  "bank",
] as const;

export type DataKind = (typeof DATA_KINDS)[number];

export function isDataKind(value: string): value is DataKind {
  return (DATA_KINDS as readonly string[]).includes(value);
}

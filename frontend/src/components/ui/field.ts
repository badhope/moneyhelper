/**
 * 表单字段样式：输入框 / 标签的**唯一来源**。
 *
 * 此前这一串 class 在 8 个页面里各抄了一份（BankPage / EntryView / ExpensesPage /
 * GlPage / GoalsPanel / LongTaskPage / PositionAppendDialog / PositionEditDialog /
 * ProcurementPage / settings/shared），一字不差。改圆角或聚焦环要改 8 处，
 * 漏一处就会出现"同一屏两个输入框长得不一样"。
 *
 * 只放样式常量，不放组件——这些页面用的是原生 input/select，
 * 包一层组件会改变受控写法与 ref 行为，收益不如直接用常量。
 */

export const inputCls =
  "w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring";

export const labelCls = "block text-xs text-muted-foreground mb-1";

/** 紧凑变体：面板/卡片内的小表单用（原 GoalsPanel 的小一号间距）。 */
export const inputClsCompact =
  "w-full rounded-lg border border-input bg-background px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring";

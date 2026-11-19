/**
 * 资产类别与支出分类：**数据值保持中文**（后端枚举、历史数据、导入文件都用中文），
 * 只有展示走 labelKey。
 *
 * 为什么单独成模块：这套选项原先在 `EntryView`（记账）与 `PositionEditDialog`（改持仓）
 * 各写了一份，改一处忘一处就会出现"记账页有'基金'、改持仓页没有"的不一致。
 * 选项列表与显示名一起收口，两边都从这里取。
 */

export const KIND_OPTIONS = ["股票", "ETF", "基金", "现金", "其他"] as const;
export type AssetKind = (typeof KIND_OPTIONS)[number];

export const KIND_LABEL_KEYS: Record<string, string> = {
  股票: "entry.kindStock",
  ETF: "entry.kindEtf",
  基金: "entry.kindFund",
  现金: "entry.kindCash",
  其他: "entry.kindOther",
};

export const CATEGORY_OPTIONS = [
  "收入",
  "餐饮",
  "居住",
  "交通",
  "购物",
  "订阅",
  "投资",
  "还款",
  "其他",
] as const;

export const CAT_LABEL_KEYS: Record<string, string> = {
  收入: "entry.catIncome",
  餐饮: "entry.catFood",
  居住: "entry.catHousing",
  交通: "entry.catTransport",
  购物: "entry.catShopping",
  订阅: "entry.catSubs",
  投资: "entry.catInvest",
  还款: "entry.catRepay",
  其他: "entry.catOther",
};

/** 类别 → 展示名；未登记的类别原样返回（导入数据里可能出现自定义类别）。 */
export function kindLabel(kind: string, t: (k: string) => string): string {
  const key = KIND_LABEL_KEYS[kind];
  return key ? t(key) : kind;
}

/**
 * 设置中心的分区定义 —— **唯一定义处**。
 *
 * ## 为什么抽出来
 *
 * 改造前「一个分区」要在三处登记：
 *   1. `use-settings-form.ts` 里的 `SectionId` 联合类型（24 个字符串）
 *   2. `SettingsView.tsx` 里的 `SECTIONS`（id + 文案 key + 图标）
 *   3. `SettingsView.tsx` 里的 `SECTION_GROUPS`（分组归属）
 *
 * 三份清单靠人工保持同步，加一个分区漏改任一处就会出现「导航里有、渲染没有」
 * 或「类型不认、点开白屏」。现在分组结构是唯一真源，`SectionId` 由它派生：
 * 新增分区只需在下面加一个 id，再在 SettingsView 的 SECTIONS 里补文案与图标。
 */

export const SECTION_GROUPS = [
  { key: "settings.groupGeneral", ids: ["prefs", "rules", "budget", "family", "org"] },
  { key: "settings.groupAi", ids: ["ai", "knowledge", "report", "memory"] },
  {
    key: "settings.groupStudio",
    ids: [
      "roles",
      "skills",
      "prompt",
      "constraints",
      "hooks",
      "plugins",
      "market",
      "internalTools",
      "permissions",
    ],
  },
  { key: "settings.groupData", ids: ["data", "token", "logs", "audit", "provenance"] },
  { key: "settings.groupEval", ids: ["eval"] },
] as const;

export type SectionId = (typeof SECTION_GROUPS)[number]["ids"][number];

/** 全部分区 id（按分组顺序展开），供校验与遍历使用。 */
export const SECTION_IDS: readonly SectionId[] = SECTION_GROUPS.flatMap((g) => g.ids);

export function isSectionId(value: string): value is SectionId {
  return (SECTION_IDS as readonly string[]).includes(value);
}

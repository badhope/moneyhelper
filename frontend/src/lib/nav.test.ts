import { describe, expect, it } from "vitest";
import { NAV_GROUPS, WORKSPACE_HOME, groupOfKind, navHomeOf } from "@/lib/nav";
import { DATA_KINDS } from "@/lib/views";

/**
 * 导航覆盖守卫。
 *
 * 改造前 NAV_GROUPS 写在 FinancePage.tsx 内部，没有任何测试能回答
 * "是不是每个视图都能从导航点到"。新增视图忘记加进导航的后果是
 * 该页只能被对话跳转打开，用户点不到 —— 静默失败，只有真实用户会发现。
 */
describe("NAV_GROUPS", () => {
  const keys = NAV_GROUPS.flatMap((g) => g.items.map((i) => i.key));

  it("每个视图要么在导航里，要么归属某个工作区入口", () => {
    for (const kind of DATA_KINDS) {
      if (keys.includes(kind)) continue;
      const home = navHomeOf(kind);
      expect(home, `视图「${kind}」既不在导航里，也没有工作区入口`).not.toBe(kind);
      expect(keys, `视图「${kind}」的工作区入口「${home}」不在导航里`).toContain(home);
    }
  });

  it("工作区成员不重复登记，且入口本身不被吸收", () => {
    for (const [member, home] of Object.entries(WORKSPACE_HOME)) {
      expect(keys, `被吸收的视图「${member}」不该再单独出现在导航里`).not.toContain(member);
      expect(WORKSPACE_HOME[home as keyof typeof WORKSPACE_HOME]).toBeUndefined();
    }
  });

  it("没有视图被重复挂在两个位置", () => {
    const dup = keys.filter((k, i) => keys.indexOf(k) !== i);
    expect(dup, `重复出现的视图：${dup.join("、")}`).toEqual([]);
  });

  it("导航里没有残留的已删视图", () => {
    for (const k of keys) {
      expect(DATA_KINDS as readonly string[]).toContain(k);
    }
  });

  it("分组 id 与标题不重复，且每组都有内容", () => {
    const ids = NAV_GROUPS.map((g) => g.id);
    const labels = NAV_GROUPS.map((g) => g.labelKey);
    expect(new Set(ids).size).toBe(ids.length);
    expect(new Set(labels).size).toBe(labels.length);
    for (const g of NAV_GROUPS) expect(g.items.length).toBeGreaterThan(0);
  });

  it("每个视图都能反查到所属分组（按工作区入口归一）", () => {
    for (const kind of DATA_KINDS) {
      const g = groupOfKind(kind);
      expect(g, `视图「${kind}」反查不到分组`).toBeTruthy();
      expect(
        g?.items.some((i) => i.key === navHomeOf(kind)),
        `视图「${kind}」的分组里没有它的入口「${navHomeOf(kind)}」`,
      ).toBe(true);
    }
  });
});

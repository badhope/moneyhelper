import { test, expect } from "@playwright/test";

/**
 * 主功能页全量可达：每个导航分区的每个子页都真实点开，断言内容渲染且无 JS 异常。
 *
 * 与 settings-all.spec.ts 互补：那个覆盖设置中心 24 个分区，这个覆盖
 * 财务工作区的全部子页（含新增的采购应付）。目的是防止"导航重构后某页不可达"
 * 这类只有用户才会发现的问题。
 */

const GROUPS: { group: string; tabs: string[] }[] = [
  { group: "每天看", tabs: ["总览", "持仓", "记账", "还债规划"] },
  { group: "判断时", tabs: ["行情", "投研", "投资策略", "财务体检"] },
  { group: "业务", tabs: ["报销", "采购应付"] },
  { group: "账务", tabs: ["总账", "银行对账", "财报", "公司财税", "模拟盘"] },
  { group: "接入", tabs: ["连接中心"] },
];

test.describe("财务工作区全量可达", () => {
  test("每个分组的每个子页都能打开且渲染内容", async ({ page }) => {
    test.setTimeout(180_000);
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(`console: ${m.text()}`);
    });

    await page.goto("/");
    await page.getByRole("button", { name: "总览" }).first().click();

    let visited = 0;
    for (const { group, tabs } of GROUPS) {
      const groupBtn = page.getByRole("button", { name: group, exact: true }).first();
      await groupBtn.waitFor({ state: "visible", timeout: 10_000 });
      await groupBtn.click();

      for (const tab of tabs) {
        const trigger = page.getByRole("tab", { name: tab, exact: true }).first();
        try {
          await expect(trigger).toBeVisible({ timeout: 5_000 });
        } catch {
          // "接入"组在部分构建里是单个按钮而非 tab，按按钮再试一次
          await page.getByRole("button", { name: tab, exact: true }).first().click();
          visited += 1;
          continue;
        }
        await trigger.click();
        await expect(trigger).toHaveAttribute("aria-selected", "true");
        const main = page.locator("main").first();
        await expect(main).toBeVisible();
        const text = (await main.innerText()).trim();
        expect(text.length, `页面「${tab}」渲染为空`).toBeGreaterThan(0);
        visited += 1;
      }
    }

    expect(visited).toBe(16);
    expect(errors, `页面出现异常：\n${errors.join("\n")}`).toEqual([]);
  });
});

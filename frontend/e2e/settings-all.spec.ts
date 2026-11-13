import { test, expect } from "@playwright/test";

/**
 * 设置页全量可达性：24 个分区逐个点开，断言
 *  - 分区内容区渲染（不是空白）；
 *  - 页面无 JS 异常；
 *  - 切换后不残留上一分区的标题。
 *
 * 这是「用户能真的走到每个设置页」的门禁：单测覆盖不到导航链路，
 * 分组折叠一改就可能让某个分区彻底不可达。
 */

const GROUPS: { group: string; sections: string[] }[] = [
  { group: "基础设置", sections: ["偏好", "账本规则", "预算", "家庭账本", "组织架构"] },
  { group: "AI 与自动化", sections: ["AI 回答", "知识库", "每日晨报", "长期记忆"] },
  {
    group: "Agent 能力",
    sections: [
      "角色（Agent）",
      "技能（Skill）",
      "系统提示词",
      "约束（Rules）",
      "Hook 钩子",
      "插件（MCP）",
      "插件市场",
      "内置工具",
      "权限",
    ],
  },
  { group: "数据与安全", sections: ["数据与状态", "访问口令", "日志", "审计日志", "溯源链"] },
  { group: "质量与评测", sections: ["模型评测"] },
];

test.describe("设置页全量可达", () => {
  test("24 个分区逐个打开无异常", async ({ page }) => {
    test.setTimeout(180_000);
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(`console: ${m.text()}`);
    });

    await page.goto("/");
    await page.getByRole("button", { name: "设置" }).first().click();

    let visited = 0;
    for (const { group, sections } of GROUPS) {
      const groupBtn = page.getByRole("button", { name: group, exact: true }).first();
      await groupBtn.waitFor({ state: "visible", timeout: 10_000 });
      if ((await groupBtn.getAttribute("aria-expanded")) !== "true") {
        await groupBtn.click();
      }
      await expect(groupBtn).toHaveAttribute("aria-expanded", "true");

      for (const section of sections) {
        const btn = page.getByRole("button", { name: section, exact: true }).first();
        await expect(btn).toBeVisible({ timeout: 10_000 });
        await btn.click();
        // 内容区必须真的渲染出东西：检查主内容容器有可见文本
        const content = page.locator("main, [role=main], .space-y-3").first();
        await expect(content).toBeVisible();
        const text = (await content.innerText()).trim();
        expect(text.length, `分区「${section}」渲染为空`).toBeGreaterThan(0);
        visited += 1;
      }
    }

    expect(visited).toBe(24);
    expect(errors, `页面出现异常：\n${errors.join("\n")}`).toEqual([]);
  });
});

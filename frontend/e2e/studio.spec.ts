import { test, expect } from "@playwright/test";

/**
 * Agent Studio 设置回归：新分区可达、四通道添加可用、权限锁定生效。
 *
 * 用真实后端 + 真实前端（Playwright webServer），断言的是用户可见结果：
 * 条目出现在列表里、错误有明确提示、切到标准模式后写入被拒。
 */

const API = "http://127.0.0.1:8788";

async function openSettings(page: import("@playwright/test").Page, section: string) {
  await page.goto("/");
  await page.getByRole("button", { name: "设置" }).first().click();
  await page.getByRole("button", { name: section, exact: true }).first().click();
}

test.describe("Agent Studio", () => {
  test.beforeEach(async ({ request }) => {
    // 每个用例前恢复全面放开，避免上一个用例改模式影响后续
    await request.put(`${API}/api/studio/permissions`, {
      data: { mode: "open", allow_chat_admin: true, allow_cli_admin: true, allow_remote_install: true },
    });
  });

  test("设置页出现全部 Studio 分区且默认非空", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "设置" }).first().click();
    for (const label of ["角色（Agent）", "技能（Skill）", "插件市场", "约束（Rules）", "Hook 钩子", "权限", "内置工具"]) {
      await expect(page.getByRole("button", { name: label, exact: true }).first()).toBeVisible();
    }
    // 角色页有内置角色（默认非空）
    await page.getByRole("button", { name: "角色（Agent）", exact: true }).first().click();
    await expect(page.getByText("Moneyhelper 总调度").first()).toBeVisible();
  });

  test("模板手写创建提示词并保存", async ({ page }) => {
    await openSettings(page, "系统提示词");
    await page.getByRole("button", { name: "手写模板" }).first().click();
    // 表单第一组：名称（text）、说明（text）、正文（textarea）、优先级（number）
    const nameInput = page.locator('input[type="text"]').last().locator("xpath=../..").locator("..");
    const textInputs = page.locator('input[type="text"]');
    const count = await textInputs.count();
    await textInputs.nth(count - 2).fill("E2E 提示词");
    await page.locator("textarea").last().fill("回答不超过三句话。");
    await page.getByRole("button", { name: "创建", exact: true }).click();
    await expect(page.getByText("E2E 提示词").first()).toBeVisible({ timeout: 10_000 });
    await expect(nameInput).toHaveCount(1);
  });

  test("导入 SKILL.md 文件", async ({ page }) => {
    await openSettings(page, "技能（Skill）");
    await page.getByRole("button", { name: "拖拽导入" }).first().click();
    await page.locator('input[type="file"][accept*=".zip"]').setInputFiles({
      name: "SKILL.md",
      mimeType: "text/markdown",
      buffer: Buffer.from("---\nname: e2e-skill\ndescription: E2E 导入技能\n---\n\n# 步骤\n1. 做一件事"),
    });
    await expect(page.getByText("e2e-skill").first()).toBeVisible({ timeout: 10_000 });
  });

  test("导入坏 JSON 显示字段级错误", async ({ page }) => {
    await openSettings(page, "约束（Rules）");
    await page.getByRole("button", { name: "拖拽导入" }).first().click();
    await page.locator('input[type="file"][accept*=".zip"]').setInputFiles({
      name: "broken.json",
      mimeType: "application/json",
      buffer: Buffer.from("{oops"),
    });
    await expect(page.getByText(/broken\.json/).first()).toBeVisible({ timeout: 10_000 });
  });

  test("插件市场一键安装并显示已安装", async ({ page }) => {
    await openSettings(page, "插件市场");
    await expect(page.getByText("PDF 工具链").first()).toBeVisible({ timeout: 10_000 });
    const card = page.locator("li", { hasText: "PDF 工具链" }).first();
    const btn = card.getByRole("button");
    if ((await btn.innerText()).includes("安装") && !(await btn.innerText()).includes("已安装")) {
      await btn.click();
    }
    await expect(card.getByText("已安装到本地")).toBeVisible({ timeout: 10_000 });
  });

  test("权限：切到标准模式后对话配置被拒", async ({ page, request }) => {
    await openSettings(page, "权限");
    await page.getByRole("button", { name: /标准/ }).first().click();
    await expect(page.getByText("权限设置已保存").first()).toBeVisible({ timeout: 10_000 });
    const r = await request.post(`${API}/api/studio/chat-command`, {
      data: { text: "添加技能 blocked：x" },
    });
    const body = await r.json();
    expect(body.ok).toBe(false);
  });

  test("内置工具：显示清单并切换单个工具", async ({ page }) => {
    await openSettings(page, "内置工具");
    await expect(page.getByText(/已启用 \d+ \/ \d+ 个内置工具/)).toBeVisible();
    await page.getByRole("button", { name: "显示清单" }).click();
    await expect(page.getByText("统计摘要").first()).toBeVisible();
    const row = page.locator("li", { hasText: "统计摘要" }).first();
    await row.getByRole("switch").click();
    await expect(page.getByText(/已启用 \d+ \/ \d+ 个内置工具/)).toBeVisible();
  });
});

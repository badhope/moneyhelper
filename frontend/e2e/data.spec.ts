import { test, expect } from "@playwright/test";

/**
 * 数据浮层（v2：对话主导，数据按需弹出）：总览种子数据 + 从对话 chip 跳转持仓。
 * 依赖 global-setup 已种入演示数据（贵州茅台 / 沪深300ETF 等）。
 */

test.describe("数据浮层", () => {
  test("总览页包含资产相关文案（种子数据）", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "总览" }).first().click();
    await expect(page.getByRole("tab", { name: "总览" })).toHaveAttribute("aria-selected", "true", {
      timeout: 10_000,
    });
    await expect(page.getByText("资产分布").first()).toBeVisible();
    // 净值卡：负债明细可见（dict 契约的前端消费回归）
    await expect(page.getByText("信用卡分期").first()).toBeVisible({ timeout: 10_000 });
  });

  test("从对话跳转持仓浮层：种子持仓可见", async ({ page }) => {
    // 已接入模型的机器上该问答走 agent 路径；本地 CPU 2B 模型一轮 1-3 分钟，
    // 整例超时必须跟着放宽，否则 locator 的 240s 等待会被 60s 的用例超时先掐断。
    test.setTimeout(process.env.E2E_WITH_LLM === "1" ? 300_000 : 60_000);
    await page.goto("/");
    const field = page.getByPlaceholder(/问点什么/);
    await field.fill("我的持仓怎么样");
    await field.press("Enter");
    // 确定性/模型回答都带「去持仓页」chip。
    // 本地 2B 模型在纯 CPU 上 prefill 就要几十秒，E2E_WITH_LLM=1 时放宽等待；
    // 默认路径（无模型）仍然是 45s，避免把真故障拖成三分钟。
    const wait = process.env.E2E_WITH_LLM === "1" ? 240_000 : 45_000;
    await page.getByRole("button", { name: "去持仓页" }).first().click({ timeout: wait });
    await expect(page.getByRole("tab", { name: "持仓" })).toHaveAttribute("aria-selected", "true", {
      timeout: 15_000,
    });
    await expect(page.getByText(/贵州茅台/).first()).toBeVisible({ timeout: 15_000 });
  });
});

test("流式回答被中途掐断时，UI 明确提示不完整而不是假装成功", async ({ page }) => {
  await page.goto("/");
  // 拦截 /api/ask：先发两帧文本，然后直接关闭（不发 done）
  await page.route("**/api/ask", async (route) => {
    const events = [
      'data: {"type":"start","question":"测试"}',
      'data: {"type":"token","data":{"content":"这是一段被截断的"}}',
    ].join("\n\n");
    await route.fulfill({
      status: 200,
      headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" },
      body: events + "\n\n",
    });
  });

  await page.getByRole("textbox").first().fill("测试断流");
  await page.keyboard.press("Enter");

  // 应该看到已收到的那段文字
  await expect(page.getByText("这是一段被截断的").first()).toBeVisible({ timeout: 15_000 });
  // 并且必须出现"不完整"提示（而不是静默当作完成）
  await expect(page.getByText(/不完整|连接中断/).first()).toBeVisible({ timeout: 15_000 });
});

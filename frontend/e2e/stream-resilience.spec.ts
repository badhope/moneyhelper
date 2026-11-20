import { expect, test } from "@playwright/test";

/**
 * 弱网回归：SSE 第一次连接被强制掐断（模拟代理 reset / 移动网络切换），
 * 验证前端会按退避策略重连，并最终把完整回答拿到手。
 *
 * 用一个确定性问句（"午饭 35 元"）保证不依赖模型：未配模型时走离线模板，
 * 配了模型时也同样是流式返回。
 */
test("SSE 首次连接被掐断后自动重连成功", async ({ page }) => {
  let attempts = 0;
  await page.route("**/api/ask", async (route) => {
    attempts += 1;
    if (attempts === 1) {
      await route.abort("connectionreset");
      return;
    }
    await route.continue();
  });

  await page.goto("/");
  const field = page.getByPlaceholder(/问点什么/);
  await field.fill("午饭 35 元");
  await field.press("Enter");

  // 重连成功后才能拿到确定性回执
  await expect(page.getByText(/已记一笔/).first()).toBeVisible({ timeout: 20_000 });
  expect(attempts).toBeGreaterThanOrEqual(2);
});

import { test, expect } from "@playwright/test";

/**
 * 问答流程：回车发送 → 气泡 → 一句话记账离线闭环（含大额待确认审批）。
 * 不依赖真实 LLM：未配模型时走确定性模板，整条链路（SSE + 入账 + 跳转）仍可验证。
 */

test.describe("问答流程", () => {
  test("输入框中回车发出消息，气泡立刻出现", async ({ page }) => {
    await page.goto("/");
    const field = page.getByPlaceholder(/问点什么/);
    await field.fill("本月餐饮花了多少");
    await field.press("Enter");
    await expect(page.getByText("本月餐饮花了多少").first()).toBeVisible();
  });

  test("一句话记账离线闭环：回执 + 去记账页联动", async ({ page }) => {
    await page.goto("/");
    const field = page.getByPlaceholder(/问点什么/);
    await field.fill("午饭 35 元");
    await field.press("Enter");

    // 确定性回执（无需模型）
    await expect(page.getByText(/已记一笔/).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/35/).first()).toBeVisible();

    // 回执带「去记账页」跳转 chip → 打开记账浮层
    await page.getByRole("button", { name: "去记账页" }).first().click();
    await expect(page.getByRole("tab", { name: "记账" })).toHaveAttribute("aria-selected", "true", {
      timeout: 10_000,
    });
    await page.getByRole("button", { name: "返回问答" }).first().click();
  });

  test("大额待确认：回复「确认」后入账", async ({ page }) => {
    await page.goto("/");
    const field = page.getByPlaceholder(/问点什么/);
    await field.fill("工资 8000 已到账");
    await field.press("Enter");
    // 大额审批先待确认，不入账
    await expect(page.getByText(/确认要记吗/).first()).toBeVisible({ timeout: 10_000 });

    // 等本轮流式回答完全结束（停止按钮消失），再发确认，避免被 busy 早退静默丢弃
    await expect(page.getByRole("button", { name: "停止回答" })).toHaveCount(0);
    await field.fill("确认");
    await field.press("Enter");
    // 确认后入账
    await expect(page.getByText(/已记一笔/).last()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/8,000/).last()).toBeVisible();
  });

  test("未配置模型时仍回显友好提示（无页面异常）", async ({ page, request }) => {
    const health = (await (await request.get("http://127.0.0.1:8788/api/health")).json()) as {
      llm_configured?: boolean;
    };
    // 本机已接入模型时该离线兜底文案不适用：本用例只在未配模型环境（CI）运行
    test.skip(Boolean(health.llm_configured), "已接入模型，跳过离线兜底断言");

    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(String(err)));
    await page.goto("/");
    const field = page.getByPlaceholder(/问点什么/);
    await field.fill("你好");
    await field.press("Enter");
    // 确定性兜底文案，不是白屏 / JS 崩溃
    await expect(page.getByText(/未接入 AI|没有接入模型|未接入模型/).first()).toBeVisible({ timeout: 10_000 });
    expect(errors).toEqual([]);
  });
});

import { test, expect, request } from "@playwright/test";

/**
 * 「零输入出报表」的可达性守卫。
 *
 * 产品定位是"不用懂会计也能看到财报"，所以这条默认路径必须真的能点出结果：
 * - 总账有已过账凭证 → 出指标（毛利率/资产负债率等）；
 * - 总账里只有草稿 → 必须给出"还没有已过账凭证"的解释，而不是静默无反应。
 *
 * 两种结果都算通过；无反应、白屏、或抛 JS 异常算失败。
 */
test.describe("财报：按总账自动出表", () => {
  test("点「一键出报表」必须给出结果或明确原因", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));

    await page.addInitScript(() => {
      try {
        localStorage.setItem("wo.onboarded", "1");
      } catch {}
    });
    await page.goto("/", { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "总览" }).first().click();
    // 分组行只决定"显示哪一组"，还要点组内子项才真正切视图
    await page.getByRole("button", { name: "账务", exact: true }).click();
    await page.getByRole("tab", { name: "账务", exact: true }).click();
    // 财报现在是「账务」工作区内的 pill 按钮（不是 tablist），合并后必须按 button 定位
    await page.getByRole("button", { name: "经营报表", exact: true }).click();

    // 先造一张草稿凭证：本测试要验的正是"有草稿 → 系统替你过账 → 出指标"，
    // 空库上点两次不可能变出报表（此前脚本在空库上跑，第 2 步必然失败）。
    const ctx = await request.newContext({ baseURL: "http://127.0.0.1:8788" });
    const boot = await ctx.post("/api/gl/bootstrap", { data: { ref_date: "2026-11-20" } });
    if (!boot.ok()) throw new Error(`建账失败: ${await boot.text()}`);
    const accounts = await (await ctx.get("/api/gl/accounts")).json();
    const list = (accounts.accounts || []) as { id: number }[];
    if (list.length < 2) throw new Error("科目表少于 2 个，无法造凭证");
    const entry = await ctx.post("/api/gl/entries", {
      data: {
        entry_date: "2026-11-20",
        description: `E2E草稿 ${Date.now()}`,
        lines: [
          { account_id: list[0].id, debit: 1200, memo: "E2E" },
          { account_id: list[1].id, credit: 1200, memo: "E2E" },
        ],
      },
    });
    if (!entry.ok()) throw new Error(`造草稿凭证失败: ${await entry.text()}`);
    await ctx.dispose();

    await page.getByRole("button", { name: "一键出报表" }).click();

    // 结果区：要么直接出指标，要么给出"草稿还没过账"的原因
    const metrics = page.getByText("盈利能力").first();
    const reason = page.getByText(/草稿凭证还没过账|还没有任何凭证|还没有任何会计期间/).first();
    await expect(metrics.or(reason)).toBeVisible({ timeout: 20_000 });

    // 有草稿时，产品定位要求"人不用操作"：再点一次自动过账，就必须出指标
    if (await reason.isVisible().catch(() => false)) {
      // 文案已改为「全部交给你，直接出报表」（关键路径上产品主动揽下动作）
      await page.getByRole("button", { name: "全部交给你，直接出报表" }).click();
      await expect(metrics).toBeVisible({ timeout: 25_000 });
    }

    expect(errors, `页面异常：${errors.join("\n")}`).toEqual([]);

    // 留一张结果图，供人工核对"自动出的表长什么样"
    await page.screenshot({ path: "../out/shots/statements-auto.png", fullPage: true });
  });
});

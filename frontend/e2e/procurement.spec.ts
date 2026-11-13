import { test, expect, request, type APIRequestContext } from "@playwright/test";

/**
 * 采购/应付真实 UI 闭环（切片 8）：
 * 供应商 → 采购单 → 提交/审核 → 应付单 → 提交/审核 → 付款。
 *
 * 依赖：
 * - 本地模式（无账号），tenant 0；local 角色拥有全部权限点；
 * - 会计期间与三个科目通过 API 幂等准备（E2E 库跨轮次保留，不能假设为空）。
 */

async function ensureAccounts(ctx: APIRequestContext) {
  const wanted = [
    { code: "6601", name: "采购费用", type: "expense" },
    { code: "2202", name: "应付账款", type: "liability" },
    { code: "1002", name: "银行存款", type: "asset" },
  ];
  for (const acct of wanted) {
    const r = await ctx.post("/api/gl/accounts", { data: acct });
    if (!r.ok()) {
      // 已存在（唯一索引）时复用，不把重复创建当失败
      const list = await (await ctx.get("/api/gl/accounts")).json();
      const found = (list.accounts || []).some(
        (a: { code: string }) => a.code === acct.code,
      );
      if (!found) throw new Error(`创建科目 ${acct.code} 失败: ${await r.text()}`);
    }
  }
  await ctx.post("/api/gl/periods", { data: { year: 2026, month: 11 } });
}

test.describe("采购应付", () => {
  test("供应商→采购单→应付→付款全链路", async ({ page }) => {
    test.setTimeout(90_000);
    const suffix = String(Date.now()).slice(-6);
    const vendorName = `E2E供应商${suffix}`;
    const description = `E2E采购${suffix}`;
    const invoiceNo = `INV-E2E-${suffix}`;

    const ctx = await request.newContext({ baseURL: "http://127.0.0.1:8788" });
    await ensureAccounts(ctx);
    await ctx.dispose();

    await page.goto("/");
    await page.getByRole("button", { name: "总览" }).first().click();
    await page.getByRole("button", { name: "业务" }).click();
    await page.getByRole("tab", { name: "采购应付" }).click();
    await expect(page.getByText("采购与应付")).toBeVisible();

    // 1) 供应商
    await page.getByRole("button", { name: "供应商", exact: true }).click();
    // 新增表单默认折叠：先展开
    await page.getByRole("button", { name: "新增供应商 新增" }).click();
    await page.getByLabel("供应商编码").fill(`E2E${suffix}`);
    await page.getByLabel("供应商名称").fill(vendorName);
    await page.getByRole("button", { name: "保存供应商" }).click();
    await expect(page.getByText(vendorName)).toBeVisible();

    // 2) 采购单
    await page.getByRole("button", { name: "采购单", exact: true }).click();
    await page.getByRole("button", { name: "新建采购单 新增" }).click();
    await page.getByLabel("供应商").first().selectOption({ label: `E2E${suffix} ${vendorName}` });
    await page.getByLabel("采购日期").fill("2026-11-05");
    await page.getByLabel("预计到货").fill("2026-11-15");
    await page.getByLabel("金额").fill("5000");
    await page.getByLabel("采购说明").fill(description);
    await page.getByRole("button", { name: "保存采购单" }).click();

    const orderRow = page.locator("div.rounded-lg.border").filter({ hasText: description });
    await expect(orderRow).toBeVisible();
    await orderRow.getByRole("button", { name: "提交" }).click();
    await expect(orderRow.getByText("待审核")).toBeVisible();
    await orderRow.getByRole("button", { name: "通过" }).click();
    await expect(orderRow.getByText("已审核")).toBeVisible();

    // 3) 应付单
    await page.getByRole("button", { name: "应付单", exact: true }).click();
    await page.getByRole("button", { name: /新建应付单/ }).click();
    await page.getByLabel("供应商").first().selectOption({ label: `E2E${suffix} ${vendorName}` });
    // 该供应商是新建的，采购单下拉里只有它自己的一张单
    await page.getByLabel("关联采购单").selectOption({ index: 1 });
    await page.getByLabel("发票号").fill(invoiceNo);
    await page.getByLabel("发票日期").fill("2026-11-10");
    await page.getByLabel("到期日").fill("2026-12-10");
    await page.getByLabel("金额").fill("5000");
    await page.getByLabel("税额").fill("300");
    await page.getByLabel("借方科目（费用/资产）").selectOption({ label: "6601 采购费用" });
    await page.getByLabel("应付科目（负债）").selectOption({ label: "2202 应付账款" });
    await page.getByRole("button", { name: "保存应付单" }).click();

    const payableRow = page.locator("div.rounded-lg.border").filter({ hasText: invoiceNo });
    await expect(payableRow).toBeVisible();
    await payableRow.getByRole("button", { name: "提交" }).click();
    await expect(payableRow.getByText("待审核")).toBeVisible();
    await payableRow.getByRole("button", { name: "通过" }).click();
    await expect(payableRow.getByText("已审核")).toBeVisible();
    // 审核通过才生成凭证草稿（草稿状态下断言凭证号是错的）
    await expect(payableRow.getByText(/GL-\d{6}-\d{4}/)).toBeVisible();

    // 4) 付款
    await payableRow.getByRole("button", { name: "付款", exact: true }).click();
    await payableRow.locator("select").last().selectOption({ label: "1002 银行存款" });
    await payableRow.getByRole("button", { name: "确认付款" }).click();
    await expect(payableRow.getByText("已付款")).toBeVisible();
    await expect(payableRow.getByText(/PAY-\d{6}-\d{4}/)).toBeVisible();
  });
});

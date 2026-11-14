import { test, expect, type Page } from "@playwright/test";

/**
 * 设置项**逐个配置**测试（不是只打开页面）。
 *
 * 每个用例的判据都是「改了 → 真的存住 → 刷新后还在 → 能改回」：
 *   1. 读取当前值（作为基线）
 *   2. 改成另一个值
 *   3. 刷新页面，确认新值仍是它（证明落库，不是只改了内存）
 *   4. 改回基线（保证用例可重复、不污染后续）
 *
 * 覆盖两类控件：
 *   - 开关/档位（即时保存，PUT /api/settings 单键）
 *   - 批量字段（底部「保存」按钮）
 *
 * 说明：本文件只覆盖「基础设置」组。Agent 能力 / 数据与安全各组
 * 有自己的 CRUD 语义（资产 CRUD、权限模式、备份恢复），由 settings-agent.spec.ts
 * 与 settings-data.spec.ts 覆盖，避免把不同语义硬塞进一张表。
 */

const API = "http://127.0.0.1:8788";

async function openSettings(page: Page, group: string, section: string) {
  await page.goto("/");
  await page.getByRole("button", { name: "设置" }).first().click();
  const groupBtn = page.getByRole("button", { name: group, exact: true }).first();
  await groupBtn.waitFor({ state: "visible", timeout: 10_000 });
  if ((await groupBtn.getAttribute("aria-expanded")) !== "true") await groupBtn.click();
  await expect(groupBtn).toHaveAttribute("aria-expanded", "true");
  await page.getByText(section, { exact: true }).first().click();
}

async function settingValue(page: Page, key: string): Promise<string> {
  const res = await page.request.get(`${API}/api/settings`);
  const body = await res.json();
  return String(body.settings?.[key] ?? "");
}

/** 即时保存类：点击 → 断言后端值变了 → 刷新 → 断言仍是新值 → 改回。 */
async function roundTripToggle(
  page: Page,
  opts: {
    key: string;
    open: () => Promise<void>;
    toggle: () => Promise<void>;
    /** 期望的新值；默认 "on"（对 off→on 的开关） */
    expectAfter?: string;
  },
) {
  await opts.open();
  const before = await settingValue(page, opts.key);
  const want =
    opts.expectAfter ?? (before === "on" ? "off" : "on");

  await opts.toggle();
  await expect
    .poll(async () => settingValue(page, opts.key), { timeout: 10_000 })
    .toBe(want);

  // 刷新后仍是新值：证明写进了库，不是只改了前端 state
  await page.reload();
  await page.getByRole("button", { name: "设置" }).first().click();
  await expect
    .poll(async () => settingValue(page, opts.key), { timeout: 10_000 })
    .toBe(want);

  // 改回基线，避免污染后续用例
  await page.request.put(`${API}/api/settings`, { data: { settings: { [opts.key]: before } } });
}

test.describe("设置项逐个配置", () => {
  test("高对比度：开 → 刷新仍在 → 关回", async ({ page }) => {
    await roundTripToggle(page, {
      key: "high_contrast",
      open: () => openSettings(page, "基础设置", "偏好"),
      toggle: async () => {
        await page.getByRole("switch", { name: "高对比度" }).click();
      },
    });
  });

  test("语音提问：切换 → 刷新仍在 → 改回", async ({ page }) => {
    await roundTripToggle(page, {
      key: "voice_input",
      open: () => openSettings(page, "基础设置", "偏好"),
      toggle: async () => {
        await page.getByRole("switch", { name: "语音提问" }).click();
      },
    });
  });

  test("语音播报：切换 → 刷新仍在 → 改回", async ({ page }) => {
    await roundTripToggle(page, {
      key: "voice_output",
      open: () => openSettings(page, "基础设置", "偏好"),
      toggle: async () => {
        await page.getByRole("switch", { name: "语音播报" }).click();
      },
    });
  });

  test("字号档位：标准 → 大 → 刷新仍是「大」 → 改回标准", async ({ page }) => {
    await openSettings(page, "基础设置", "偏好");
    const before = await settingValue(page, "text_scale");
    const target = before === "large" ? "xlarge" : "large";

    await page
      .getByRole("button", { name: target === "large" ? "大" : "特大", exact: true })
      .first()
      .click();
    await expect.poll(async () => settingValue(page, "text_scale"), { timeout: 10_000 }).toBe(target);

    await page.reload();
    await page.getByRole("button", { name: "设置" }).first().click();
    await expect.poll(async () => settingValue(page, "text_scale"), { timeout: 10_000 }).toBe(target);
    // 根元素 data 属性也要跟着变（这是字号真正生效的位置）
    await expect(page.locator("html")).toHaveAttribute("data-text-scale", target);

    await page.request.put(`${API}/api/settings`, { data: { settings: { text_scale: before } } });
  });

  test("涨跌颜色：cn ↔ us → 刷新仍在 → 改回", async ({ page }) => {
    await openSettings(page, "基础设置", "偏好");
    const before = await settingValue(page, "color_scheme");
    const target = before === "us" ? "cn" : "us";
    await page
      .getByRole("button", { name: target === "us" ? "绿涨红跌" : "红涨绿跌", exact: true })
      .first()
      .click();
    await expect
      .poll(async () => settingValue(page, "color_scheme"), { timeout: 10_000 })
      .toBe(target);

    await page.reload();
    await page.getByRole("button", { name: "设置" }).first().click();
    await expect
      .poll(async () => settingValue(page, "color_scheme"), { timeout: 10_000 })
      .toBe(target);

    await page.request.put(`${API}/api/settings`, { data: { settings: { color_scheme: before } } });
  });

  test("默认首页：问答 ↔ 功能 → 刷新仍在 → 改回", async ({ page }) => {
    await openSettings(page, "基础设置", "偏好");
    const before = await settingValue(page, "default_tab");
    const target = before === "chat" ? "features" : "chat";
    await page
      .getByRole("button", { name: target === "chat" ? "问答" : "功能", exact: true })
      .first()
      .click();
    await expect
      .poll(async () => settingValue(page, "default_tab"), { timeout: 10_000 })
      .toBe(target);

    await page.reload();
    await page.getByRole("button", { name: "设置" }).first().click();
    await expect
      .poll(async () => settingValue(page, "default_tab"), { timeout: 10_000 })
      .toBe(target);

    await page.request.put(`${API}/api/settings`, { data: { settings: { default_tab: before } } });
  });

  test("主题模式：浅色/深色切换真实生效", async ({ page }) => {
    await openSettings(page, "基础设置", "偏好");
    await page.getByRole("button", { name: "深色", exact: true }).first().click();
    await expect(page.locator("html")).toHaveClass(/dark/);
    await page.getByRole("button", { name: "浅色", exact: true }).first().click();
    await expect(page.locator("html")).not.toHaveClass(/dark/);
  });

  test("主题色：切换预设真实生效（本机持久化）", async ({ page }) => {
    await openSettings(page, "基础设置", "偏好");
    const radios = page.getByRole("radio");
    expect(await radios.count()).toBeGreaterThan(3);
    await radios.nth(2).click();
    await expect(radios.nth(2)).toHaveAttribute("aria-checked", "true");
    // 刷新后仍是同一个预设
    await page.reload();
    await page.getByRole("button", { name: "设置" }).first().click();
    await expect(page.getByRole("radio").nth(2)).toHaveAttribute("aria-checked", "true");
    await page.getByRole("radio").nth(0).click();
  });
});

test.describe("批量保存字段（改 → 点保存 → 刷新仍在 → 改回）", () => {
  test("账本假设四项可改可存", async ({ page }) => {
    await openSettings(page, "基础设置", "账本规则");
    const before = {
      monthly_income: await settingValue(page, "monthly_income"),
      emergency_target_months: await settingValue(page, "emergency_target_months"),
      essential_categories: await settingValue(page, "essential_categories"),
      savings_goal: await settingValue(page, "savings_goal"),
    };

    // 用与基线不同的值，确保能看出"确实写进去了"
    const income = String(Number(before.monthly_income || 0) + 1111);
    const months = String(Number(before.emergency_target_months || 0) + 1);
    const cats = before.essential_categories === "居住,餐饮,交通" ? "居住,餐饮" : "居住,餐饮,交通";
    const goal = before.savings_goal === "25" ? "20" : "25";

    await page.getByLabel("月收入（元）").fill(income);
    await page.getByLabel("应急金目标（月）").fill(months);
    await page.getByLabel(/必要支出类别/).fill(cats);
    await page.getByLabel("储蓄率目标（%）").fill(goal);

    // 出现「未保存」提示与保存按钮
    await expect(page.getByRole("button", { name: "保存设置" })).toBeVisible();
    await page.getByRole("button", { name: "保存设置" }).click();

    await expect.poll(async () => settingValue(page, "monthly_income"), { timeout: 10_000 }).toBe(income);
    await expect.poll(async () => settingValue(page, "savings_goal"), { timeout: 10_000 }).toBe(goal);
    await expect.poll(async () => settingValue(page, "essential_categories"), { timeout: 10_000 }).toBe(cats);
    await expect
      .poll(async () => settingValue(page, "emergency_target_months"), { timeout: 10_000 })
      .toBe(months);

    // 刷新后仍在
    await page.reload();
    await page.getByRole("button", { name: "设置" }).first().click();
    await expect.poll(async () => settingValue(page, "monthly_income"), { timeout: 10_000 }).toBe(income);

    // 改回基线
    await page.request.put(`${API}/api/settings`, { data: { settings: before } });
  });

  test("输入非法值被后端拒绝（不是静默接受）", async ({ page }) => {
    await openSettings(page, "基础设置", "账本规则");
    const before = await settingValue(page, "savings_goal");
    // savings_goal 合法区间 0-100；填 999 应被拒
    await page.getByLabel("储蓄率目标（%）").fill("999");
    await page.getByRole("button", { name: "保存设置" }).click();
    // 后端拒绝 → 值不变
    await page.waitForTimeout(1500);
    expect(await settingValue(page, "savings_goal")).toBe(before);
  });
});

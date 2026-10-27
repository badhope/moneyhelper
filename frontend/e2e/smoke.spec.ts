import { test, expect } from "@playwright/test";

/**
 * 冒烟测试（v2 对话主导布局）：品牌可见、对话是默认入口、数据浮层 / 设置 / 主题可达。
 * 依赖 global-setup 已种入演示数据；语言固定 zh-CN（playwright.config.ts locale）。
 */

test.describe("应用启动 & 冒烟", () => {
  test("首屏加载品牌 + 对话输入框", async ({ page }) => {
    await page.goto("/");
    // 品牌：侧栏 logo 按钮（Moneyhelper + 标语）
    await expect(page.getByText("Moneyhelper").first()).toBeVisible();
    await expect(page.getByText("记一笔，问一句").first()).toBeVisible();
    // 对话是默认入口：输入框可见
    await expect(page.getByPlaceholder(/问点什么/)).toBeVisible();
  });

  test("侧栏总览入口打开财务工作区，可返回问答", async ({ page }) => {
    await page.goto("/");
    // 品牌负责回到问答；财务入口在侧栏底部
    await page.getByRole("button", { name: "总览" }).first().click();
    await expect(page.getByRole("tab", { name: "总览" })).toHaveAttribute("aria-selected", "true", {
      timeout: 10_000,
    });
    await page.getByRole("button", { name: "返回问答" }).first().click();
    await expect(page.getByPlaceholder(/问点什么/)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("tab", { name: "总览" })).toHaveCount(0);
  });

  test("打开应用不会新建垃圾会话（会话列表加载竞态回归）", async ({ page, request }) => {
    const api = "http://127.0.0.1:8788";
    const list = async () =>
      ((await (await request.get(`${api}/api/sessions`)).json()).sessions ?? []) as unknown[];
    let sessions = await list();
    if (sessions.length === 0) {
      // 全新库场景：先自建一个会话，再验证「打开应用不会额外新建」
      await request.post(`${api}/api/sessions`, { data: {} });
      sessions = await list();
    }
    const before = sessions.length;
    await page.goto("/");
    // 等首屏初始化（bootstrap + 会话列表）稳定
    await expect(page.getByPlaceholder(/问点什么/)).toBeVisible({ timeout: 10_000 });
    await page.waitForTimeout(1200);
    expect((await list()).length).toBe(before);
  });

  test("设置页能打开，看到语言切换与 AI 入口", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "设置" }).first().click();
    await expect(page.getByRole("button", { name: "关闭" })).toBeVisible();
    await expect(page.getByText("AI 回答").first()).toBeVisible();
    await expect(page.getByText("偏好").first()).toBeVisible();
  });

  test("明暗主题切换修改 html 类名", async ({ page }) => {
    await page.goto("/");
    const html = page.locator("html");
    const before = await html.getAttribute("class");
    // Theme button aria-label = 切换明暗（icon only）
    await page.getByRole("button", { name: "切换明暗" }).click();
    await page.waitForTimeout(200);
    const after = await html.getAttribute("class");
    expect(before !== after).toBeTruthy();
  });

  test("切换品牌主题色即时生效并可恢复默认", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "设置" }).first().click();
    const primaryVar = () =>
      page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--primary").trim());

    // 选「麦金」：--primary 变为预设明色值
    await page.getByRole("radio", { name: "麦金" }).click();
    await expect.poll(primaryVar).toBe("38 78% 45%");

    // 恢复默认：变量回落 index.css 墨绿
    await page.getByRole("radio", { name: "墨绿（默认）" }).click();
    await expect.poll(primaryVar).toBe("168 76% 24%");
  });

  test("设置区都有 AI 生成入口（预算/规则/晨报/记忆/Agent）", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "设置" }).first().click();

    // 一键建议型：点「生成建议」；Agent 区是"先描述再生成"型：入口为「AI 生成」
    const expectAi = async (section: string, entry: RegExp) => {
      await page.getByText(section, { exact: true }).first().click();
      await expect(page.getByRole("button", { name: entry }).first()).toBeVisible({ timeout: 10_000 });
    };

    await expectAi("预算", /生成建议/);
    await expectAi("账本规则", /生成建议/);
    await expectAi("每日晨报", /生成建议/);
    await expectAi("长期记忆", /生成建议/);
    await expectAi("技能（Skill）", /AI 一键生成/);
  });

  test("技能定时动作：配置时间/星期并立即触发（结果回显）", async ({ page, request }) => {
    const api = "http://127.0.0.1:8788";
    // 自建技能（e2e 库也可能是被复用的研发库：用独立 id + 测试完删除，避免污染）
    const cfg = (await (await request.get(`${api}/api/agent-config`)).json()).config as {
      skills: Record<string, unknown>;
    };
    cfg.skills["e2e_weekly_note"] = {
      name: "E2E 周报提醒",
      description: "每周日晚提醒看持仓",
      enabled: true,
      action: { prompt: "帮我看看这个月的支出", time: "20:00", weekdays: [6] },
    };
    const saveResp = await request.post(`${api}/api/agent-config`, { data: { config: cfg } });
    expect((await saveResp.json()).ok).toBe(true);

    try {
      await page.goto("/");
      await page.getByRole("button", { name: "设置" }).first().click();
      await page.getByText("技能（Skill）", { exact: true }).first().click();

      // 动作徽标显示 周几 + 时间；「立即触发」按钮（aria-label 带技能名）可用
      const runBtn = page.getByRole("button", { name: "立即执行 E2E 周报提醒" });
      await expect(runBtn).toBeVisible({ timeout: 10_000 });
      await expect(page.getByText(/周日 20:00/).first()).toBeVisible();
      await runBtn.click();

      // 触发结果如实回显（走真实问答管线：确定性兜底即可产生回答）
      await expect(page.getByText(/^已触发/).first()).toBeVisible({ timeout: 30_000 });

      // 触发记录：归档线程可查（含刚触发的一条；标题 + 问题可见）
      await page.getByRole("button", { name: "触发记录 E2E 周报提醒" }).click();
      await expect(page.getByText("触发记录（含定时与手动）").first()).toBeVisible({ timeout: 10_000 });
      await expect(page.getByText("帮我看看这个月的支出").first()).toBeVisible({ timeout: 10_000 });
    } finally {
      // 清理：删除测试技能并保存
      const cfg2 = (await (await request.get(`${api}/api/agent-config`)).json()).config as {
        skills: Record<string, unknown>;
      };
      delete cfg2.skills["e2e_weekly_note"];
      await request.post(`${api}/api/agent-config`, { data: { config: cfg2 } });
    }
  });

  test("定时产出收件箱：侧栏入口 + 未读徽标 + 面板可查技能产出", async ({ page, request }) => {
    const api = "http://127.0.0.1:8788";
    const cfg = (await (await request.get(`${api}/api/agent-config`)).json()).config as {
      skills: Record<string, unknown>;
    };
    cfg.skills["e2e_inbox_probe"] = {
      name: "E2E 收件箱技能",
      description: "收件箱探测",
      enabled: true,
      action: { prompt: "收件箱探测专用问题", time: "20:00", weekdays: [6] },
    };
    await request.post(`${api}/api/agent-config`, { data: { config: cfg } });
    try {
      // 先产生一条技能产出（直接走接口；界面上的「立即触发」已由上一用例覆盖）
      const runResp = await request.post(`${api}/api/skills/e2e_inbox_probe/run`);
      expect((await runResp.json()).ok).toBe(true);

      await page.goto("/");
      // 侧栏收件箱入口（桌面视口默认展示左侧栏）；新产出未读 → 徽标出现
      const entry = page.getByRole("button", { name: "定时产出" }).first();
      await expect(entry).toBeVisible({ timeout: 10_000 });
      await expect(entry.locator("span.rounded-full").first()).toBeVisible({ timeout: 10_000 });
      await entry.click();

      // 面板：标题 + 刚产生的产出（问题文本可见）
      await expect(page.getByRole("complementary", { name: "定时产出" })).toBeVisible({ timeout: 10_000 });
      await expect(page.getByText("收件箱探测专用问题").first()).toBeVisible({ timeout: 10_000 });
    } finally {
      const cfg2 = (await (await request.get(`${api}/api/agent-config`)).json()).config as {
        skills: Record<string, unknown>;
      };
      delete cfg2.skills["e2e_inbox_probe"];
      await request.post(`${api}/api/agent-config`, { data: { config: cfg2 } });
    }
  });
});

test.describe("财务部门看板", () => {
  test("派工 → 四工位运行 → 秘书出呈批件 → 可审批", async ({ page }) => {
    await page.goto("/");
    // 侧栏部门入口
    await page.getByRole("button", { name: "财务部门" }).click();
    await expect(page.getByText("一句话派工，四部门并行取数")).toBeVisible();

    // 派一个"全面盘点"类问题（后端会派全部四部门）
    await page.getByLabel("比如：盘一下上季度").fill("盘一下上季度");
    await page.getByRole("button", { name: /派工/ }).click();

    // 四工位出现（会计/风控/投资/记账），并最终都交件
    for (const name of ["会计部", "风控部", "投资部", "记账部"]) {
      await expect(page.getByText(name).first()).toBeVisible({ timeout: 60_000 });
    }
    // 秘书台出结论
    await expect(page.getByText("结论").first()).toBeVisible({ timeout: 60_000 });
    // 待批 → 批准
    await expect(page.getByText("待批").first()).toBeVisible({ timeout: 30_000 });
    // 精确匹配：历史列表里会有"已批准"文本，模糊匹配会命中多处
    await page.getByRole("button", { name: "批准", exact: true }).click();
    await expect(page.getByText("已处理").first()).toBeVisible({ timeout: 30_000 });
  });

  test("家庭账本：添加成员 → 汇总出现 → 记录借贷 → 结清", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "设置" }).first().click();
    await page.getByRole("button", { name: "家庭账本" }).first().click();

    // 两个成员才可能出现借贷区
    for (const name of ["测试甲", "测试乙"]) {
      await page.getByPlaceholder("例如：小明").fill(name);
      await page.getByRole("button", { name: "添加" }).first().click();
      await expect(page.getByText(name).first()).toBeVisible({ timeout: 10_000 });
    }

    // 家庭汇总块出现（有成员后才渲染）
    await expect(page.getByText("家庭收入").first()).toBeVisible();
    await expect(page.getByText("成员间借贷").first()).toBeVisible();

    // 记录一笔借贷
    const selects = page.locator("select");
    const n = await selects.count();
    // 最后两个 select 是「借出方 / 借入方」
    await selects.nth(n - 2).selectOption({ index: 1 });
    await selects.nth(n - 1).selectOption({ index: 2 });
    await page.locator('input[type="number"]').last().fill("123");
    await page.getByRole("button", { name: "记录借贷" }).click();
    await expect(page.getByText("已结清").or(page.getByText("结清")).first()).toBeVisible({
      timeout: 10_000,
    });
  });
});

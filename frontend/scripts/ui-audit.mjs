/**
 * 界面审查截图：把一个运行中的实例的每个页面、每个弹窗都拍一遍，供人工比对。
 *
 * 用法：
 *   node scripts/ui-audit.mjs                       # 默认 http://127.0.0.1:8799
 *   XIAOMAN_URL=http://127.0.0.1:8788 node scripts/ui-audit.mjs
 *
 * 产物：../out/ui-audit/<桌面|手机>/*.png（不参与 CI）
 * 覆盖：对话空态/回答、财务五页、设置各分区、记账各面板、持仓编辑/K线、
 *       命令面板、部门看板、定时产出、手机抽屉与底栏。
 */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const BASE = process.env.XIAOMAN_URL || "http://127.0.0.1:8799";
const ROOT = resolve(process.cwd(), "../out/ui-audit");
mkdirSync(ROOT, { recursive: true });

const errors = [];
const shot = async (page, name) => page.screenshot({ path: `${ROOT}/${name}.png` });

const browser = await chromium.launch();

// 截图前清空会话：重复运行会在侧栏堆出一列同名会话，噪点会盖住真实问题
const sessions = await (await fetch(`${BASE}/api/sessions`)).json();
for (const s of sessions.sessions ?? []) {
  await fetch(`${BASE}/api/sessions/${s.id}`, { method: "DELETE" });
}

async function newPage(opts) {
  const ctx = await browser.newContext({ locale: "zh-CN", ...opts });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(`${opts.name || ""} pageerror: ${e}`));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`${opts.name || ""} console: ${m.text().slice(0, 160)}`);
  });
  // 跳过首次引导，否则遮罩挡住所有页面
  await page.addInitScript(() => localStorage.setItem("wo.onboarded", "1"));
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.waitForTimeout(700);
  return { ctx, page };
}

const tab = (page, label) => page.locator("[role=tab]", { hasText: label }).first();

// ---------------- 桌面 ----------------
{
  const { ctx, page } = await newPage({ viewport: { width: 1440, height: 900 } });
  await shot(page, "desktop/01-chat-empty");

  await page.getByRole("button", { name: "新对话" }).first().click();
  await page.waitForTimeout(1000);
  await page.locator("main textarea").fill("我的持仓怎么样");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(9000);
  await shot(page, "desktop/02-chat-answer");

  await page.getByRole("button", { name: "总览" }).first().click();
  await page.waitForTimeout(2000);
  await shot(page, "desktop/03-finance-overview");
  for (const t of ["持仓", "投资策略", "行情", "记账", "财务体检"]) {
    await tab(page, t).click();
    await page.waitForTimeout(t === "投资策略" ? 15000 : t === "行情" ? 14000 : 2600);
    await shot(page, `desktop/04-finance-${t}`);
  }

  // 记账页各内联面板
  await tab(page, "记账").click();
  await page.waitForTimeout(900);
  for (const label of ["导入账单", "管理持仓", "添加负债", "添加订阅", "添加目标"]) {
    await page.getByRole("button", { name: label }).first().click();
    await page.waitForTimeout(500);
    await shot(page, `desktop/05-entry-${label}`);
    await page.getByRole("button", { name: label }).first().click();
    await page.waitForTimeout(250);
  }

  // 持仓：编辑弹窗 + K 线
  await tab(page, "持仓").click();
  await page.waitForTimeout(1200);
  await page.getByRole("button", { name: /编辑/ }).first().click();
  await page.waitForTimeout(700);
  await shot(page, "desktop/06-hold-edit");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);
  await page.getByRole("button", { name: /查看.*K线/ }).first().click();
  await page.waitForTimeout(5000);
  await shot(page, "desktop/07-hold-kline");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);

  // 设置各分区
  await page.getByRole("button", { name: "设置" }).first().click();
  await page.waitForTimeout(1000);
  const sections = ["偏好", "账本规则", "预算", "AI 回答", "Agent 与技能", "插件（MCP）", "系统提示词", "知识库", "每日晨报", "长期记忆", "数据与状态", "访问口令", "日志", "审计日志", "溯源链", "家庭账本", "模型评测"];
  for (const s of sections) {
    await page.getByText(s, { exact: true }).first().click();
    await page.waitForTimeout(600);
    await shot(page, `desktop/08-settings-${s}`);
  }
  await page.getByRole("button", { name: "关闭" }).first().click();
  await page.waitForTimeout(500);

  // 命令面板 / 部门 / 收件箱
  await page.keyboard.press("Control+k");
  await page.waitForTimeout(700);
  await shot(page, "desktop/09-cmdk");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);
  await page.getByRole("button", { name: "财务部门" }).first().click();
  await page.waitForTimeout(1200);
  await shot(page, "desktop/10-dept");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(500);
  await page.getByRole("button", { name: "定时产出" }).first().click();
  await page.waitForTimeout(900);
  await shot(page, "desktop/11-inbox");

  await ctx.close();
}

// ---------------- 手机 ----------------
{
  const { ctx, page } = await newPage({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  });
  await shot(page, "phone/01-chat");

  await page.locator("button[aria-label='会话']").first().click();
  await page.waitForTimeout(500);
  await shot(page, "phone/02-drawer");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);

  await page.locator("nav[aria-label='主导航'] button").nth(1).click();
  await page.waitForTimeout(1800);
  await shot(page, "phone/03-finance-overview");
  for (const t of ["持仓", "投资策略", "行情", "记账", "财务体检"]) {
    await tab(page, t).click();
    await page.waitForTimeout(t === "投资策略" ? 15000 : t === "行情" ? 14000 : 3800);
    await shot(page, `phone/04-finance-${t}`);
  }

  await page.locator("nav[aria-label='主导航'] button").last().click();
  await page.waitForTimeout(1000);
  await shot(page, "phone/05-settings");
  for (const g of ["AI 回答", "溯源链", "模型评测"]) {
    await page.getByText(g, { exact: true }).first().click();
    await page.waitForTimeout(1000);
    await shot(page, `phone/06-settings-${g}`);
  }
  await ctx.close();
}

// ---------------- 平板 ----------------
{
  const { ctx, page } = await newPage({ viewport: { width: 768, height: 1024 } });
  await shot(page, "tablet/01-chat");
  await page.getByRole("button", { name: "总览" }).first().click();
  await page.waitForTimeout(1800);
  await shot(page, "tablet/02-finance-overview");
  await ctx.close();
}

await browser.close();
console.log(errors.length ? `页面错误：\n${errors.join("\n")}` : "无页面错误");
console.log(`截图目录：${ROOT}`);

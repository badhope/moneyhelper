import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const OUT = ".tmp/shots2";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("console", (m) => {
  if (m.type() === "error") errors.push(m.text());
});
page.on("pageerror", (e) => errors.push(String(e)));

const BASE = "http://127.0.0.1:5198";
await page.addInitScript(() => {
  try {
    localStorage.setItem("wo.onboarded", "1");
  } catch {}
});
await page.goto(BASE);
await page.waitForSelector("textarea", { timeout: 15000 });
// 关掉可能出现的引导弹窗（空库首启会弹）
const closeBtn = page.getByRole("button", { name: "跳过" }).first();
if (await closeBtn.count()) await closeBtn.click().catch(() => {});
await page.getByRole("button", { name: "设置" }).first().click();
await page.waitForTimeout(600);

const exists = async (label) => {
  const loc = page.getByRole("button", { name: label, exact: true });
  return (await loc.count()) > 0;
};

// A. 设置导航：确认旧「Agent 与技能」已消失、新分区齐全
const navLabels = ["角色（Agent）", "技能（Skill）", "约束（Rules）", "Hook 钩子", "权限", "内置工具", "插件市场", "插件（MCP）"];
const nav = {};
for (const l of navLabels) nav[l] = await exists(l);
nav["Agent 与技能(应已移除)"] = await exists("Agent 与技能");
console.log("NAV", JSON.stringify(nav));

// B. 技能页：空态/列表 + 新增定时字段（打开手写模板）
await page.getByRole("button", { name: "技能（Skill）", exact: true }).first().click();
await page.waitForTimeout(500);
await page.screenshot({ path: `${OUT}/10-skills.png` });
await page.getByRole("button", { name: "手写模板" }).first().click();
await page.waitForTimeout(400);
await page.screenshot({ path: `${OUT}/11-skill-form.png` });

// C. 角色页表单（含 tools 白名单与温度）
await page.getByRole("button", { name: "角色（Agent）", exact: true }).first().click();
await page.waitForTimeout(400);
const editButtons = page.getByRole("button", { name: /编辑/ });
if (await editButtons.count()) {
  await editButtons.first().click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/12-role-form.png` });
}

// D. 市场：搜科研 MCP
await page.getByRole("button", { name: "插件市场", exact: true }).first().click();
await page.waitForTimeout(600);
const search = page.getByPlaceholder("搜索名称或说明");
await search.fill("zotero");
await page.waitForTimeout(400);
await page.screenshot({ path: `${OUT}/13-market-zotero.png` });
await search.fill("");

// E. 移动端 390x844 检查溢出
await page.setViewportSize({ width: 390, height: 844 });
await page.waitForTimeout(600);
await page.screenshot({ path: `${OUT}/14-mobile-skills.png`, fullPage: true });
const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
console.log("MOBILE_OVERFLOW_PX", overflow);

// F. 深色模式角色页
await page.setViewportSize({ width: 1440, height: 900 });
await page.getByRole("button", { name: "角色（Agent）", exact: true }).first().click();
await page.evaluate(() => document.documentElement.classList.add("dark"));
await page.waitForTimeout(500);
await page.screenshot({ path: `${OUT}/15-roles-dark.png` });

console.log("CONSOLE_ERRORS", JSON.stringify(errors));
await browser.close();

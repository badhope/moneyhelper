/**
 * README 展示图：在干净实例上拍一组 1400×860 的界面截图（2x DPR，文字清晰）。
 *
 * 用法：
 *   MONEYHELPER_URL=http://127.0.0.1:8799 node scripts/readme-shots.mjs
 * 产物：docs/screenshots/*.png（随仓库提交，README 直接引用）
 */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const BASE = process.env.MONEYHELPER_URL || "http://127.0.0.1:8799";
const OUT = resolve(process.cwd(), "../docs/screenshots");
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1400, height: 860 },
  deviceScaleFactor: 2,
  locale: "zh-CN",
});
const page = await ctx.newPage();
await page.addInitScript(() => localStorage.setItem("wo.onboarded", "1"));
await page.goto(BASE, { waitUntil: "networkidle" });
await page.waitForTimeout(800);

const shot = (name) => page.screenshot({ path: `${OUT}/${name}.png` });

// 截图前清空会话：脚本会反复新建对话，残留会在侧栏堆成一列「新会话」，
// 拍出来的图不干净，也会让人误以为是产品 bug。
const sessions = await (await fetch(`${BASE}/api/sessions`)).json();
for (const s of sessions.sessions ?? []) {
  await fetch(`${BASE}/api/sessions/${s.id}`, { method: "DELETE" });
}
await page.reload({ waitUntil: "networkidle" });
await page.waitForTimeout(800);

// 1. 对话空态
await shot("01-chat-home");

// 2. 对话回答（含计划、快照、跳转）
await page.getByRole("button", { name: "新对话" }).first().click();
await page.waitForTimeout(900);
await page.locator("main textarea").fill("我的持仓怎么样");
await page.keyboard.press("Enter");
await page.waitForTimeout(10000);
await shot("02-chat-answer");

// 3. 总览
await page.getByRole("button", { name: "总览" }).first().click();
await page.waitForTimeout(3000);
await shot("03-overview");

// 4. 持仓
await page.locator('[role=tab]', { hasText: "持仓" }).first().click();
await page.waitForTimeout(2500);
await shot("04-holdings");

// 5. 行情
await page.locator('[role=tab]', { hasText: "行情" }).first().click();
// 行情页有 4 条迷你走势 + 右侧详情各一次 K 线请求，串行加载约 8-12 秒
await page.waitForTimeout(14000);
await shot("05-market");

// 6. 记账
await page.locator('[role=tab]', { hasText: "记账" }).first().click();
await page.waitForTimeout(1800);
await shot("06-ledger");

// 7. 财务体检
await page.locator('[role=tab]', { hasText: "财务体检" }).first().click();
await page.waitForTimeout(2500);
await shot("07-health");

// 8. 设置
await page.getByRole("button", { name: "设置" }).first().click();
await page.waitForTimeout(1200);
await shot("08-settings");
await page.getByText("AI 回答", { exact: true }).first().click();
await page.waitForTimeout(900);
await shot("09-ai-settings");
await page.getByRole("button", { name: "关闭" }).first().click();
await page.waitForTimeout(600);

// 9. 命令面板
await page.keyboard.press("Control+k");
await page.waitForTimeout(900);
await shot("10-command-palette");
await page.keyboard.press("Escape");
await page.waitForTimeout(400);

// 10. 暗色
await page.evaluate(() => {
  document.documentElement.classList.add("dark");
  localStorage.setItem("wo.theme", "dark");
});
await page.waitForTimeout(900);
await shot("11-dark-mode");

// 11. 手机
await page.evaluate(() => {
  document.documentElement.classList.remove("dark");
  localStorage.setItem("wo.theme", "light");
});
const phone = await browser.newContext({
  viewport: { width: 390, height: 844 },
  deviceScaleFactor: 3,
  isMobile: true,
  hasTouch: true,
  locale: "zh-CN",
});
const mp = await phone.newPage();
await mp.addInitScript(() => localStorage.setItem("wo.onboarded", "1"));
await mp.goto(BASE, { waitUntil: "networkidle" });
await mp.waitForTimeout(1200);
await mp.screenshot({ path: `${OUT}/12-mobile-chat.png` });
await mp.locator("nav[aria-label='主导航'] button").nth(1).click();
await mp.waitForTimeout(3000);
await mp.screenshot({ path: `${OUT}/13-mobile-finance.png` });

console.log("README screenshots ->", OUT);
await browser.close();

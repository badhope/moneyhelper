/**
 * 响应式截图：桌面 / 平板 / 手机三档，验证布局不溢出、导航可用。
 * 产物写入 ../out/shots/，供人工核对（不参与 CI）。
 */
import { chromium, devices } from "playwright";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const BASE = process.env.XIAOMAN_URL || "http://127.0.0.1:8788";
const OUT = resolve(process.cwd(), "../out/shots");
mkdirSync(OUT, { recursive: true });

const cases = [
  { name: "desktop", viewport: { width: 1440, height: 900 } },
  { name: "laptop", viewport: { width: 1024, height: 768 } },
  { name: "tablet", viewport: { width: 768, height: 1024 } },
  { name: "phone", viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
];

const browser = await chromium.launch();
for (const c of cases) {
  const ctx = await browser.newContext({
    viewport: c.viewport,
    isMobile: c.isMobile || false,
    hasTouch: c.hasTouch || false,
    locale: "zh-CN",
    deviceScaleFactor: 1,
  });
  const page = await ctx.newPage();
  // 先标记"已引导"，否则首次访问会被 Onboarding 遮罩挡住（不是布局问题）
  await page.addInitScript(() => {
    try {
      localStorage.setItem("wo.onboarded", "1");
    } catch {}
  });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/${c.name}-chat.png`, fullPage: false });

  // 横向溢出检查：scrollWidth 不应超过 clientWidth + 1
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );

  // 打开数据面板（各尺寸都应有入口）：主导航只暴露「问答/功能」两项，
  // 需先进「功能」页，子 tab 才有「总览」按钮（主导航上没有总览）。
  try {
    await page.getByRole("button", { name: "功能" }).first().click();
    await page.waitForTimeout(400);
    await page.getByRole("button", { name: "总览" }).first().click();
    await page.waitForTimeout(900);
    await page.screenshot({ path: `${OUT}/${c.name}-panel.png`, fullPage: false });
  } catch (e) {
    console.log(`[${c.name}] panel open failed: ${String(e).slice(0, 80)}`);
  }

  console.log(`[${c.name}] ${c.viewport.width}x${c.viewport.height} overflow=${overflow}px`);
  await ctx.close();
}
await browser.close();
console.log("shots ->", OUT);

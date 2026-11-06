#!/usr/bin/env node
// 债务规划页的浏览器实测：进入页面、读关键数字、切换方法、改额外还款额，
// 全程收集 pageerror / console error / 横向溢出，并落一张截图。
//
// 为什么不用 shots-full.mjs：那个脚本只做「点进去截一张」，不做交互断言。
// 这里要验证的是「换个方法 / 改个数字，页面数字真的跟着变」——
// 只有交互后才看输出才能证明接线是通的。

import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.argv[2] || "http://127.0.0.1:8789";
const OUT = process.argv[3] || "shots-debts";

fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ channel: "msedge" }).catch(() => chromium.launch());
const issues = [];

async function collect(page, tag) {
  page.on("pageerror", (e) => issues.push(`${tag} pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") issues.push(`${tag} console: ${m.text()}`);
  });
}

async function openDebts(page) {
  // 首屏是对话页；先进财务区（侧栏「总览」/ 移动端「财务」），再按两级导航点进去
  const entry = page.getByRole("button", { name: /^(总览|Overview|财务|Finance)$/ }).first();
  await entry.waitFor({ state: "visible", timeout: 15000 });
  await entry.click();
  await page.waitForTimeout(1000);

  const group = page.getByRole("button", { name: /^(每天看|Daily)$/ }).first();
  await group.waitFor({ state: "visible", timeout: 15000 });
  await group.click();
  await page.waitForTimeout(300);

  const tab = page.getByRole("tab", { name: /^(还债规划|Debt payoff)$/ }).first();
  await tab.waitFor({ state: "visible", timeout: 10000 });
  await tab.click();
  await page.waitForTimeout(1500);
}

/** 首启引导是 z-50 模态框，会拦截所有点击（不是缺陷，但自动化必须先关掉）。 */
async function dismissOnboarding(page) {
  const btn = page
    .getByRole("button", { name: /关闭引导|Close guide|跳过引导|Skip and start/ })
    .first();
  if (await btn.count()) {
    await btn.click({ timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(400);
  }
}

async function main() {
  for (const vp of [
    { tag: "desktop", width: 1440, height: 900 },
    { tag: "mobile", width: 390, height: 844 },
  ]) {
    const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
    const page = await ctx.newPage();
    await collect(page, vp.tag);

    await page.goto(BASE, { waitUntil: "networkidle", timeout: 30000 });
    await page.waitForTimeout(1500);
    await dismissOnboarding(page);
    await openDebts(page);

    const title = await page.locator("text=/还债规划|Debt payoff plan/").first().textContent();
    if (!title) issues.push(`${vp.tag}: 页面标题未渲染`);

    // 读取结论卡上的还清日期与总利息，作为「数字真的算出来了」的证据
    const bodyText = await page.locator("body").innerText();
    const hasDate = /20\d{2}-\d{2}/.test(bodyText);
    if (!hasDate) issues.push(`${vp.tag}: 未渲染预计还清日期`);

    // 横向溢出
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    if (overflow > 1) issues.push(`${vp.tag}: 横向溢出 ${overflow}px`);

    await page.screenshot({ path: `${OUT}/${vp.tag}-debts-avalanche.png`, fullPage: true });

    // 切换到雪球法，断言顺序文案变化
    const snow = page.getByRole("button", { name: /^(雪球法|Snowball)$/ }).first();
    await snow.click();
    await page.waitForTimeout(1500);
    const afterSwitch = await page.locator("body").innerText();
    if (afterSwitch === bodyText) issues.push(`${vp.tag}: 切换方法后页面内容未变化`);

    // 改额外还款额，等防抖窗口 + 请求返回
    const input = page.locator('input[aria-label="每月额外还款"], input[aria-label="Extra payment / month"]').first();
    await input.fill("6000");
    await page.waitForTimeout(1800);
    const afterExtra = await page.locator("body").innerText();
    if (afterExtra === afterSwitch) issues.push(`${vp.tag}: 改额外还款额后数字未更新`);

    const overflow2 = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    if (overflow2 > 1) issues.push(`${vp.tag}: 交互后横向溢出 ${overflow2}px`);

    await page.screenshot({ path: `${OUT}/${vp.tag}-debts-snowball.png`, fullPage: true });
    await ctx.close();
  }
}

await main();
await browser.close();

if (issues.length) {
  console.error("发现问题：");
  for (const i of issues) console.error(" -", i);
  process.exit(1);
}
console.log("债务规划页实测通过：桌面 + 移动，零报错零溢出，交互后数字有变化");

#!/usr/bin/env node
// 真实浏览器截图：遍历主要页面，产出 PNG 供人工与视觉门禁核对。
// 用法：node e2e/shots-full.mjs [baseUrl] [outDir]
//
// 导航是两级结构：先点组（每天看/判断时/业务/账务/接入），再点该组下的子项。
// 移动端没有顶栏组条，改走底部 TabBar（总览入口）。
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.argv[2] || "http://localhost:5199";
const OUT = process.argv[3] || "shots";

// [文件名, 组文案, 子项文案]；main 为 null 表示停留在对话页
const PAGES = [
  { name: "01-chat", group: null, tab: null },
  { name: "02-overview", group: /^(每天看|Daily)$/, tab: /^(总览|Dashboard)$/ },
  { name: "03-holdings", group: /^(每天看|Daily)$/, tab: /^(持仓|Holdings)$/ },
  { name: "04-ledger", group: /^(每天看|Daily)$/, tab: /^(记账|Ledger)$/ },
  { name: "11-debts", group: /^(每天看|Daily)$/, tab: /^(还债规划|Debt payoff)$/ },
  { name: "05-market", group: /^(判断时|Analyze)$/, tab: /^(行情|Market)$/ },
  { name: "06-strategy", group: /^(判断时|Analyze)$/, tab: /^(投资策略|Strategy)$/ },
  { name: "07-tax", group: /^(账务|Accounting)$/, tab: /^(公司财税|Tax)$/ },
  // 新增：此前从未纳入截图的三个主功能页（也是 i18n 覆盖的重点）
  { name: "08-statements", group: /^(账务|Accounting)$/, tab: /^(财报|Statements)$/ },
  { name: "09-paper", group: /^(账务|Accounting)$/, tab: /^(模拟盘|Paper)$/ },
  { name: "10-research", group: /^(判断时|Analyze)$/, tab: /^(投研|Research)$/ },
];

async function launch() {
  try {
    return await chromium.launch();
  } catch {
    return await chromium.launch({ channel: "msedge" });
  }
}

async function clickByRole(page, role, re) {
  const loc = page.getByRole(role, { name: re }).first();
  await loc.waitFor({ state: "visible", timeout: 10000 });
  await loc.click();
  await page.waitForTimeout(900);
}

const browser = await launch();
fs.mkdirSync(OUT, { recursive: true });
const issues = [];

for (const vp of [
  { tag: "desktop", width: 1440, height: 900 },
  { tag: "mobile", width: 390, height: 844 },
]) {
  const ctx = await browser.newContext({
    viewport: { width: vp.width, height: vp.height },
    deviceScaleFactor: 2,
  });
  const page = await ctx.newPage();
  page.on("console", (m) => {
    if (m.type() === "error") issues.push(`[${vp.tag}] console: ${m.text().slice(0, 140)}`);
  });
  page.on("pageerror", (e) => issues.push(`[${vp.tag}] pageerror: ${String(e).slice(0, 140)}`));

  for (const p of PAGES) {
    try {
      await page.goto(BASE, { waitUntil: "networkidle", timeout: 30000 });
      await page.waitForTimeout(1500);

      // 首启引导是 z-50 模态框，会拦截所有点击（不是 bug，但自动化必须先关掉）。
      // 关闭按钮有 aria-label，直接按 role 找最稳。
      const onboardClose = page.getByRole("button", { name: /关闭引导|Close guide|跳过引导|Skip and start/ }).first();
      if (await onboardClose.count()) {
        await onboardClose.click({ timeout: 5000 }).catch(() => {});
        await page.waitForTimeout(400);
      }

      if (p.group) {
        // 首屏是对话页；先进入财务区（侧栏/底部栏的「总览」入口），
        // 再用分组条切到目标组，最后点组内子项。
        // 桌面侧栏入口叫「总览」，移动端底部栏入口叫「财务」——两个都试。
        const entry = page.getByRole("button", { name: /^(总览|Overview|财务|Finance)$/ }).first();
        await entry.click();
        await page.waitForTimeout(1000);
        await clickByRole(page, "button", p.group);
        await clickByRole(page, "tab", p.tab);
      }

      const file = path.join(OUT, `${vp.tag}-${p.name}.png`);
      await page.screenshot({ path: file, fullPage: true });
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      if (overflow > 2) issues.push(`[${vp.tag}] ${p.name}: horizontal overflow ${overflow}px`);
      console.log(`${vp.tag}/${p.name} ok`);
    } catch (e) {
      issues.push(`[${vp.tag}] ${p.name}: ${String(e).split("\n")[0].slice(0, 140)}`);
      console.log(`${vp.tag}/${p.name} FAIL:`, String(e).slice(0, 900));
    }
  }
  await ctx.close();
}

await browser.close();
if (issues.length) {
  console.log("\nISSUES:");
  for (const i of issues) console.log(" -", i);
  process.exit(1);
}
console.log("\nall clean");

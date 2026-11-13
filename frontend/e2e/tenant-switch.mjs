#!/usr/bin/env node
// 真实浏览器验证全局租户切换（切片 7b）。
// 用法：node e2e/tenant-switch.mjs [baseUrl] [outDir]
//
// 验的是"切了以后真的换了一份数据"，不是"下拉框能打开"：
// 1. 登录 demo 账号；
// 2. 顶栏出现「工作租户」选择器，且当前是 Acme 科技（企业租户）；
// 3. 切到个人租户 → 总账科目应为空（个人租户没有建过科目）；
// 4. 切回 Acme → 总账科目应出现 1001/4001；
// 5. 个人流水在两种租户下都应存在（账本不随租户切换移动）。
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.argv[2] || "http://127.0.0.1:18791";
const OUT = process.argv[3] || "../out/selfcheck-shots";

async function launch() {
  try {
    return await chromium.launch();
  } catch {
    return await chromium.launch({ channel: "msedge" });
  }
}

const issues = [];
const browser = await launch();
fs.mkdirSync(OUT, { recursive: true });

const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
});
const page = await ctx.newPage();
page.on("console", (m) => {
  if (m.type() === "error") issues.push(`console: ${m.text().slice(0, 160)}`);
});
page.on("pageerror", (e) => issues.push(`pageerror: ${String(e).slice(0, 160)}`));

async function api(pathname, init = {}) {
  const token = await page.evaluate(() => localStorage.getItem("wo.accessToken"));
  const resp = await fetch(`${BASE}${pathname}`, {
    ...init,
    headers: {
      ...(init.headers || {}),
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
  });
  return resp.json();
}

async function login() {
  // 直接走登录接口拿 token 再写进 localStorage：比点表单稳，
  // 免得改个 placeholder 就把脚本弄坏。
  const resp = await fetch(`${BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "demo", password: "demo123456" }),
  });
  const body = await resp.json();
  if (!body.access_token) throw new Error(`login failed: ${JSON.stringify(body)}`);
  await page.addInitScript((token) => {
    window.localStorage.setItem("wo.accessToken", token);
  }, body.access_token);
  await page.goto(BASE, { waitUntil: "networkidle", timeout: 30000 });
  await page.waitForTimeout(1800);
}

// 读取顶栏当前显示的租户名
async function topbarTenant() {
  const el = page.locator('select[data-testid="tenant-switcher"]').first();
  if (!(await el.count())) return null;
  const value = await el.inputValue();
  const label = await el.evaluate((n) => {
    const opt = n.options[n.selectedIndex];
    return opt ? opt.textContent : "";
  });
  return { value, label };
}

async function switchTo(tenantId) {
  const el = page.locator('select[data-testid="tenant-switcher"]').first();
  await el.selectOption(String(tenantId));
  await page.waitForTimeout(1800);
}

await login();

// 1. 切换器存在
const sw = await topbarTenant();
if (!sw) issues.push("顶栏没有出现工作租户选择器");
console.log("topbar tenant:", JSON.stringify(sw));

await page.screenshot({ path: path.join(OUT, "tenant-01-switcher.png") });

// 2. 切到个人租户 → 总账科目应为空
await switchTo(1);
const personal = await api("/api/gl/accounts");
const personalCodes = (personal.accounts || []).map((a) => a.code);
console.log("personal tenant gl codes:", JSON.stringify(personalCodes));
if (personalCodes.length !== 0) issues.push(`切到个人租户后仍有总账科目：${personalCodes}`);

const txPersonal = await api("/api/transactions");
const itemsPersonal = (txPersonal.transactions || []).map((t) => t.item);
console.log("personal transactions:", JSON.stringify(itemsPersonal));
if (!itemsPersonal.some((x) => x.includes("个人午餐"))) {
  issues.push("个人流水不在个人账本里");
}
await page.screenshot({ path: path.join(OUT, "tenant-02-personal.png") });

// 3. 切回企业租户 → 总账科目应出现 1001/4001
await switchTo(7100);
const ent = await api("/api/gl/accounts");
const entCodes = (ent.accounts || []).map((a) => a.code);
console.log("enterprise tenant gl codes:", JSON.stringify(entCodes));
if (!entCodes.includes("1001") || !entCodes.includes("4001")) {
  issues.push(`切回企业租户后没有看到 1001/4001：${entCodes}`);
}

const txEnt = await api("/api/transactions");
const itemsEnt = (txEnt.transactions || []).map((t) => t.item);
console.log("enterprise view transactions:", JSON.stringify(itemsEnt));
if (!itemsEnt.some((x) => x.includes("个人午餐"))) {
  issues.push("切到企业租户后个人流水丢了——账本不该随租户切换移动");
}

// 4. 组织页应显示企业租户
await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
await page.waitForTimeout(1500);
const overview = await api("/api/org/overview");
console.log("org overview tenant id:", overview.tenant?.id);
if (overview.tenant?.id !== 7100) issues.push(`组织页租户不对：${overview.tenant?.id}`);
await page.screenshot({ path: path.join(OUT, "tenant-03-enterprise.png") });

// 5. 影子记录应能查到
const shadow = await api("/api/authz/shadow/summary");
console.log("shadow:", JSON.stringify({ total: shadow.total, mismatches: shadow.mismatches }));
if (!shadow.total) issues.push("影子表没有任何记录");

// 6. 只读角色：建单入口应隐藏（不能"按钮能点、点了 403"）
const viewerToken = await (
  await fetch(`${BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "viewer", password: "viewer123456" }),
  })
).json();
if (!viewerToken.access_token) throw new Error("viewer login failed");
await page.addInitScript((token) => {
  window.localStorage.setItem("wo.accessToken", token);
}, viewerToken.access_token);
await page.goto(BASE, { waitUntil: "networkidle", timeout: 30000 });
await page.waitForTimeout(1500);

const caps = await api("/api/org/capabilities");
console.log("viewer capabilities:", JSON.stringify(caps));
if (caps.permissions.includes("expense:create")) {
  issues.push("viewer 的权限点里不该有 expense:create");
}

// 切到「业务 → 报销」页，看建单按钮是否被禁用/隐藏
await page.getByRole("button", { name: /^(总览|Overview|财务|Finance)$/ }).first().click();
await page.waitForTimeout(900);
await page.getByRole("button", { name: /^(业务|Operations)$/ }).first().click();
await page.waitForTimeout(700);
await page.getByRole("tab", { name: /^(报销|Expenses)$/ }).first().click();
await page.waitForTimeout(1500);

const saveBtn = page.getByRole("button", { name: /保存草稿|Save draft/ }).first();
if (await saveBtn.count()) {
  const disabled = await saveBtn.isDisabled();
  console.log("viewer save-draft disabled:", disabled);
  if (!disabled) issues.push("只读角色的「保存草稿」按钮仍可点");
} else {
  console.log("viewer save-draft button not rendered");
}
const readonlyHint = await page.getByText(/当前角色只读/).count();
if (!readonlyHint) issues.push("只读角色看不到只读提示");
await page.screenshot({ path: path.join(OUT, "tenant-04-viewer-readonly.png") });

await ctx.close();
await browser.close();

if (issues.length) {
  console.log("\nISSUES:");
  for (const i of issues) console.log(" -", i);
  process.exit(1);
}
console.log("\nall clean");

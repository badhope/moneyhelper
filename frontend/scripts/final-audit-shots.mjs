import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const OUT = ".tmp/final-shots";
mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
const errors = [];

async function shoot(page, name) {
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false });
}

async function openSettings(page, section) {
  await page.getByRole("button", { name: "设置" }).first().click();
  if (section) {
    await page.getByRole("button", { name: section, exact: true }).first().click();
    await page.waitForTimeout(500);
  }
}

// ---------- 桌面 1440 ----------
const d = await browser.newPage({ viewport: { width: 1440, height: 900 } });
d.on("pageerror", (e) => errors.push("desktop:" + String(e)));
d.on("console", (m) => m.type() === "error" && errors.push("desktop:" + m.text()));
await d.addInitScript(() => {
  try {
    localStorage.setItem("wo.onboarded", "1");
  } catch {}
});
await d.goto("http://127.0.0.1:5198/");
await d.waitForSelector("textarea");
const skip = d.getByRole("button", { name: "跳过" }).first();
if (await skip.count()) await skip.click().catch(() => {});
await openSettings(d, "约束（Rules）");
await shoot(d, "d01-rules-cards");

await d.getByRole("button", { name: "技能（Skill）", exact: true }).first().click();
await d.waitForTimeout(400);
await shoot(d, "d02-skills-cards");

await d.getByRole("button", { name: "插件（MCP）", exact: true }).first().click();
await d.waitForTimeout(800);
await shoot(d, "d03-mcp-cards");

await d.getByRole("button", { name: "插件市场", exact: true }).first().click();
await d.waitForTimeout(800);
await shoot(d, "d04-market");

await d.getByRole("button", { name: "内置工具", exact: true }).first().click();
await d.waitForTimeout(700);
const showList = d.getByRole("button", { name: "显示清单" });
if (await showList.count()) await showList.click();
await d.waitForTimeout(500);
await shoot(d, "d05-tools-cards");

// 深色模式：用 localStorage 预设（主题按钮在设置页被遮罩覆盖，不点它）
const dark = await browser.newPage({ viewport: { width: 1440, height: 900 } });
dark.on("pageerror", (e) => errors.push("dark:" + String(e)));
await dark.addInitScript(() => {
  try {
    localStorage.setItem("wo.onboarded", "1");
    localStorage.setItem("wo.theme", "dark");
  } catch {}
});
await dark.goto("http://127.0.0.1:5198/");
await dark.waitForSelector("textarea");
const ds = dark.getByRole("button", { name: "跳过" }).first();
if (await ds.count()) await ds.click().catch(() => {});
await openSettings(dark, "角色（Agent）");
await dark.waitForTimeout(600);
await shoot(dark, "d06-roles-dark");

// ---------- 平板 768 ----------
const t = await browser.newPage({ viewport: { width: 768, height: 1024 } });
t.on("pageerror", (e) => errors.push("tablet:" + String(e)));
await t.addInitScript(() => {
  try {
    localStorage.setItem("wo.onboarded", "1");
  } catch {}
});
await t.goto("http://127.0.0.1:5198/");
await t.waitForSelector("textarea");
const skip2 = t.getByRole("button", { name: "跳过" }).first();
if (await skip2.count()) await skip2.click().catch(() => {});
await openSettings(t, "约束（Rules）");
await shoot(t, "t01-rules");
const tCols = await t.evaluate(() => {
  const ul = [...document.querySelectorAll("ul")].find((u) => u.className.includes("grid"));
  return ul ? getComputedStyle(ul).gridTemplateColumns.split(" ").length : 0;
});

// ---------- 手机 390 ----------
const m = await browser.newPage({ viewport: { width: 390, height: 844 } });
m.on("pageerror", (e) => errors.push("mobile:" + String(e)));
await m.addInitScript(() => {
  try {
    localStorage.setItem("wo.onboarded", "1");
  } catch {}
});
await m.goto("http://127.0.0.1:5198/");
await m.waitForSelector("textarea");
const skip3 = m.getByRole("button", { name: "跳过" }).first();
if (await skip3.count()) await skip3.click().catch(() => {});
await openSettings(m, "约束（Rules）");
await shoot(m, "m01-rules");
const mCols = await m.evaluate(() => {
  const ul = [...document.querySelectorAll("ul")].find((u) => u.className.includes("grid"));
  return ul ? getComputedStyle(ul).gridTemplateColumns.split(" ").length : 0;
});
const overflow = await m.evaluate(
  () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
);
await m.getByRole("button", { name: "插件（MCP）", exact: true }).first().click();
await m.waitForTimeout(700);
await shoot(m, "m02-mcp");

console.log(JSON.stringify({ tabletCols: tCols, mobileCols: mCols, mobileOverflow: overflow }));
console.log("ERRORS", JSON.stringify(errors));
await browser.close();

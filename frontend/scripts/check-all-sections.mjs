import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
const OUT = ".tmp/shots3";
mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));
await page.addInitScript(() => { try { localStorage.setItem("wo.onboarded", "1"); } catch {} });
await page.goto("http://127.0.0.1:5198/");
await page.waitForSelector("textarea", { timeout: 15000 });
const skip = page.getByRole("button", { name: "跳过" }).first();
if (await skip.count()) await skip.click().catch(() => {});
await page.getByRole("button", { name: "设置" }).first().click();
await page.waitForTimeout(500);
const sections = await page.locator("nav[aria-label] button").allInnerTexts();
console.log("SECTIONS", JSON.stringify(sections));
const results = [];
for (const label of sections) {
  const clean = label.trim();
  if (!clean) continue;
  await page.getByRole("button", { name: clean, exact: true }).first().click();
  await page.waitForTimeout(350);
  const overflow = await page.evaluate(() => {
    const el = document.querySelector(".overflow-y-auto");
    return el ? el.scrollWidth - el.clientWidth : -1;
  });
  const body = await page.locator("body").innerText();
  const err = /加载失败|出错了|Cannot read|undefined/.test(body);
  results.push({ section: clean, overflowX: overflow, suspicious: err });
  await page.screenshot({ path: `${OUT}/${clean.replace(/[^\w\u4e00-\u9fa5]/g, "_")}.png` });
}
console.log("RESULTS", JSON.stringify(results, null, 1));
console.log("CONSOLE_ERRORS", JSON.stringify(errors));
await browser.close();

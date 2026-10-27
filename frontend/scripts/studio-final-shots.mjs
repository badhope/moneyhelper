import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const OUT = ".tmp/shots4";
mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errs = [];
page.on("console", (m) => m.type() === "error" && errs.push(m.text()));
page.on("pageerror", (e) => errs.push(String(e)));
await page.addInitScript(() => {
  try {
    localStorage.setItem("wo.onboarded", "1");
  } catch {}
});

const API = "http://127.0.0.1:5198";
await page.goto(`${API}/`);
await page.waitForSelector("textarea");
const skip = page.getByRole("button", { name: "跳过" }).first();
if (await skip.count()) await skip.click().catch(() => {});

// 1) 对话内添加技能（带定时）
const box = page.locator("textarea").first();
await box.fill("添加技能 周报助手：每周五下午5点30分汇总本周收支并给三条建议");
await box.press("Enter");
await page.waitForTimeout(2200);
await page.screenshot({ path: `${OUT}/20-chat-skill-schedule.png` });

// 2) 设置 → 技能：确认新技能带定时徽标
await page.getByRole("button", { name: "设置" }).first().click();
await page.getByRole("button", { name: "技能（Skill）", exact: true }).first().click();
await page.waitForTimeout(700);
await page.screenshot({ path: `${OUT}/21-skill-scheduled.png` });

// 3) 技能 → 立即执行 → 触发记录
const runBtn = page.getByRole("button", { name: "立即执行 周报助手" }).first();
if (await runBtn.count()) {
  await runBtn.click();
  await page.waitForTimeout(2000);
  await page.getByRole("button", { name: "触发记录 周报助手" }).first().click();
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${OUT}/22-skill-history.png` });
}

// 4) 内置工具：显示清单
await page.getByRole("button", { name: "内置工具", exact: true }).first().click();
await page.getByRole("button", { name: "显示清单" }).click();
await page.waitForTimeout(500);
await page.screenshot({ path: `${OUT}/23-internal-tools-list.png` });

// 5) 诊断 + 看门狗
await page.getByRole("button", { name: "一键自检" }).click();
await page.waitForTimeout(1500);
await page.screenshot({ path: `${OUT}/24-diagnostics.png` });

// 6) 约束页
await page.getByRole("button", { name: "约束（Rules）", exact: true }).first().click();
await page.waitForTimeout(500);
await page.screenshot({ path: `${OUT}/25-rules.png` });

// 7) Hook 页
await page.getByRole("button", { name: "Hook 钩子", exact: true }).first().click();
await page.waitForTimeout(500);
await page.screenshot({ path: `${OUT}/26-hooks.png` });

// 8) 提示词页（叠加旧 PromptSection + 新 AssetManager）
await page.getByRole("button", { name: "系统提示词", exact: true }).first().click();
await page.waitForTimeout(500);
await page.screenshot({ path: `${OUT}/27-prompts.png` });

// 9) 移动端 390：技能页 + 权限页
await page.setViewportSize({ width: 390, height: 844 });
await page.getByRole("button", { name: "权限", exact: true }).first().click();
await page.waitForTimeout(500);
await page.screenshot({ path: `${OUT}/28-mobile-permissions.png`, fullPage: true });
const overflow = await page.evaluate(
  () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
);
console.log("MOBILE_OVERFLOW", overflow);
console.log("ERRORS", JSON.stringify(errs));
await browser.close();

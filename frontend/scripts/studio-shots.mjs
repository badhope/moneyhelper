import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const OUT = ".tmp/shots";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("console", (m) => {
  if (m.type() === "error") errors.push(m.text());
});
page.on("pageerror", (e) => errors.push(String(e)));

const API = "http://127.0.0.1:8788";
await fetch(`${API}/api/studio/permissions`, {
  method: "PUT",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ mode: "open", allow_chat_admin: true, allow_cli_admin: true, allow_remote_install: true }),
});

await page.goto("http://127.0.0.1:5198/");
await page.waitForSelector("textarea", { timeout: 15000 });

// 1. Chat: 对话内添加技能
const box = page.locator("textarea").first();
await box.fill("添加技能 周报助手：每周五汇总本周收支并给三条建议");
await box.press("Enter");
await page.waitForTimeout(2500);
await page.screenshot({ path: `${OUT}/01-chat-create.png` });

// 2-8. 设置页各分区
const sections = [
  ["角色（Agent）", "02-roles"],
  ["技能（Skill）", "03-skills"],
  ["约束（Rules）", "04-rules"],
  ["Hook 钩子", "05-hooks"],
  ["权限", "06-permissions"],
  ["插件市场", "07-market"],
  ["内置工具", "08-internal"],
  ["插件（MCP）", "09-mcp"],
];
await page.getByRole("button", { name: "设置" }).first().click();
for (const [label, name] of sections) {
  await page.getByRole("button", { name: label, exact: true }).first().click();
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${OUT}/${name}.png` });
}

// 9. 内置工具显示清单
await page.getByRole("button", { name: "内置工具", exact: true }).first().click();
await page.getByRole("button", { name: "显示清单" }).click();
await page.waitForTimeout(400);
await page.screenshot({ path: `${OUT}/10-internal-list.png` });

// 10. 角色页：AI 生成面板
await page.getByRole("button", { name: "技能（Skill）", exact: true }).first().click();
await page.getByRole("button", { name: "AI 一键生成" }).first().click();
await page.waitForTimeout(400);
await page.screenshot({ path: `${OUT}/11-ai-generate.png` });

// 11. 拖拽区
await page.getByRole("button", { name: "拖拽导入" }).first().click();
await page.waitForTimeout(400);
await page.screenshot({ path: `${OUT}/12-dropzone.png` });

console.log("console errors:", JSON.stringify(errors, null, 2));
await browser.close();

import { test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/**
 * 视觉基线截图（工具，不是用例）：给「改样式 / 合并组件」类改动留可对比的前后图。
 *
 * 为什么用 spec 而不是独立脚本：这样能白拿 playwright.config.ts 的 webServer
 * （后端 :8788 专用测试库 + 前端 :5198 反代）与 globalSetup（种演示数据），
 * 不需要自己管进程和端口。
 *
 * 用法：
 *   SHOTS=1 npx playwright test e2e/shots-pages.spec.ts
 *   SHOTS=1 SHOTS_ONLY=gl,bank npx playwright test e2e/shots-pages.spec.ts
 * 产物：frontend/../out/shots/<kind>.png（整页，1440×900 视口）
 *
 * 不加 SHOTS=1 时整个文件跳过，日常 `npx playwright test` 不受影响。
 */

const ONLY = process.env.SHOTS_ONLY ? process.env.SHOTS_ONLY.split(",") : null;
const OUT = path.resolve(process.cwd(), "../out/shots");

// 与 src/lib/nav.ts 的分组一一对应（分组名与子页名取自 zh.ts）
const GROUPS: { group: string; tabs: [string, string][] }[] = [
  {
    group: "每天看",
    tabs: [
      ["overview", "总览"],
      ["holdings", "持仓"],
      ["ledger", "记账"],
      ["debts", "还债规划"],
    ],
  },
  {
    group: "判断时",
    tabs: [
      ["market", "行情"],
      ["research", "投研"],
      ["strategy", "投资策略"],
      ["health", "财务体检"],
    ],
  },
  {
    group: "业务",
    tabs: [
      ["expenses", "报销"],
      ["procurement", "采购应付"],
      ["longtask", "长任务"],
    ],
  },
  {
    group: "账务",
    tabs: [
      ["gl", "总账"],
      ["bank", "银行对账"],
      ["statements", "财报"],
      ["tax", "公司财税"],
      ["paper", "模拟盘"],
    ],
  },
  { group: "接入", tabs: [["connect", "连接中心"]] },
];

test.describe("视觉基线截图", () => {
  test.skip(!process.env.SHOTS, "仅 SHOTS=1 时运行");

  test("逐页整页截图", async ({ page }) => {
    test.setTimeout(240_000);
    fs.mkdirSync(OUT, { recursive: true });
    await page.addInitScript(() => {
      try {
        localStorage.setItem("wo.onboarded", "1");
      } catch {}
    });
    await page.goto("/", { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "总览" }).first().click();
    await page.waitForTimeout(600);

    let n = 0;
    for (const { group, tabs } of GROUPS) {
      const groupBtn = page.getByRole("button", { name: group, exact: true }).first();
      if (await groupBtn.count()) {
        await groupBtn.click();
        await page.waitForTimeout(150);
      }
      for (const [kind, label] of tabs) {
        if (ONLY && !ONLY.includes(kind)) continue;
        const trigger = page.getByRole("tab", { name: label, exact: true }).first();
        if (await trigger.count()) {
          await trigger.click();
        } else {
          const btn = page.getByRole("button", { name: label, exact: true }).first();
          if (!(await btn.count())) continue;
          await btn.click();
        }
        // 图表是异步挂载的，等一帧再截
        await page.waitForTimeout(700);
        await page.screenshot({ path: path.join(OUT, `${kind}.png`), fullPage: true });
        n += 1;
      }
    }
    test.info().annotations.push({ type: "shots", description: `${n} 张 -> ${OUT}` });
  });
});

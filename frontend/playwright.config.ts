import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { defineConfig, devices } from "@playwright/test";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

/**
 * e2e 配置：启动后端（uvicorn :8788，专用测试库 e2e.db）+ 前端 dev（vite :5198，/api 反代到后端）。
 * globalSetup 先加载种子数据（positions/transactions/subscriptions），再开始测试。
 *
 * 用法：
 *   npx playwright test                # 头默模式
 *   npx playwright test --headed       # 看得见的浏览器
 *   npx playwright test --debug        # 单步调试
 */
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  // 2 核 / 7G 开发机上 Vite 冷启动 + chromium 首帧经常超过 7s：
  // expect 放宽到 12s、整例 45s，并允许本地重试一次，避免把资源抖动误报成功能回归。
  timeout: 45_000,
  expect: { timeout: 12_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 1,
  workers: 1,
  reporter: process.env.CI ? "github" : [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5198",
    locale: "zh-CN",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      // 默认仍是 Playwright 自带 Chromium；网络下载受限的机器可设
      // PLAYWRIGHT_CHANNEL=msedge / chrome 复用本机已安装浏览器，
      // 避免"下载失败 → 全部用例误报失败"。
      use: {
        ...devices["Desktop Chrome"],
        ...(process.env.PLAYWRIGHT_CHANNEL
          ? { channel: process.env.PLAYWRIGHT_CHANNEL }
          : {}),
      },
    },
  ],
  webServer: [
    {
      // 后端：专用测试库，避免污染研发者的 wealth.db
      command: "bash ../scripts/e2e-backend.sh",
      cwd: __dirname,
      port: 8788,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        // 必须绝对路径：e2e-backend.sh 会先 cd 到 backend/，相对路径会解析成 backend/backend/data/e2e.db
        MONEYHELPER_DB_PATH: resolve(__dirname, "../backend/data/e2e.db"),
        // 关限流：整轮 e2e 从同一 IP 在 1 分钟内发出 200+ 请求，会撞上默认 200/分钟的上限，
        // 表现为每轮随机某个用例失败（视用例执行顺序而定），极易误判为功能回归。
        MONEYHELPER_DISABLE_RATE_LIMIT: "1",
        // 强制清空模型配置：e2e 断言的是确定性模板路径（"确定性兜底即可产生回答"）。
        // 若继承开发者 shell 里的 LLM_API_KEY，用例会真的去调模型（一次 30-60s），
        // 表现为随机超时失败——这是测试隔离问题，不是产品缺陷。
        LLM_API_KEY: "",
        LLM_BASE_URL: "",
        LLM_MODEL: "",
      },
    },
    {
      // 前端 dev：/api 反代到 8788
      command: "npm run dev",
      cwd: __dirname,
      port: 5198,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});

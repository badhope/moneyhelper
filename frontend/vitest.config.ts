import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [react() as never],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // 实测：默认每跑一个测试文件就新建一次 jsdom（25 个文件 → 256s / 总 344s，占 77%）。
    // 本项目的用例都只读渲染 + 纯函数，没有写全局状态，所以共享一个环境是安全的。
    isolate: false,
    pool: "vmThreads",
  },
});

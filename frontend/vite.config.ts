import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

/**
 * 版本号来自后端单一真源 backend/app/version.py。
 *
 * 为什么不在前端再存一份：版本号此前三处漂移（1.0.0 / 1.4.0 / 2.1.0），
 * 用户问"这是什么版本"会得到不同答案。现在构建时从 Python 源文件读，
 * 前端只有这一个来源；package.json 的 version 由发版脚本同步。
 */
const HERE = fileURLToPath(new URL(".", import.meta.url));

function readAppVersion(): string {
  try {
    const src = readFileSync(resolve(HERE, "../backend/app/version.py"), "utf-8");
    const m = src.match(/^__version__\s*=\s*["']([^"']+)["']/m);
    return m?.[1] ?? "0.0.0";
  } catch {
    return "0.0.0";
  }
}

// 开发期：vite 跑 5198，/api 反代到后端 8788（避免跨域）。
// 注意：用 8788/5198 专用端口，避开其他 AI 工具可能抢占的 8787/5199。
// 生产期：vite build 出 dist，由 FastAPI 直接托管（单端口，无跨域）。
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // 注入 __APP_VERSION__，前端无需再存一份版本号
  define: {
    __APP_VERSION__: JSON.stringify(readAppVersion()),
  },
  // 生产构建剔除调试类 console（保留 console.error/warn，便于线上排查）
  esbuild: {
    pure: ["console.log", "console.debug", "console.info"],
  },
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5198,
    host: "0.0.0.0",
    allowedHosts: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8788", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    // echarts 已按依赖族独立分包且懒加载，555kB 属预期；上调阈值消除误报警告
    // echarts 独立分包且**懒加载**（不在首屏请求路径上），它的体积不影响首屏。
    // 阈值设 750 是为了「超过就说明混进了不该进来的东西」，而不是追求压到 650。
    chunkSizeWarningLimit: 750,
    // 按依赖族分包：echarts / markdown 渲染 / react 各自独立缓存，应用主包保持轻
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes("node_modules/echarts") || id.includes("node_modules/zrender")) return "echarts";
          if (
            id.includes("node_modules/react-markdown") ||
            id.includes("node_modules/remark-gfm") ||
            id.includes("node_modules/remark-parse") ||
            id.includes("node_modules/micromark") ||
            id.includes("node_modules/mdast-util") ||
            id.includes("node_modules/hast-util") ||
            id.includes("node_modules/unified") ||
            id.includes("node_modules/vfile") ||
            id.includes("node_modules/react-syntax-highlighter") ||
            id.includes("node_modules/highlight.js") ||
            id.includes("node_modules/refractor") ||
            id.includes("node_modules/prismjs") ||
            id.includes("node_modules/lowlight")
          )
            return "markdown";
          if (id.includes("node_modules/react") || id.includes("node_modules/scheduler")) return "react";
          return undefined;
        },
      },
    },
  },
});

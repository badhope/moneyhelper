/* 每次构建时替换 sw.js 里的缓存版本号，保证发布新版后浏览器更新 SW 并清理旧缓存。

 * 版本戳用内容哈希而不是时间戳：内容没变就不改 SW 文件，
 * 避免每次构建都产生一个"无差异的新版本"并让所有客户端重新下载。
 * 匹配规则同时兼容旧格式（旧脚本只认 v 前缀，而 sw.js 里实际写的是时间戳，
 * 导致替换静默失效，缓存版本永远不变）。
 */
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";

const swPath = new URL("../public/sw.js", import.meta.url);
const src = readFileSync(swPath, "utf8");

const CACHE_RE = /const CACHE = "moneyhelper-pwa-[^"]*";/;
if (!CACHE_RE.test(src)) {
  console.error("[bump-sw] 未找到 CACHE 常量，跳过（请检查 public/sw.js）");
  process.exit(0);
}

// 用去掉版本行后的内容算哈希：内容不变 → 版本不变 → 不必重新发布 SW
const body = src.replace(CACHE_RE, "");
const stamp = `moneyhelper-pwa-${createHash("sha256").update(body).digest("hex").slice(0, 12)}`;
const out = src.replace(CACHE_RE, `const CACHE = "${stamp}";`);

if (out === src) {
  console.log("[bump-sw] cache version unchanged:", stamp);
} else {
  writeFileSync(swPath, out);
  console.log("[bump-sw] cache version:", stamp);
}

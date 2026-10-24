/* 小满 · Service Worker
 * - 静态资源：cache-first（先查缓存，未命中再走网络）
 * - API 请求：白名单跳过（/api/* 始终走网络，不缓存）
 * - HTML 导航：网络优先 + 离线兜底页
 * - 仅缓存同源资源；新 SW 安装后清理旧缓存。 */

const CACHE = "xiaoman-pwa-1afe659f8b4a"; // 缓存版本号，升级 PWA 时修改即可触发旧缓存清理

// 预缓存清单；图标不强行预缓存（已存在则缓存，也无妨跳过）。
const PRECACHE = ["/", "/index.html", "/manifest.webmanifest"];

// 离线兜底页：内联于 SW，不依赖外部文件
const OFFLINE_HTML = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>小满 Xiaoman · 离线模式</title>
<style>
  :root { color-scheme: dark; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    min-height: 100vh; display: flex; align-items: center; justify-content: center;
    background: #0f0f10; color: #e6e6e8; font-family: system-ui, -apple-system, sans-serif;
    padding: 24px; text-align: center;
  }
  .card { max-width: 420px; padding: 32px 24px; border: 1px solid #2a2a2e; border-radius: 12px; }
  h1 { font-size: 20px; margin-bottom: 12px; color: #b8891f; }
  p { font-size: 14px; line-height: 1.7; color: #9a9aa0; margin-bottom: 20px; }
  button {
    font-size: 14px; padding: 8px 20px; border: 1px solid #b8891f; border-radius: 6px;
    background: transparent; color: #b8891f; cursor: pointer;
  }
  button:hover { background: rgba(184,137,31,.12); }
</style>
</head>
<body>
  <div class="card">
    <h1>当前处于离线状态</h1>
    <p>无法连接到服务器。请检查网络后重连；已缓存的页面仍可浏览。</p>
    <button onclick="window.location.reload()">重新连接</button>
  </div>
</body>
</html>`;

// 安装：预缓存壳资源，完成后立即激活
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting()),
  );
});

// 激活：清理旧缓存，立即接管所有标签页
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

// 请求拦截
self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // 跨源不缓存
  if (url.pathname.startsWith("/api/")) return;     // API 白名单：永远走网络

  // HTML 导航：网络优先，离线时回退 → 缓存的壳 → 内联兜底页
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((res) => {
          if (res.ok) caches.open(CACHE).then((c) => c.put(request, res.clone()));
          return res;
        })
        .catch(async () => (await caches.match("/index.html")) || new Response(OFFLINE_HTML, { headers: { "Content-Type": "text/html; charset=utf-8" } })),
    );
    return;
  }

  // 静态资源（JS/CSS/字体/图像等）：cache-first
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(request, copy));
        }
        return res;
      }).catch(async () => {
        // 网络失败且无缓存：导航类请求给兜底页，其他返回不透明错误
        return request.mode === "navigate"
          ? new Response(OFFLINE_HTML, { headers: { "Content-Type": "text/html; charset=utf-8" } })
          : Response.error();
      });
    }),
  );
});

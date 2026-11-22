/** API 访问层：统一带访问口令（Authorization: Bearer，不进 URL/日志）；
 * 401 时通过注册的回调打开应用内口令对话框，输入后自动重试一次；
 * 普通请求带超时，SSE 由 fetch-event-source 管理断线重试。
 */

import { fetchEventSource } from "@microsoft/fetch-event-source";
import { demoHeader } from "@/lib/demo";

const TOKEN_KEY = "wo.accessToken";
const REQUEST_TIMEOUT_MS = 20_000;
/** 上传/解析类请求：20MB 的文件过 OCR、pdfplumber（≤30 页）在慢机器上远超 20s，
 *  用同一个超时会把"还在跑"误报成"请求超时"，用户重试还会产生重复单据。 */
export const SLOW_REQUEST_TIMEOUT_MS = 120_000;

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

export function setToken(token: string): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

/** 口令对话框回调（由 App 注册，返回用户输入或 null=取消） */
let authPrompt: (() => Promise<string | null>) | null = null;

export function setAuthPromptHandler(fn: (() => Promise<string | null>) | null): void {
  authPrompt = fn;
}

/** 401 去重：并发请求同时 401 时只弹一次口令框，后续请求等结果后各自重试 */
let authPromptInFlight: Promise<string | null> | null = null;

async function askAuth(): Promise<string | null> {
  if (!authPrompt) return null;
  if (authPromptInFlight) return authPromptInFlight;
  authPromptInFlight = authPrompt().finally(() => {
    authPromptInFlight = null;
  });
  return authPromptInFlight;
}

/** 带超时的 fetch：外部 signal 与超时共存（任一触发即中止）。 */
async function fetchWithTimeout(path: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), timeoutMs);
  const external = init.signal;
  const onAbort = () => ctrl.abort();
  if (external) {
    if (external.aborted) ctrl.abort();
    else external.addEventListener("abort", onAbort);
  }
  try {
    return await fetch(path, { ...init, signal: ctrl.signal });
  } finally {
    window.clearTimeout(timer);
    external?.removeEventListener("abort", onAbort);
  }
}

function authHeaders(init: RequestInit): HeadersInit {
  const token = getToken();
  // FormData/Blob 由浏览器自己带 Content-Type（含 multipart boundary）；
  // 手动写死 application/json 会把 boundary 覆盖掉，后端解析不到文件。
  const isForm = typeof FormData !== "undefined" && init.body instanceof FormData;
  return {
    ...(isForm ? {} : { "Content-Type": "application/json" }),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...demoHeader(),
    ...(init.headers ?? {}),
  };
}

async function request(
  path: string,
  init: RequestInit = {},
  retried = false,
  timeoutMs = REQUEST_TIMEOUT_MS,
): Promise<Response> {
  let resp: Response;
  try {
    resp = await fetchWithTimeout(path, { ...init, headers: authHeaders(init) }, timeoutMs);
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("请求超时，请检查服务是否可用");
    }
    throw err;
  }
  if (resp.status === 401 && !retried) {
    // 远程设备不要弹本机口令框：它没有本机口令，唯一解法是回电脑重新扫码。
    try {
      if (sessionStorage.getItem("mh.remote") === "1") {
        sessionStorage.removeItem("mh.remote");
        // 直接回配对页：手机上继续显示旧页面只会让用户以为还能用
        window.location.replace("/remote?expired=1");
        throw new Error("远程连接已失效，请重新扫码");
      }
    } catch (err) {
      if (err instanceof Error && err.message.includes("重新扫码")) throw err;
    }
    const input = await askAuth();
    if (input) {
      setToken(input.trim());
      return request(path, init, true, timeoutMs);
    }
    throw new Error("需要访问口令");
  }
  return resp;
}

/** 把非 2xx 响应翻译成「人能读懂的句子」，不能是裸状态码。
 *  代理层 502/504 常返回 HTML 而非 JSON，只显示 "500" / "502" 时用户无法判断
 *  是服务没启动、接口报错、还是网络断了。api() 与 apiDownload() 共用这一份，
 *  避免两套文案各说各话（也避免新增无法翻译的词条）。 */
async function responseDetail(resp: Response, cloneForJson: boolean): Promise<string> {
  let detail = `请求失败（HTTP ${resp.status}）`;
  try {
    const body = await (cloneForJson ? resp.clone() : resp).json();
    detail = body?.error ?? body?.detail ?? body?.message ?? detail;
  } catch {
    if (resp.status >= 500) detail = `服务暂时不可用（HTTP ${resp.status}），请稍后重试或检查后端是否已启动`;
    else if (resp.status === 401) detail = "需要访问口令";
    else if (resp.status === 404) detail = "接口不存在（HTTP 404），请确认前后端版本一致";
  }
  return detail;
}

export interface ApiOptions {
  /** 覆盖默认 20s 超时（上传/解析类用 SLOW_REQUEST_TIMEOUT_MS） */
  timeoutMs?: number;
}

export async function api<T>(path: string, init: RequestInit = {}, opts: ApiOptions = {}): Promise<T> {
  const resp = await request(path, init, false, opts.timeoutMs ?? REQUEST_TIMEOUT_MS);
  if (!resp.ok) throw new Error(await responseDetail(resp, false));
  // 部分接口（如 DELETE）可能返回空 body，避免对空串调 json() 报 SyntaxError
  const text = await resp.text();
  return (text ? (JSON.parse(text) as T) : ({} as T));
}

/** 把 Blob 存成本地文件：三处手写过同样的 `a.href=createObjectURL → click → revoke`，
 *  抽出来避免各写一遍（漏 revoke 会一直占内存）。 */
export function saveBlob(blob: Blob, filename: string): void {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

/** 读取二进制响应（图片/PDF 预览）：必须走统一 request 才能带口令与 401 处理。 */
export async function apiBlob(path: string, opts: ApiOptions = {}): Promise<Blob> {
  const resp = await request(path, {}, false, opts.timeoutMs ?? REQUEST_TIMEOUT_MS);
  if (!resp.ok) throw new Error(await responseDetail(resp, true));
  return resp.blob();
}

/** 下载类接口统一入口：必须走 fetch 才能带上 Authorization。
 *  以前直接用 `<a href="/api/export/report">`，浏览器不会附带 Bearer 头，
 *  配了口令或启用了账号体系时后端返回 401，但 a.click() 不报错，
 *  界面还会提示"已下载"——用户拿到的是一个 401 报错页或空文件。 */
export async function apiDownload(
  path: string,
  filename: string,
  opts: ApiOptions = {},
): Promise<void> {
  const resp = await request(path, {}, false, opts.timeoutMs ?? SLOW_REQUEST_TIMEOUT_MS);
  if (!resp.ok) throw new Error(await responseDetail(resp, true));
  saveBlob(await resp.blob(), filename);
}

/** 内部信号：需要用户重新输口令（触发一次带新口令的重试） */
class ReauthError extends Error {}
/** 致命错误：不重试，直接抛给调用方 */
class FatalError extends Error {}

/**
 * SSE 流式问答：用微软官方 fetch-event-source。
 *
 * 生产级增强：
 * - 指数退避重连：首次断连等 1s，第二次 2s，第三次 4s，最多 5 次
 * - 网络恢复自动重试：监听 online 事件，断连后网络恢复时立即重试
 * - 页面隐藏不打断：openWhenHidden=true（提问后切标签页也不中断生成）
 * - 已收到内容不重试：got 后断连直接报错（重试会重跑一遍后端）
 *
 * fetch-event-source 的 onerror 语义：返回数字=延迟后重试，抛错=停止重试。
 */

const MAX_RETRIES = 5;
const BASE_RETRY_MS = 1000;

export async function apiStream(
  path: string,
  body: unknown,
  onLine: (obj: Record<string, unknown>) => void,
  signal?: AbortSignal,
  retried = false,
): Promise<void> {
  let got = false;
  // 是否收到服务端的终帧。只有收到 done 才算这条流成功走完；
  // 仅有"收到过内容"不足以判定成功——断连时也会 got=true，
  // 旧逻辑会直接 return，把半截回答当成完整结果展示给用户。
  let completed = false;
  let retryCount = 0;

  try {
    while (retryCount <= MAX_RETRIES) {
      if (signal?.aborted) break;

      // 离线时等网络恢复再试
      if (!navigator.onLine) {
        await _waitForOnline(signal);
        if (signal?.aborted) break;
      }

      try {
        await _fetchOnce(path, body, signal, retried, (obj) => {
          got = true;
          if (obj && obj.type === "done") completed = true;
          onLine(obj);
        });
        if (completed) return; // 收到终帧才算完整接收
        // 连接正常关闭但没收到 done：一律视为断流，交给重试逻辑。
        // 此前 got=false（一帧都没收到，例如反代超时/后端 204）时直接 return，
        // 调用方以为成功，气泡留空并永久显示「分析中」。
        if (got) throw new Error("流式连接提前结束（未收到完成标记）");
        throw new Error("流式连接未返回任何数据（服务端或代理中断）");
      } catch (err) {
        if (signal?.aborted) break;
        if (err instanceof ReauthError) {
          return apiStream(path, body, onLine, signal, true);
        }
        if (err instanceof FatalError) throw err;
        // 已经收到部分内容：不重放（会重复半段），但必须把"未完成"如实抛出，
        // 否则 UI 会把半截回答当成完整结果（旧逻辑在这里静默 return）。
        if (got) {
          throw err instanceof Error ? err : new Error("流式连接中断");
        }
        retryCount++;
        if (retryCount > MAX_RETRIES) {
          throw new Error(`流式连接中断，已重试 ${MAX_RETRIES} 次`);
        }
        const delay = BASE_RETRY_MS * 2 ** (retryCount - 1);
        // 每次重试创建新的 onlinePromise，防止"首次恢复后背底失效"
        await Promise.race([
          _sleep(delay, signal),
          new Promise<void>((resolve) => {
            if (navigator.onLine) { resolve(); return; }
            const onOnline = () => { window.removeEventListener("online", onOnline); resolve(); };
            window.addEventListener("online", onOnline);
            // signal abort 时也退出
            signal?.addEventListener("abort", () => {
              window.removeEventListener("online", onOnline);
              resolve();
            }, { once: true });
          }),
        ]);
      }
    }
  } finally {
    // cleanup 已内联到 Promise 构造中
  }

  if (signal?.aborted) {
    const e = new Error("aborted");
    e.name = "AbortError";
    throw e;
  }
}

/** 单次 SSE 连接（内部辅助，不含重试逻辑） */
async function _fetchOnce(
  path: string,
  body: unknown,
  signal: AbortSignal | undefined,
  retried: boolean,
  onLine: (obj: Record<string, unknown>) => void,
): Promise<void> {
  const token = getToken();
  await fetchEventSource(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...demoHeader(),
    },
    body: JSON.stringify(body),
    signal,
    openWhenHidden: true,
    async onopen(response) {
      if (response.status === 401) {
        if (!retried) {
          const input = await askAuth();
          if (input) {
            setToken(input.trim());
            throw new ReauthError();
          }
        }
        throw new FatalError("需要访问口令");
      }
      if (!response.ok) {
        let detail = `${response.status}`;
        try {
          const b = await response.clone().json();
          if (b?.error) detail = b.error;
        } catch {
          /* ignore */
        }
        throw new FatalError(detail);
      }
    },
    onmessage(ev) {
      if (!ev.data || ev.data === "[DONE]") return;
      try {
        onLine(JSON.parse(ev.data) as Record<string, unknown>);
      } catch {
        /* 忽略坏帧 */
      }
    },
    onclose() {
      // 对端正常关闭 → 不重试
    },
    onerror(err) {
      if (err instanceof ReauthError || err instanceof FatalError) throw err;
      if (signal?.aborted) throw err;
      throw err; // 交给外层 while 循环做重试
    },
  });
}

/** 等待网络恢复（或 signal 中止） */
function _waitForOnline(signal?: AbortSignal): Promise<void> {
  if (navigator.onLine) return Promise.resolve();
  return new Promise((resolve) => {
    const onOnline = () => {
      cleanup();
      resolve();
    };
    const onAbort = () => {
      cleanup();
      resolve();
    };
    const cleanup = () => {
      window.removeEventListener("online", onOnline);
      signal?.removeEventListener("abort", onAbort);
    };
    window.addEventListener("online", onOnline);
    signal?.addEventListener("abort", onAbort);
  });
}

function _sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(t);
      resolve();
    });
  });
}


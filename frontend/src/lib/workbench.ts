/** 右侧工作台 · 浏览器地址规范化。
 *
 * 用户输入往往只有域名（quote.eastmoney.com）或一句中文；统一在这里转成
 * 可放进 iframe 的 http(s) 地址。任何 javascript:/data: 之类都拒绝——
 * 这个地址来自用户输入与回答里的链接，不能成为执行入口。
 */

export const OPEN_URL_EVENT = "moneyhelper:open-url";

export interface OpenUrlDetail {
  url: string;
}

/** 把输入变成安全 URL；中文/空格按搜索词处理，其余补 https://。 */
export function normalizeBrowserUrl(raw: string): string {
  const text = (raw ?? "").trim();
  if (!text) return "";
  // 已经带协议：只放行 http/https
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(text)) {
    try {
      const u = new URL(text);
      return u.protocol === "http:" || u.protocol === "https:" ? u.toString() : "";
    } catch {
      return "";
    }
  }
  // 像域名 / IP / localhost：补协议
  if (/^(localhost|(\d{1,3}\.){3}\d{1,3})(:\d+)?(\/|$)/.test(text) || /^[^\s/]+\.[^\s/]+/.test(text)) {
    try {
      const u = new URL(`https://${text}`);
      return u.protocol === "https:" ? u.toString() : "";
    } catch {
      return "";
    }
  }
  // 其余当成搜索词（中文站内搜索走百度，国内网络可达）
  return `https://www.baidu.com/s?wd=${encodeURIComponent(text)}`;
}

/** 仅用于 UI 展示的简短域名。 */
export function hostLabel(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}

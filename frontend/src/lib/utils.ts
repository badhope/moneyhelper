/** className 合并：clsx（条件拼接）+ tailwind-merge（后项覆盖冲突类名）。
 *
 * 为什么不用手写 join：手写版会把 `bg-red-500` 和 `bg-blue-500` 同时留在 class 里，
 * 后写的不一定生效（取决于 CSS 源顺序）；twMerge 能识别 tailwind 冲突并保留后者。
 */

import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...parts: ClassValue[]): string {
  return twMerge(clsx(parts));
}


/**
 * 错误信息归一化 —— 和 `cn` 同属"全站都要用的小工具"，所以放在一起。
 *
 * `catch` 块里把任何异常变成一句可展示的文案，每个页面都要做。改造前这段
 * "取 message / 兜底 toString"的三元表达式在 20 个文件里抄了 132 遍，
 * 抄多了必然漂移：出现 `e` / `err` / `ex` / `error` 四种变量命名，
 * 还有"忘了取 message、直接把对象塞进 toast 渲染成 [object Object]"这类
 * 只在网络异常时才暴露的缺陷。
 *
 * 顺序：Error → 取 message；非空字符串 → 直接用（后端会返回字符串错误，
 * 如 409 的冲突提示）；否则用调用方给的 `fallback`（"JSON 解析失败"等）；
 * 最后才退到 `String()` —— 这层顺序保证用户永远看不到 `[object Object]`。
 */
export function errMsg(e: unknown, fallback?: string): string {
  if (e instanceof Error) return e.message;
  if (typeof e === "string" && e) return e;
  if (fallback) return fallback;
  return e == null ? "" : String(e);
}

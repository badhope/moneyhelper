/** 演示账本开关。
 *
 * 真实账本与演示账本在服务端是两套独立租户；前端只保存一个开关，
 * 每个 API 请求带 `X-Demo-Mode: 1` 决定读哪一套。切换后整页重载，
 * 避免旧查询缓存把两套数字混在同一屏。
 */
import { useEffect, useState } from "react";

const KEY = "mh.demoMode";
const EVENT = "mh:demo-mode-change";

export function isDemoMode(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function setDemoMode(on: boolean): void {
  try {
    if (on) localStorage.setItem(KEY, "1");
    else localStorage.removeItem(KEY);
  } catch {
    /* 隐私模式下 localStorage 不可用：退化为仅本次页面 */
  }
  window.dispatchEvent(new Event(EVENT));
}

export function demoHeader(): Record<string, string> {
  return isDemoMode() ? { "X-Demo-Mode": "1" } : {};
}

export function useDemoMode(): boolean {
  const [on, setOn] = useState(isDemoMode);
  useEffect(() => {
    const sync = () => setOn(isDemoMode());
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  return on;
}

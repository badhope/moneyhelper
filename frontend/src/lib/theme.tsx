/** 主题系统：浅色/深色/跟随系统 + 品牌主题色预设，本机持久化（localStorage），即时生效，不依赖服务端。 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { BRAND_PRESETS } from "@/lib/brand";

export type ThemeMode = "light" | "dark" | "system";

const KEYS = { theme: "wo.theme", preset: "wo.preset" };
/** "default" = 不注入任何变量，回落 index.css 的默认墨绿主题 */
export const DEFAULT_PRESET = "default";

const PRESET_STYLE_ID = "brand-preset-vars";

/** 生成品牌预设的 CSS 变量注入内容（:root 明色 + .dark 暗色两套；空串 = 回落默认主题）。 */
export function presetCss(presetId: string): string {
  const preset = BRAND_PRESETS.find((p) => p.id === presetId);
  if (!preset) return "";
  const decl = (vars: Record<string, string>) =>
    Object.entries(vars).map(([k, v]) => `${k}: ${v};`).join(" ");
  return `:root { ${decl(preset.light)} }\n.dark { ${decl(preset.dark)} }`;
}

interface ThemeState {
  theme: ThemeMode;
  /** 实际生效的明暗（system 已解析） */
  resolved: "light" | "dark";
  setTheme: (v: ThemeMode) => void;
  /** 品牌主题色预设 id（default = 墨绿默认主题） */
  preset: string;
  setPreset: (v: string) => void;
}

const ThemeCtx = createContext<ThemeState | null>(null);

function load<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v ? (v as T) : fallback;
  } catch {
    return fallback;
  }
}

function save(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}

function systemDark(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  // 默认亮色：首次打开不做「跟随系统」猜测。
  // 理由：这个应用的主场景是白天记账/看盘，跟随系统会让晚上系统切深色后
  // 报表上的红涨绿跌与浅底对比度整体变暗；而用户一旦手动切换过，
  // localStorage 会记住选择，"跟随系统"仍然是设置里可选的第三项。
  const [theme, setThemeState] = useState<ThemeMode>(() => load<ThemeMode>(KEYS.theme, "light"));
  const [preset, setPresetState] = useState<string>(() => load<string>(KEYS.preset, DEFAULT_PRESET));

  const resolved: "light" | "dark" =
    theme === "system" ? (systemDark() ? "dark" : "light") : theme;

  // 明暗 -> html 属性
  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", resolved === "dark");
    root.dataset.theme = resolved;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", resolved === "dark" ? "#0b1120" : "#f6f8fb");
  }, [resolved]);

  // 品牌主题色：注入一段覆盖 :root/.dark 变量的 <style>（后加载者胜出，覆盖 index.css 默认值）
  useEffect(() => {
    let el = document.getElementById(PRESET_STYLE_ID) as HTMLStyleElement | null;
    const css = presetCss(preset);
    if (css) {
      if (!el) {
        el = document.createElement("style");
        el.id = PRESET_STYLE_ID;
        document.head.appendChild(el);
      }
      el.textContent = css;
    } else if (el) {
      el.textContent = "";
    }
    document.documentElement.dataset.preset = preset;
  }, [preset]);

  // 跟随系统切换（首帧与主 effect 一致；后续系统明暗变化只改 class 与 meta）
  useEffect(() => {
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => {
      const root = document.documentElement;
      root.classList.toggle("dark", mq.matches);
      const meta = document.querySelector('meta[name="theme-color"]');
      if (meta) meta.setAttribute("content", mq.matches ? "#0b1120" : "#f6f8fb");
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [theme]);

  const setTheme = useCallback((v: ThemeMode) => {
    setThemeState(v);
    save(KEYS.theme, v);
  }, []);

  const setPreset = useCallback((v: string) => {
    setPresetState(v);
    save(KEYS.preset, v);
  }, []);

  const value = useMemo<ThemeState>(
    () => ({ theme, resolved, setTheme, preset, setPreset }),
    [theme, resolved, setTheme, preset, setPreset],
  );

  return <ThemeCtx.Provider value={value}>{children}</ThemeCtx.Provider>;
}

export function useTheme(): ThemeState {
  const ctx = useContext(ThemeCtx);
  if (!ctx) throw new Error("useTheme 必须在 ThemeProvider 内使用");
  return ctx;
}

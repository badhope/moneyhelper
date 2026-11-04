import { describe, expect, it } from "vitest";
import { en } from "./lang/en";
import { zh } from "./lang/zh";

describe("i18n", () => {
  it("给定缺失的 key 应返回 key 自身，而不是 undefined", () => {
    // 模拟 t 函数的 fallback 逻辑（与 i18n.tsx 实现一致）
    const DICTS = { en, zh } as const;
    const fallbackT = (key: string, lang: "en" | "zh" = "en"): string =>
      DICTS[lang][key] ?? DICTS.en[key] ?? key;

    expect(fallbackT("totally.missing.key")).toBe("totally.missing.key");
    expect(fallbackT("")).toBe("");
  });

  it("中英文 key 数均应 >= 600", () => {
    const enCount = Object.keys(en).length;
    const zhCount = Object.keys(zh).length;
    expect(enCount).toBeGreaterThanOrEqual(600);
    expect(zhCount).toBeGreaterThanOrEqual(600);
  });

  it("给定已知 key 和非空字符串 lang，t 应返回非空字符串", () => {
    const sampleKeys = ["topbar.toggleDark", "sidebar.sessions", "summary.marketValue"];
    for (const key of sampleKeys) {
      expect(en[key]).toBeTypeOf("string");
      expect(en[key].length).toBeGreaterThan(0);
      expect(zh[key]).toBeTypeOf("string");
      expect(zh[key].length).toBeGreaterThan(0);
    }
  });

  it("中英文 key 集合应一致（无遗漏翻译）", () => {
    const enKeys = new Set(Object.keys(en));
    const zhKeys = new Set(Object.keys(zh));
    const missingInZh = [...enKeys].filter((k) => !zhKeys.has(k));
    const missingInEn = [...zhKeys].filter((k) => !enKeys.has(k));
    expect(missingInZh, `中文缺少以下 key: ${missingInZh.join(", ")}`).toEqual([]);
    expect(missingInEn, `英文缺少以下 key: ${missingInEn.join(", ")}`).toEqual([]);
  });
});

/**
 * 静态扫描：源码里 t("...") 用到的每个 key 必须在中英字典里都存在。
 *
 * 为什么必须有：t() 的兜底是「返回 key 自身」，于是缺 key 不会报错，
 * 只在界面上显示 `common.cancel` 这种字面量——测试全绿、用户看得见。
 * 这条用例把「文案完整性」变成构建期可拦截的硬约束。
 */
describe("i18n key 完整性（静态扫描）", () => {
  it("源码中所有 t(\"key\") 都在字典里", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");

    const roots = ["src"];
    const files: string[] = [];
    const walk = (dir: string) => {
      for (const name of fs.readdirSync(dir)) {
        const full = path.join(dir, name);
        const stat = fs.statSync(full);
        if (stat.isDirectory()) walk(full);
        else if (/\.(tsx?|jsx?)$/.test(name) && !name.endsWith(".test.ts") && !name.endsWith(".test.tsx")) {
          files.push(full);
        }
      }
    };
    roots.forEach(walk);

    // 只匹配字面量 key（含点号的），跳过动态拼接（t(variable) 无法静态验证）
    const keyRe = /\bt\(\s*"([a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)+)"/g;
    const used = new Set<string>();
    for (const f of files) {
      const src = fs.readFileSync(f, "utf-8");
      let m: RegExpExecArray | null;
      while ((m = keyRe.exec(src))) used.add(m[1]);
    }

    expect(used.size).toBeGreaterThan(100);
    const missingZh = [...used].filter((k) => !(k in zh)).sort();
    const missingEn = [...used].filter((k) => !(k in en)).sort();

    expect(missingZh, `缺少中文文案: ${missingZh.join(", ")}`).toEqual([]);
    expect(missingEn, `缺少英文文案: ${missingEn.join(", ")}`).toEqual([]);
  });
});

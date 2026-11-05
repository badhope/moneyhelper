// 敌意输入测试：格式化函数对任何「后端可能给出的值」都必须返回可读字符串。
//
// 为什么只测格式化层：前端崩溃高发位置是数字格式化（null/NaN/Infinity 传进
// toFixed/toLocaleString），而后端 4.13.2 已把 NaN/Inf 挡在写入层。
// 后端挡不住的（历史脏数据、外部行情 API 返回垃圾）最终都会流到这里。
//
// 契约：任何输入 → 输出不含 "NaN" / "undefined" / "Infinity%" / "Invalid Date"
// / "-0.00"——这些是用户肉眼可见的渲染事故。

import { describe, expect, it, beforeEach } from "vitest";
import {
  fmtMoney,
  fmtPct,
  fmtDate,
  fmtMonth,
  fmtTokens,
  pnlClass,
  setMoneyLocale,
} from "./format";

// 后端/行情可能给进来的垃圾值全集
const HOSTILE_NUMBERS = [
  NaN,
  Infinity,
  -Infinity,
  -0,
  0,
  1e15,
  -1e15,
  Number.MAX_SAFE_INTEGER + 1,
  0.0000001,
  -0.004,
];

const HOSTILE_STRINGS = ["", "garbage", "not-a-date", "2026-13-45", "NaN", "undefined"];

function assertReadable(output: string, context: string) {
  expect(output, context).toBeTruthy();
  for (const bad of ["NaN", "undefined", "Infinity%", "Invalid Date", "-0.00"]) {
    expect(output, `${context} → "${output}" 含 ${bad}`).not.toContain(bad);
  }
}

describe("fmtMoney 敌意输入", () => {
  beforeEach(() => setMoneyLocale("zh"));

  for (const v of HOSTILE_NUMBERS) {
    it(`处理 ${String(v)}`, () => {
      assertReadable(fmtMoney(v), `fmtMoney(${String(v)})`);
      assertReadable(fmtMoney(v, true, true), `fmtMoney(${String(v)}, compact)`);
    });
  }

  it("null/undefined 显示占位符", () => {
    expect(fmtMoney(null)).toBe("-");
    expect(fmtMoney(undefined)).toBe("-");
  });

  it("-0 不带负号", () => {
    const out = fmtMoney(-0);
    expect(out).not.toMatch(/^-/);
  });
});

describe("fmtPct 敌意输入", () => {
  for (const v of HOSTILE_NUMBERS) {
    it(`处理 ${String(v)}`, () => {
      assertReadable(fmtPct(v), `fmtPct(${String(v)})`);
      assertReadable(fmtPct(v, true), `fmtPct(${String(v)}, sign)`);
    });
  }

  it("-0 显示为 0.00% 而非 -0.00%", () => {
    expect(fmtPct(-0)).not.toContain("-0.00");
  });
});

describe("fmtDate / fmtMonth 敌意输入", () => {
  for (const s of HOSTILE_STRINGS) {
    it(`fmtDate(${s || "空串"})`, () => {
      assertReadable(fmtDate(s), `fmtDate("${s}")`);
    });
  }

  it("fmtMonth 越界月份不输出 undefined", () => {
    for (const s of ["2026-13", "2026-0", "abc", ""]) {
      const out = fmtMonth(s);
      // 空输入允许空串回退（UI 显示为空，无害）；其余必须可读
      for (const badWord of ["NaN", "undefined", "Invalid"]) {
        expect(out, `fmtMonth("${s}") 含 ${badWord}`).not.toContain(badWord);
      }
    }
  });
});

describe("fmtTokens / pnlClass 敌意输入", () => {
  for (const v of HOSTILE_NUMBERS) {
    it(`fmtTokens(${String(v)})`, () => {
      assertReadable(fmtTokens(v as number), `fmtTokens(${String(v)})`);
    });
  }

  it("pnlClass 对任何输入返回字符串", () => {
    for (const v of [...HOSTILE_NUMBERS, null, undefined]) {
      expect(typeof pnlClass(v as number)).toBe("string");
    }
  });
});

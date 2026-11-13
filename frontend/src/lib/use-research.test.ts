import { describe, expect, it } from "vitest";
import { isBacktestParamsValid } from "./use-research";

describe("isBacktestParamsValid", () => {
  it("默认参数（fast 5 / slow 20）可用", () => {
    expect(isBacktestParamsValid("ma_cross", {})).toBe(true);
  });

  it("fast >= slow 不可用：后端会 400，请求不该发出去", () => {
    expect(isBacktestParamsValid("ma_cross", { fast: 50, slow: 5 })).toBe(false);
    expect(isBacktestParamsValid("ma_cross", { fast: 20, slow: 20 })).toBe(false);
  });

  it("fast 小于 2 不可用（与后端 ge=2 一致）", () => {
    expect(isBacktestParamsValid("ma_cross", { fast: 1, slow: 20 })).toBe(false);
  });

  it("非均线策略不校验 fast/slow", () => {
    expect(isBacktestParamsValid("dca", { fast: 50, slow: 5 })).toBe(true);
    expect(isBacktestParamsValid("grid", {})).toBe(true);
  });

  it("合法的自定义组合可用", () => {
    expect(isBacktestParamsValid("ma_cross", { fast: 10, slow: 60 })).toBe(true);
  });
});

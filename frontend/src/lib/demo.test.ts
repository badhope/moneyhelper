import { afterEach, describe, expect, it } from "vitest";
import { demoHeader, isDemoMode, setDemoMode } from "./demo";

afterEach(() => localStorage.clear());

describe("demo mode", () => {
  it("只在用户显式开启后附加演示请求头", () => {
    expect(isDemoMode()).toBe(false);
    expect(demoHeader()).toEqual({});
    setDemoMode(true);
    expect(isDemoMode()).toBe(true);
    expect(demoHeader()).toEqual({ "X-Demo-Mode": "1" });
  });

  it("关闭后立即回到真实数据请求", () => {
    setDemoMode(true);
    setDemoMode(false);
    expect(isDemoMode()).toBe(false);
    expect(demoHeader()).toEqual({});
  });
});

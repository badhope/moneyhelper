import { describe, expect, it } from "vitest";
import { errMsg } from "@/lib/utils";

describe("errMsg", () => {
  it("取 Error.message，不带类型前缀", () => {
    expect(errMsg(new Error("预算不足"))).toBe("预算不足");
  });

  it("字符串原样返回", () => {
    expect(errMsg("409 冲突")).toBe("409 冲突");
  });

  it("空字符串被视为无信息，让位给兜底文案", () => {
    expect(errMsg("", "解析失败")).toBe("解析失败");
  });

  it("给了兜底文案时，对象不再渲染成 [object Object]", () => {
    expect(errMsg({ code: 500 }, "解析失败")).toBe("解析失败");
    expect(errMsg(null, "解析失败")).toBe("解析失败");
  });

  it("无兜底时退到 String()，不抛异常", () => {
    expect(errMsg(42)).toBe("42");
    expect(errMsg(undefined)).toBe("");
  });
});
